"""Safe migration of legacy ``users.json`` account and authentication data.

Preview never opens SQLite. Apply installs the additive application schema only
after an exact approval and unchanged-source check, then imports every account
in one ``BEGIN IMMEDIATE`` transaction. The legacy file is never rewritten.

Recoverable authentication factors and notification capabilities are removed
from plaintext columns/JSON and stored only in the account's AES-GCM envelope.
Existing one-way password, token, backup-code, and trusted-device hashes remain
byte-for-byte unchanged in plaintext authentication metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import user_account_service
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor
from PushShoppingList.services.data_encryption_service import DataEncryptionError
from PushShoppingList.services.data_encryption_service import EncryptedEnvelope
from PushShoppingList.services.data_encryption_service import SecretEncryptor


APPLY_APPROVAL_PHRASE = "APPLY ACCOUNT DATA MIGRATION"
SOURCE_KIND = "legacy_users_json"
MIGRATION_DOMAIN = "identity"
WORKSPACE_TYPE = "user"
SCHEMA_VERSION = 1
SECRET_AAD_VERSION = 1
MAX_SOURCE_BYTES = 16 * 1024 * 1024
_SAFE_STATUS_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{1,160}$")


class AccountDataMigrationError(RuntimeError):
    """Base class for account migration failures."""


class AccountMigrationApprovalError(AccountDataMigrationError):
    """Raised when apply lacks the exact approval phrase."""


class AccountMigrationSourceError(AccountDataMigrationError):
    """Raised when the legacy source cannot be migrated safely."""


class StaleAccountMigrationPreviewError(AccountMigrationSourceError):
    """Raised when ``users.json`` changed after preview."""


class AccountMigrationCollisionError(AccountDataMigrationError):
    """Raised when an existing database identity has different content."""


class AccountMigrationEncryptionError(AccountDataMigrationError):
    """Raised when recoverable secrets cannot be encrypted safely."""


class _DuplicateJsonKeyError(ValueError):
    pass


class _AccountShapeError(ValueError):
    pass


@dataclass(frozen=True)
class AccountMigrationPreview:
    """Payload-free source inventory safe for logs and operator review."""

    created_at: str
    status: str
    source_sha256: Optional[str]
    byte_count: int
    account_count: int
    profile_field_count: int
    auth_metadata_field_count: int
    accounts_requiring_encryption: int
    secret_field_counts: Mapping[str, int]
    preserved_hash_counts: Mapping[str, int]
    error_code: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def encryption_required(self) -> bool:
        return self.accounts_requiring_encryption > 0

    def to_dict(self) -> Dict[str, object]:
        result = asdict(self)
        result["encryption_required"] = self.encryption_required
        result["ready"] = self.ready
        return result


@dataclass(frozen=True)
class AccountMigrationApplyResult:
    applied_at: str
    source_sha256: str
    migration_run_id: Optional[str]
    account_count: int
    inserted_accounts: int
    unchanged_accounts: int
    inserted_workspaces: int
    updated_workspaces: int
    unchanged_workspaces: int
    coverage_rows: int
    no_op: bool
    validation: Mapping[str, int]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _PreparedAccount:
    account_id: str
    workspace_id: str
    record_sha256: str
    username: str
    normalized_email: str
    status: str
    password_hash: str
    firebase_uid: str
    provider: str
    created_at: str
    updated_at: str
    profile_json: str
    auth_metadata_json: str
    secret_payload: Mapping[str, object]


_STRING_FIELDS = {
    "account_status",
    "auth_provider",
    "avatar_path",
    "browser_notification_permission",
    "browser_push_subscription_updated_at",
    "created_at",
    "email",
    "email_verified_at",
    "firebase_last_login_at",
    "firebase_sign_in_provider",
    "firebase_uid",
    "first_name",
    "last_login_at",
    "last_name",
    "last_notification_received",
    "last_notification_sent",
    "last_test_notification",
    "notification_topic",
    "notification_topic_created_at",
    "ntfy_topic",
    "ntfy_topic_created_at",
    "password_hash",
    "phone",
    "phone_verified_at",
    "picture",
    "two_factor_disabled_by_admin_actor",
    "two_factor_disabled_by_admin_at",
    "two_factor_disabled_by_admin_reason",
    "updated_at",
    "user_id",
    "username",
}
_BOOLEAN_FIELDS = {
    "admin_access_enabled",
    "firebase_email_verified",
    "notifications_enabled",
}
_OBJECT_FIELDS = {
    "account_delete",
    "account_verification",
    "browser_push_subscription",
    "notification_preferences",
    "password_reset",
    "phone_verification",
    "two_factor",
    "two_factor_recovery",
    "two_factor_setup",
}
_ARRAY_FIELDS = {"firebase_provider_ids", "notification_devices"}
KNOWN_ACCOUNT_FIELDS = frozenset(
    _STRING_FIELDS | _BOOLEAN_FIELDS | _OBJECT_FIELDS | _ARRAY_FIELDS
)

PROFILE_FIELDS = frozenset({
    "avatar_path",
    "browser_notification_permission",
    "browser_push_subscription_updated_at",
    "email",
    "email_verified_at",
    "first_name",
    "last_name",
    "last_notification_received",
    "last_notification_sent",
    "last_test_notification",
    "notification_devices",
    "notification_preferences",
    "notification_topic_created_at",
    "notifications_enabled",
    "ntfy_topic_created_at",
    "phone",
    "phone_verified_at",
    "picture",
})

AUTH_METADATA_FIELDS = frozenset({
    "account_delete",
    "account_verification",
    "admin_access_enabled",
    "firebase_email_verified",
    "firebase_last_login_at",
    "firebase_provider_ids",
    "firebase_sign_in_provider",
    "last_login_at",
    "password_reset",
    "phone_verification",
    "two_factor",
    "two_factor_disabled_by_admin_actor",
    "two_factor_disabled_by_admin_at",
    "two_factor_disabled_by_admin_reason",
    "two_factor_recovery",
    "two_factor_setup",
})

SECRET_TOP_LEVEL_FIELDS = frozenset({
    "browser_push_subscription",
    "notification_topic",
    "ntfy_topic",
})

_TOKEN_STATE_FIELDS = frozenset({"token_hash", "created_at", "expires_at"})
_PHONE_VERIFICATION_FIELDS = frozenset({
    "code_hash",
    "created_at",
    "expires_at",
    "phone",
})
_TWO_FACTOR_FIELDS = frozenset({
    "backup_codes",
    "enabled",
    "enabled_at",
    "secret",
    "setup_confirmation_required",
    "setup_confirmed_at",
    "trusted_devices",
})
_TWO_FACTOR_SETUP_FIELDS = frozenset({"created_at", "secret"})
_BACKUP_CODE_FIELDS = frozenset({"code_hash", "used_at"})
_TRUSTED_DEVICE_FIELDS = frozenset({"token_hash", "created_at", "expires_at"})
_NOTIFICATION_DEVICE_FIELDS = frozenset({
    "key",
    "last_seen_at",
    "last_seen_at_label",
    "name",
    "status",
})
_NOTIFICATION_PREFERENCE_FIELDS = frozenset({
    "cloudflare_upload_complete",
    "feedback_response",
    "pantry_expiration_reminders",
    "recipe_import_complete",
    "recipe_pdf_generated",
    "security_alerts",
    "shopping_list_updated",
    "store_search_complete",
})

_HASH_PATHS = (
    ("password_hash",),
    ("account_verification", "token_hash"),
    ("password_reset", "token_hash"),
    ("phone_verification", "code_hash"),
    ("account_delete", "token_hash"),
    ("two_factor_recovery", "token_hash"),
)


def account_users_file_path(source_path=None) -> Path:
    """Resolve the legacy source lazily so tests can monkeypatch it."""
    if source_path is not None:
        return Path(source_path)
    return Path(user_account_service.USERS_FILE)


def account_migration_db_path(db_path=None) -> Path:
    """Resolve the application database lazily through its owning service."""
    if db_path is not None:
        return Path(db_path)
    return Path(application_data.application_data_db_path())


def account_secret_associated_data(account_id: str) -> str:
    _validate_opaque_id(account_id, "account_id")
    return "account\x1f%s\x1flegacy-auth-secrets\x1fv%d" % (
        account_id,
        SECRET_AAD_VERSION,
    )


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _timestamp(clock: Optional[Callable[[], datetime]]) -> str:
    value = clock() if clock is not None else datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_opaque_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or value == "" or "\x00" in value:
        raise _AccountShapeError(
            "%s must be a non-empty opaque string" % field_name
        )


def _strict_json_loads(raw: bytes) -> object:
    text = raw.decode("utf-8-sig", errors="strict")

    def object_pairs(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKeyError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("non_finite_json_number")

    return json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _read_source(source_path: Path) -> Tuple[bytes, object]:
    if not source_path.is_file():
        raise FileNotFoundError("legacy account source is missing")
    raw = source_path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise _AccountShapeError("source_too_large")
    return raw, _strict_json_loads(raw)


def _validate_exact_keys(value: Mapping[str, object], allowed, code: str) -> None:
    if set(value).difference(allowed):
        raise _AccountShapeError(code)


def _validate_optional_strings(value: Mapping[str, object], fields, code: str) -> None:
    for field in fields:
        if field in value and not isinstance(value[field], str):
            raise _AccountShapeError(code)


def _validate_token_state(value: object, code: str) -> None:
    if not isinstance(value, dict):
        raise _AccountShapeError(code)
    _validate_exact_keys(value, _TOKEN_STATE_FIELDS, code)
    _validate_optional_strings(value, _TOKEN_STATE_FIELDS, code)


def _validate_phone_verification(value: object) -> None:
    if not isinstance(value, dict):
        raise _AccountShapeError("invalid_phone_verification")
    _validate_exact_keys(
        value,
        _PHONE_VERIFICATION_FIELDS,
        "invalid_phone_verification",
    )
    _validate_optional_strings(
        value,
        _PHONE_VERIFICATION_FIELDS,
        "invalid_phone_verification",
    )


def _validate_two_factor(value: object) -> None:
    if not isinstance(value, dict):
        raise _AccountShapeError("invalid_two_factor")
    _validate_exact_keys(value, _TWO_FACTOR_FIELDS, "invalid_two_factor")
    for field in ("enabled", "setup_confirmation_required"):
        if field in value and not isinstance(value[field], bool):
            raise _AccountShapeError("invalid_two_factor")
    _validate_optional_strings(
        value,
        {"enabled_at", "secret", "setup_confirmed_at"},
        "invalid_two_factor",
    )

    backup_codes = value.get("backup_codes", [])
    if not isinstance(backup_codes, list):
        raise _AccountShapeError("invalid_backup_codes")
    for item in backup_codes:
        if not isinstance(item, dict):
            raise _AccountShapeError("invalid_backup_codes")
        _validate_exact_keys(item, _BACKUP_CODE_FIELDS, "invalid_backup_codes")
        _validate_optional_strings(
            item,
            _BACKUP_CODE_FIELDS,
            "invalid_backup_codes",
        )

    devices = value.get("trusted_devices", [])
    if not isinstance(devices, list):
        raise _AccountShapeError("invalid_trusted_devices")
    for item in devices:
        if not isinstance(item, dict):
            raise _AccountShapeError("invalid_trusted_devices")
        _validate_exact_keys(
            item,
            _TRUSTED_DEVICE_FIELDS,
            "invalid_trusted_devices",
        )
        _validate_optional_strings(
            item,
            _TRUSTED_DEVICE_FIELDS,
            "invalid_trusted_devices",
        )


def _validate_two_factor_setup(value: object) -> None:
    if not isinstance(value, dict):
        raise _AccountShapeError("invalid_two_factor_setup")
    _validate_exact_keys(
        value,
        _TWO_FACTOR_SETUP_FIELDS,
        "invalid_two_factor_setup",
    )
    _validate_optional_strings(
        value,
        _TWO_FACTOR_SETUP_FIELDS,
        "invalid_two_factor_setup",
    )


def _validate_notification_devices(value: object) -> None:
    if not isinstance(value, list):
        raise _AccountShapeError("invalid_notification_devices")
    for item in value:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            raise _AccountShapeError("invalid_notification_devices")
        _validate_exact_keys(
            item,
            _NOTIFICATION_DEVICE_FIELDS,
            "invalid_notification_devices",
        )
        _validate_optional_strings(
            item,
            _NOTIFICATION_DEVICE_FIELDS,
            "invalid_notification_devices",
        )


def _validate_notification_preferences(value: object) -> None:
    if not isinstance(value, dict):
        raise _AccountShapeError("invalid_notification_preferences")
    _validate_exact_keys(
        value,
        _NOTIFICATION_PREFERENCE_FIELDS,
        "invalid_notification_preferences",
    )
    if any(not isinstance(enabled, bool) for enabled in value.values()):
        raise _AccountShapeError("invalid_notification_preferences")


def _validate_account_record(record: object) -> Mapping[str, object]:
    if not isinstance(record, dict):
        raise _AccountShapeError("account_record_not_object")
    _validate_exact_keys(record, KNOWN_ACCOUNT_FIELDS, "unknown_account_field")
    _validate_opaque_id(record.get("user_id"), "user_id")

    for field in _STRING_FIELDS:
        if field in record and not isinstance(record[field], str):
            raise _AccountShapeError("invalid_account_field_type")
        if field in record and "\x00" in record[field]:
            raise _AccountShapeError("account_field_contains_nul")
    for field in _BOOLEAN_FIELDS:
        if field in record and not isinstance(record[field], bool):
            raise _AccountShapeError("invalid_account_field_type")
    for field in _OBJECT_FIELDS:
        if field in record and not isinstance(record[field], dict):
            raise _AccountShapeError("invalid_account_field_type")
    for field in _ARRAY_FIELDS:
        if field in record and not isinstance(record[field], list):
            raise _AccountShapeError("invalid_account_field_type")

    for field in (
        "account_delete",
        "account_verification",
        "password_reset",
        "two_factor_recovery",
    ):
        if field in record:
            _validate_token_state(record[field], "invalid_%s" % field)
    if "phone_verification" in record:
        _validate_phone_verification(record["phone_verification"])
    if "two_factor" in record:
        _validate_two_factor(record["two_factor"])
    if "two_factor_setup" in record:
        _validate_two_factor_setup(record["two_factor_setup"])
    if "notification_devices" in record:
        _validate_notification_devices(record["notification_devices"])
    if "notification_preferences" in record:
        _validate_notification_preferences(record["notification_preferences"])
    if "firebase_provider_ids" in record and any(
        not isinstance(item, str) for item in record["firebase_provider_ids"]
    ):
        raise _AccountShapeError("invalid_firebase_provider_ids")
    status = record.get("account_status", "active")
    if not _SAFE_STATUS_PATTERN.fullmatch(status):
        raise _AccountShapeError("invalid_account_status")
    for field in ("created_at", "updated_at"):
        timestamp = record.get(field, "")
        if timestamp:
            parsed_text = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
            try:
                parsed = datetime.fromisoformat(parsed_text)
            except ValueError as exc:
                raise _AccountShapeError("invalid_account_timestamp") from exc
            if parsed.tzinfo is None:
                raise _AccountShapeError("invalid_account_timestamp")
    return record


def _hash_count(record: Mapping[str, object]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for path in _HASH_PATHS:
        value: object = record
        for field in path:
            if not isinstance(value, dict) or field not in value:
                value = None
                break
            value = value[field]
        if isinstance(value, str) and value:
            name = ".".join(path)
            counts[name] = counts.get(name, 0) + 1

    two_factor = record.get("two_factor")
    if isinstance(two_factor, dict):
        for backup_code in two_factor.get("backup_codes", []):
            if isinstance(backup_code, dict) and isinstance(
                backup_code.get("code_hash"), str
            ) and backup_code.get("code_hash"):
                counts["two_factor.backup_codes.code_hash"] = (
                    counts.get("two_factor.backup_codes.code_hash", 0) + 1
                )
        for device in two_factor.get("trusted_devices", []):
            if isinstance(device, dict) and isinstance(
                device.get("token_hash"), str
            ) and device.get("token_hash"):
                counts["two_factor.trusted_devices.token_hash"] = (
                    counts.get("two_factor.trusted_devices.token_hash", 0) + 1
                )
    return counts


def _split_account_record(record: Mapping[str, object]) -> Tuple[dict, dict, dict]:
    profile = {
        field: deepcopy(record[field])
        for field in PROFILE_FIELDS
        if field in record
    }
    auth_metadata = {
        field: deepcopy(record[field])
        for field in AUTH_METADATA_FIELDS
        if field in record
    }
    secrets: Dict[str, object] = {}

    for field in SECRET_TOP_LEVEL_FIELDS:
        if field in record:
            secrets[field] = deepcopy(record[field])

    two_factor = auth_metadata.get("two_factor")
    if isinstance(two_factor, dict) and "secret" in two_factor:
        secrets.setdefault("two_factor", {})["secret"] = two_factor.pop("secret")

    setup = auth_metadata.get("two_factor_setup")
    if isinstance(setup, dict) and "secret" in setup:
        secrets.setdefault("two_factor_setup", {})["secret"] = setup.pop("secret")

    _assert_plaintext_secret_free(profile, auth_metadata)
    return profile, auth_metadata, secrets


def _assert_plaintext_secret_free(profile: object, auth_metadata: object) -> None:
    forbidden = {
        "browser_push_subscription",
        "notification_topic",
        "ntfy_topic",
        "secret",
    }

    def walk(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        if set(value).intersection(forbidden):
            raise AccountMigrationEncryptionError(
                "Recoverable account secrets remained in plaintext metadata."
            )
        for child in value.values():
            walk(child)

    walk(profile)
    walk(auth_metadata)


def _prepare_accounts(value: object) -> Tuple[_PreparedAccount, ...]:
    if not isinstance(value, dict) or set(value) != {"users"}:
        raise _AccountShapeError("expected_users_object")
    users = value.get("users")
    if not isinstance(users, list):
        raise _AccountShapeError("users_not_array")

    prepared = []
    seen_ids = set()
    seen_emails = set()
    seen_usernames = set()
    seen_login_identities: Dict[str, str] = {}
    seen_firebase_lookup_ids = set()
    seen_phone_candidates = set()
    for raw_record in users:
        record = _validate_account_record(raw_record)
        account_id = record["user_id"]
        if account_id in seen_ids:
            raise _AccountShapeError("duplicate_account_id")
        seen_ids.add(account_id)

        raw_email = record.get("email", "")
        normalized_email = raw_email.strip().lower()
        if normalized_email and normalized_email in seen_emails:
            raise _AccountShapeError("duplicate_normalized_email")
        if normalized_email:
            seen_emails.add(normalized_email)

        normalized_username = user_account_service.normalize_identity(
            record.get("username", "")
        )
        if normalized_username and normalized_username in seen_usernames:
            raise _AccountShapeError("duplicate_normalized_username")
        if normalized_username:
            seen_usernames.add(normalized_username)

        # Login accepts either a normalized username or normalized email. A
        # cross-field alias is therefore just as ambiguous as two usernames.
        for identity in {normalized_username, normalized_email}:
            if not identity:
                continue
            owner = seen_login_identities.get(identity)
            if owner is not None and owner != account_id:
                raise _AccountShapeError("duplicate_login_identity")
            seen_login_identities[identity] = account_id

        firebase_uid = record.get("firebase_uid", "")
        firebase_lookup_id = firebase_uid.strip()
        if (
            firebase_lookup_id
            and firebase_lookup_id in seen_firebase_lookup_ids
        ):
            raise _AccountShapeError("duplicate_firebase_uid")
        if firebase_lookup_id:
            seen_firebase_lookup_ids.add(firebase_lookup_id)

        phone_candidates = user_account_service.phone_lookup_candidates(
            record.get("phone", "")
        )
        if seen_phone_candidates.intersection(phone_candidates):
            raise _AccountShapeError("duplicate_phone_identity")
        seen_phone_candidates.update(phone_candidates)

        profile, auth_metadata, secrets = _split_account_record(record)
        record_json = canonical_json(record)
        prepared.append(_PreparedAccount(
            account_id=account_id,
            workspace_id=account_id,
            record_sha256=hashlib.sha256(record_json.encode("utf-8")).hexdigest(),
            username=record.get("username", ""),
            normalized_email=normalized_email,
            status=record.get("account_status", "active"),
            password_hash=record.get("password_hash", ""),
            firebase_uid=firebase_uid,
            provider=record.get("auth_provider", "local"),
            created_at=record.get("created_at", ""),
            updated_at=record.get("updated_at", ""),
            profile_json=canonical_json(profile),
            auth_metadata_json=canonical_json(auth_metadata),
            secret_payload=secrets,
        ))
    return tuple(prepared)


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
    if isinstance(exc, _AccountShapeError):
        code = str(exc)
        if code.replace("_", "").isalnum():
            return code
        return "invalid_account_source"
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_json_value"
    return "invalid_account_source"


def _preview_from_prepared(
    raw: bytes,
    prepared: Tuple[_PreparedAccount, ...],
    *,
    clock: Optional[Callable[[], datetime]],
) -> AccountMigrationPreview:
    secret_counts: Dict[str, int] = {}
    hash_counts: Dict[str, int] = {}
    requiring_encryption = 0
    profile_fields = 0
    auth_fields = 0
    source_value = _strict_json_loads(raw)
    source_records = source_value["users"]

    for record, item in zip(source_records, prepared):
        if item.secret_payload:
            requiring_encryption += 1
        for field in SECRET_TOP_LEVEL_FIELDS:
            if field in item.secret_payload:
                secret_counts[field] = secret_counts.get(field, 0) + 1
        if isinstance(item.secret_payload.get("two_factor"), dict):
            secret_counts["two_factor.secret"] = (
                secret_counts.get("two_factor.secret", 0) + 1
            )
        if isinstance(item.secret_payload.get("two_factor_setup"), dict):
            secret_counts["two_factor_setup.secret"] = (
                secret_counts.get("two_factor_setup.secret", 0) + 1
            )
        for name, count in _hash_count(record).items():
            hash_counts[name] = hash_counts.get(name, 0) + count
        profile_fields += len(json.loads(item.profile_json))
        auth_fields += len(json.loads(item.auth_metadata_json))

    return AccountMigrationPreview(
        created_at=_timestamp(clock),
        status="ready",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        account_count=len(prepared),
        profile_field_count=profile_fields,
        auth_metadata_field_count=auth_fields,
        accounts_requiring_encryption=requiring_encryption,
        secret_field_counts=dict(sorted(secret_counts.items())),
        preserved_hash_counts=dict(sorted(hash_counts.items())),
    )


def _scan_source(
    source_path: Path,
    *,
    clock: Optional[Callable[[], datetime]] = None,
) -> Tuple[AccountMigrationPreview, Tuple[_PreparedAccount, ...]]:
    raw, value = _read_source(source_path)
    prepared = _prepare_accounts(value)
    return _preview_from_prepared(raw, prepared, clock=clock), prepared


def preview_account_data_migration(
    source_path=None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
) -> AccountMigrationPreview:
    """Strictly inventory ``users.json`` without opening or creating SQLite."""
    try:
        preview, _prepared = _scan_source(
            account_users_file_path(source_path),
            clock=clock,
        )
        return preview
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return AccountMigrationPreview(
            created_at=_timestamp(clock),
            status="invalid",
            source_sha256=None,
            byte_count=0,
            account_count=0,
            profile_field_count=0,
            auth_metadata_field_count=0,
            accounts_requiring_encryption=0,
            secret_field_counts={},
            preserved_hash_counts={},
            error_code=_safe_error_code(exc),
        )


def _preview_signature(preview: AccountMigrationPreview) -> Tuple[object, ...]:
    return (
        preview.status,
        preview.source_sha256,
        preview.byte_count,
        preview.account_count,
        preview.profile_field_count,
        preview.auth_metadata_field_count,
        preview.accounts_requiring_encryption,
        tuple(sorted(preview.secret_field_counts.items())),
        tuple(sorted(preview.preserved_hash_counts.items())),
        preview.error_code,
    )


def _assert_preview_current(
    expected: AccountMigrationPreview,
    current: AccountMigrationPreview,
) -> None:
    if _preview_signature(expected) != _preview_signature(current):
        raise StaleAccountMigrationPreviewError(
            "The legacy account source changed after preview."
        )


def _scan_unchanged_source(
    expected: AccountMigrationPreview,
    source_path: Path,
    *,
    clock: Optional[Callable[[], datetime]],
) -> Tuple[_PreparedAccount, ...]:
    try:
        current, prepared = _scan_source(source_path, clock=clock)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise StaleAccountMigrationPreviewError(
            "The legacy account source changed after preview."
        ) from exc
    _assert_preview_current(expected, current)
    return prepared


def _configured_encryptor(
    prepared: Tuple[_PreparedAccount, ...],
    encryptor: Optional[SecretEncryptor],
) -> Optional[SecretEncryptor]:
    if not any(account.secret_payload for account in prepared):
        return encryptor
    if encryptor is not None:
        if not isinstance(getattr(encryptor, "key_id", None), str) or not encryptor.key_id:
            raise AccountMigrationEncryptionError(
                "Account secret encryption requires a non-empty key identifier."
            )
        return encryptor
    try:
        return AesGcmDataEncryptor.from_environment()
    except DataEncryptionError as exc:
        raise AccountMigrationEncryptionError(
            "Recoverable account secrets require configured AES-GCM encryption."
        ) from exc


def _encryption_envelope(
    account: _PreparedAccount,
    encryptor: Optional[SecretEncryptor],
) -> Tuple[Mapping[str, object], str]:
    if not account.secret_payload:
        return {}, ""
    if encryptor is None:
        raise AccountMigrationEncryptionError(
            "Recoverable account secrets require configured AES-GCM encryption."
        )
    try:
        envelope_json = encryptor.encrypt_json(
            account.secret_payload,
            associated_data=account_secret_associated_data(account.account_id),
        )
        envelope = EncryptedEnvelope.from_json(envelope_json)
    except (DataEncryptionError, TypeError, ValueError) as exc:
        raise AccountMigrationEncryptionError(
            "Account secret encryption returned an invalid envelope."
        ) from exc
    if envelope.key_id != encryptor.key_id:
        raise AccountMigrationEncryptionError(
            "The account secret envelope key identifier did not match the encryptor."
        )
    return json.loads(envelope.to_json()), envelope.key_id


def _json_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = _strict_json_loads(value.encode("utf-8"))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise AccountMigrationCollisionError(
                "An existing account contains invalid %s." % field_name
            ) from exc
        if isinstance(parsed, dict):
            return parsed
    raise AccountMigrationCollisionError(
        "An existing account contains invalid %s." % field_name
    )


def _existing_json(existing: Mapping[str, object], parsed_name: str, raw_name: str):
    if parsed_name in existing:
        return _json_mapping(existing.get(parsed_name), parsed_name)
    return _json_mapping(existing.get(raw_name), parsed_name)


def _existing_account_matches(
    existing: Mapping[str, object],
    account: _PreparedAccount,
    encryptor: Optional[SecretEncryptor],
) -> bool:
    expected_scalars = {
        "id": account.account_id,
        "workspace_id": account.workspace_id,
        "username": account.username,
        "normalized_email": account.normalized_email,
        "status": account.status,
        "password_hash": account.password_hash,
        "firebase_uid": account.firebase_uid,
        "provider": account.provider,
        "source_sha256": account.record_sha256,
    }
    if account.created_at:
        expected_scalars["created_at"] = account.created_at
    if account.updated_at:
        expected_scalars["updated_at"] = account.updated_at
    if any(existing.get(field) != value for field, value in expected_scalars.items()):
        return False
    if _existing_json(existing, "profile", "profile_json") != json.loads(
        account.profile_json
    ):
        return False
    if _existing_json(
        existing,
        "auth_metadata",
        "auth_metadata_json",
    ) != json.loads(account.auth_metadata_json):
        return False

    existing_envelope = _existing_json(
        existing,
        "encrypted_secrets",
        "encrypted_secrets_json",
    )
    existing_key_id = str(existing.get("encryption_key_id") or "")
    if not account.secret_payload:
        return not existing_envelope and not existing_key_id
    if not existing_envelope or not existing_key_id:
        return False
    try:
        parsed_envelope = EncryptedEnvelope.from_json(
            canonical_json(existing_envelope)
        )
    except DataEncryptionError:
        return False
    if parsed_envelope.key_id != existing_key_id:
        return False

    # An idempotent result is still a validation result: the configured key
    # must authenticate the stored ciphertext for this exact account binding.
    # Key rotation is a separate explicit workflow, never an implicit no-op.
    if encryptor is None or existing_key_id != encryptor.key_id:
        return False
    try:
        decrypted = encryptor.decrypt_json(
            parsed_envelope.to_json(),
            associated_data=account_secret_associated_data(account.account_id),
        )
    except (DataEncryptionError, TypeError, ValueError):
        return False
    return decrypted == account.secret_payload


def _action_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        action = value.get("action")
        if isinstance(action, str):
            return action
    return "applied"


def _is_foundation_collision(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return "collision" in type(exc).__name__.lower()


def _run_failure_injector(failure_injector, stage: str, **context) -> None:
    if callable(failure_injector):
        failure_injector(stage, dict(context))


def _coverage_is_current(
    connection,
    account: _PreparedAccount,
) -> bool:
    coverage = application_data.get_source_coverage(
        account.workspace_id,
        MIGRATION_DOMAIN,
        SOURCE_KIND,
        connection=connection,
    )
    return bool(
        isinstance(coverage, Mapping)
        and coverage.get("source_sha256") == account.record_sha256
        and coverage.get("status") == "covered"
    )


def _install_schema(db_path: Path) -> None:
    result = application_data.install_application_schema(
        db_path=db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    if isinstance(result, Mapping) and result.get("ok") is False:
        raise AccountDataMigrationError(
            "The application-data schema could not be installed."
        )


def apply_account_data_migration(
    preview: AccountMigrationPreview,
    *,
    approval: str,
    source_path=None,
    db_path=None,
    encryptor: Optional[SecretEncryptor] = None,
    clock: Optional[Callable[[], datetime]] = None,
    failure_injector=None,
) -> AccountMigrationApplyResult:
    """Apply an unchanged preview atomically without modifying ``users.json``."""
    if approval != APPLY_APPROVAL_PHRASE:
        raise AccountMigrationApprovalError(
            "The exact account-data migration approval phrase is required."
        )
    if not isinstance(preview, AccountMigrationPreview) or not preview.ready:
        raise AccountMigrationSourceError(
            "A ready account-data migration preview is required."
        )

    resolved_source = account_users_file_path(source_path)
    prepared = _scan_unchanged_source(
        preview,
        resolved_source,
        clock=clock,
    )
    configured_encryptor = _configured_encryptor(prepared, encryptor)
    resolved_db_path = account_migration_db_path(db_path)

    # Schema installation is an explicit additive step and happens only after
    # approval, strict parsing, hash comparison, and encryption preflight.
    _install_schema(resolved_db_path)

    applied_at = _timestamp(clock)
    migration_run_id: Optional[str] = None
    account_actions = {"inserted": 0, "unchanged": 0}
    workspace_actions = {"inserted": 0, "updated": 0, "unchanged": 0}
    coverage_updates = []
    validated_accounts = 0
    validated_coverage = 0

    with application_data.application_data_write_connection(
        db_path=resolved_db_path
    ) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _run_failure_injector(failure_injector, "after_begin")

            # Recheck after DDL and after the write lock is acquired. Records
            # used below come from this final, hash-matched read.
            prepared = _scan_unchanged_source(
                preview,
                resolved_source,
                clock=clock,
            )

            for index, account in enumerate(prepared):
                try:
                    workspace_result = application_data.ensure_workspace(
                        account.workspace_id,
                        WORKSPACE_TYPE,
                        account.account_id,
                        lifecycle_state="active",
                        connection=connection,
                    )
                except BaseException as exc:
                    if _is_foundation_collision(exc):
                        raise AccountMigrationCollisionError(
                            "An account workspace collides with existing application data."
                        ) from exc
                    raise
                workspace_action = _action_name(workspace_result)
                workspace_actions[workspace_action] = (
                    workspace_actions.get(workspace_action, 0) + 1
                )

                existing = application_data.get_account(
                    account.account_id,
                    connection=connection,
                )
                if existing is not None:
                    if not _existing_account_matches(
                        existing,
                        account,
                        configured_encryptor,
                    ):
                        raise AccountMigrationCollisionError(
                            "An existing account differs from the legacy source."
                        )
                    account_actions["unchanged"] += 1
                else:
                    encrypted_secrets, encryption_key_id = _encryption_envelope(
                        account,
                        configured_encryptor,
                    )
                    try:
                        result = application_data.upsert_account(
                            account.account_id,
                            account.workspace_id,
                            username=account.username,
                            normalized_email=account.normalized_email,
                            status=account.status,
                            password_hash=account.password_hash,
                            firebase_uid=account.firebase_uid,
                            provider=account.provider,
                            created_at=account.created_at,
                            updated_at=account.updated_at,
                            profile=json.loads(account.profile_json),
                            auth_metadata=json.loads(account.auth_metadata_json),
                            encrypted_secrets=encrypted_secrets,
                            encryption_key_id=encryption_key_id,
                            source_sha256=account.record_sha256,
                            connection=connection,
                        )
                    except BaseException as exc:
                        if _is_foundation_collision(exc):
                            raise AccountMigrationCollisionError(
                                "An account identity collides with existing application data."
                            ) from exc
                        raise
                    action = _action_name(result)
                    if action != "inserted":
                        raise AccountMigrationCollisionError(
                            "A new account was not inserted exactly once."
                        )
                    account_actions["inserted"] += 1

                if not _coverage_is_current(connection, account):
                    coverage_updates.append(account)
                _run_failure_injector(
                    failure_injector,
                    "after_account",
                    account_index=index,
                )

            changed = bool(
                account_actions["inserted"]
                or workspace_actions.get("inserted", 0)
                or workspace_actions.get("updated", 0)
                or coverage_updates
            )
            if changed:
                migration_run_id = uuid.uuid4().hex
                run_result = application_data.record_application_migration_run(
                    SOURCE_KIND,
                    "succeeded",
                    run_id=migration_run_id,
                    source_sha256=preview.source_sha256 or "",
                    summary={
                        "account_count": len(prepared),
                        "accounts_requiring_encryption": (
                            preview.accounts_requiring_encryption
                        ),
                        "coverage_updates": len(coverage_updates),
                        "schema_version": SCHEMA_VERSION,
                    },
                    started_at=applied_at,
                    finished_at=applied_at,
                    connection=connection,
                )
                if isinstance(run_result, Mapping) and run_result.get("id"):
                    migration_run_id = str(run_result["id"])

                for account in coverage_updates:
                    application_data.upsert_source_coverage(
                        account.workspace_id,
                        MIGRATION_DOMAIN,
                        SOURCE_KIND,
                        account.record_sha256,
                        migration_run_id=migration_run_id,
                        status="covered",
                        summary={
                            "encrypted": bool(account.secret_payload),
                            "schema_version": SCHEMA_VERSION,
                        },
                        covered_at=applied_at,
                        connection=connection,
                    )

            _run_failure_injector(failure_injector, "before_validation")
            for account in prepared:
                stored = application_data.get_account(
                    account.account_id,
                    connection=connection,
                )
                if not isinstance(stored, Mapping) or not _existing_account_matches(
                    stored,
                    account,
                    configured_encryptor,
                ):
                    raise AccountDataMigrationError(
                        "Account migration validation failed before commit."
                    )
                validated_accounts += 1
                if not _coverage_is_current(connection, account):
                    raise AccountDataMigrationError(
                        "Account source coverage validation failed before commit."
                    )
                validated_coverage += 1

            _run_failure_injector(failure_injector, "before_commit")
            _scan_unchanged_source(
                preview,
                resolved_source,
                clock=clock,
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

    return AccountMigrationApplyResult(
        applied_at=applied_at,
        source_sha256=preview.source_sha256 or "",
        migration_run_id=migration_run_id,
        account_count=len(prepared),
        inserted_accounts=account_actions["inserted"],
        unchanged_accounts=account_actions["unchanged"],
        inserted_workspaces=workspace_actions.get("inserted", 0),
        updated_workspaces=workspace_actions.get("updated", 0),
        unchanged_workspaces=workspace_actions.get("unchanged", 0),
        coverage_rows=validated_coverage,
        no_op=not bool(
            account_actions["inserted"]
            or workspace_actions.get("inserted", 0)
            or workspace_actions.get("updated", 0)
            or coverage_updates
        ),
        validation={
            "accounts": validated_accounts,
            "coverage": validated_coverage,
            "encrypted_accounts": sum(
                1 for account in prepared if account.secret_payload
            ),
            "preserved_hashes": sum(preview.preserved_hash_counts.values()),
        },
    )


__all__ = [
    "APPLY_APPROVAL_PHRASE",
    "AccountDataMigrationError",
    "AccountMigrationApplyResult",
    "AccountMigrationApprovalError",
    "AccountMigrationCollisionError",
    "AccountMigrationEncryptionError",
    "AccountMigrationPreview",
    "AccountMigrationSourceError",
    "StaleAccountMigrationPreviewError",
    "account_migration_db_path",
    "account_secret_associated_data",
    "account_users_file_path",
    "apply_account_data_migration",
    "preview_account_data_migration",
]
