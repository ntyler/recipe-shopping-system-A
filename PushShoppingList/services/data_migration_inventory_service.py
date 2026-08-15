"""Build the explicit, read-only source inventory used by staged migration.

The builder maps user directory names back to opaque account UUIDs and prefixes
guest workspaces consistently with the guest-session migration.  Unknown user
directories are reported as blockers rather than guessed.  Unknown guest
directories are safe to classify as inactive guest workspaces because guest
directory names are the session identifiers themselves.

No directory or database is created by this module.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Tuple

from PushShoppingList.services import durable_data_migration_service as migration


PACKAGE_DIR = Path(__file__).resolve().parent.parent
EXTRACTOR_DATA_DIR = PACKAGE_DIR / "services" / "recipe-extractor" / "data"


class DataMigrationInventoryError(RuntimeError):
    """Raised when source identities cannot be mapped without guessing."""


@dataclass(frozen=True)
class InventoryIssue:
    code: str
    count: int
    blocking: bool

    def to_dict(self):
        return {
            "blocking": self.blocking,
            "code": self.code,
            "count": self.count,
        }


@dataclass(frozen=True)
class DefaultMigrationInventory:
    config: migration.DurableMigrationConfig
    issues: Tuple[InventoryIssue, ...]
    user_workspace_count: int
    guest_workspace_count: int
    orphan_guest_workspace_count: int

    @property
    def ready(self) -> bool:
        return not any(issue.blocking for issue in self.issues)

    def to_dict(self):
        return {
            "guest_workspace_count": self.guest_workspace_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "orphan_guest_workspace_count": self.orphan_guest_workspace_count,
            "ready": self.ready,
            "user_workspace_count": self.user_workspace_count,
        }


def _path_from_environment(name: str, default: Path, environment: Mapping[str, str]):
    return Path(environment.get(name, "") or default)


def _safe_directory_id(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "", str(value or ""))[:80]


def _strict_json_file(path: Path, root_key: str):
    if not path.is_file():
        return []
    raw = path.read_bytes()

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DataMigrationInventoryError("A registry contains duplicate JSON keys.")
            result[key] = value
        return result

    try:
        payload = json.loads(
            raw.decode("utf-8-sig", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise DataMigrationInventoryError("A required identity registry is invalid.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get(root_key), list):
        raise DataMigrationInventoryError("A required identity registry has an invalid shape.")
    return payload[root_key]


def _directory_names(root: Path):
    if not root.is_dir():
        return set()
    try:
        return {child.name for child in root.iterdir() if child.is_dir()}
    except OSError as exc:
        raise DataMigrationInventoryError("A workspace root could not be inventoried.") from exc


def _parse_timestamp(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_default_migration_inventory(
    *,
    environment: Optional[Mapping[str, str]] = None,
    clock=None,
) -> DefaultMigrationInventory:
    """Inspect configured legacy roots and return an explicit migration config."""

    environment = environment if environment is not None else os.environ
    users_file = _path_from_environment(
        "SHOPPING_APP_USERS_FILE", PACKAGE_DIR / "users.json", environment
    )
    guests_file = _path_from_environment(
        "SHOPPING_APP_GUEST_SESSIONS_FILE",
        PACKAGE_DIR / "guest_sessions.json",
        environment,
    )
    user_root = _path_from_environment(
        "SHOPPING_APP_USER_DATA_DIR", PACKAGE_DIR / "user_data" / "users", environment
    )
    guest_root = _path_from_environment(
        "SHOPPING_APP_GUEST_DATA_DIR", PACKAGE_DIR / "user_data" / "guests", environment
    )

    issues = []
    try:
        account_records = _strict_json_file(users_file, "users")
    except DataMigrationInventoryError:
        account_records = []
        issues.append(InventoryIssue("invalid_account_registry", 1, True))
    try:
        guest_records = _strict_json_file(guests_file, "guest_sessions")
    except DataMigrationInventoryError:
        guest_records = []
        issues.append(InventoryIssue("invalid_guest_registry", 1, True))

    workspaces = []
    user_directory_owners = {}
    invalid_accounts = 0
    for record in account_records:
        if not isinstance(record, dict):
            invalid_accounts += 1
            continue
        account_id = record.get("user_id")
        if not isinstance(account_id, str) or not account_id or "\x00" in account_id:
            invalid_accounts += 1
            continue
        directory_id = _safe_directory_id(account_id)
        if not directory_id or directory_id in user_directory_owners:
            invalid_accounts += 1
            continue
        user_directory_owners[directory_id] = account_id
        workspaces.append(
            migration.WorkspaceSource(
                workspace_id=account_id,
                workspace_type="user",
                subject_id=account_id,
                root=user_root / directory_id,
                lifecycle_state="active",
            )
        )
    if invalid_accounts:
        issues.append(InventoryIssue("unmappable_account_identity", invalid_accounts, True))

    unmapped_user_directories = _directory_names(user_root).difference(user_directory_owners)
    if unmapped_user_directories:
        issues.append(
            InventoryIssue(
                "unmapped_user_workspace",
                len(unmapped_user_directories),
                True,
            )
        )

    now = clock() if clock is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    guest_ids = set()
    invalid_guests = 0
    for record in guest_records:
        if not isinstance(record, dict):
            invalid_guests += 1
            continue
        guest_id = record.get("id") or record.get("guest_session_id")
        if not isinstance(guest_id, str) or not guest_id or "\x00" in guest_id:
            invalid_guests += 1
            continue
        directory_id = _safe_directory_id(guest_id)
        if not directory_id or guest_id in guest_ids:
            invalid_guests += 1
            continue
        guest_ids.add(guest_id)
        expires_at = _parse_timestamp(record.get("expires_at"))
        is_active = bool(record.get("is_active", True)) and (
            expires_at is None or expires_at > now
        )
        workspaces.append(
            migration.WorkspaceSource(
                workspace_id="guest:%s" % guest_id,
                workspace_type="guest",
                subject_id=guest_id,
                root=guest_root / directory_id,
                lifecycle_state="active" if is_active else "inactive",
            )
        )
    if invalid_guests:
        issues.append(InventoryIssue("unmappable_guest_identity", invalid_guests, True))

    known_guest_directories = {_safe_directory_id(value) for value in guest_ids}
    orphan_guest_directories = sorted(
        _directory_names(guest_root).difference(known_guest_directories)
    )
    for directory_id in orphan_guest_directories:
        if not directory_id or _safe_directory_id(directory_id) != directory_id:
            issues.append(InventoryIssue("unsafe_orphan_guest_workspace", 1, True))
            continue
        workspaces.append(
            migration.WorkspaceSource(
                workspace_id="guest:%s" % directory_id,
                workspace_type="guest",
                subject_id=directory_id,
                root=guest_root / directory_id,
                lifecycle_state="inactive",
            )
        )

    feedback_uploads = _path_from_environment(
        "SHOPPING_APP_FEEDBACK_UPLOAD_DIR",
        PACKAGE_DIR / "static" / "uploads" / "feedback",
        environment,
    )
    avatar_uploads = _path_from_environment(
        "SHOPPING_APP_AVATAR_UPLOAD_DIR",
        PACKAGE_DIR / "static" / "uploads" / "avatars",
        environment,
    )
    global_sources = {
        "accounts_auth": users_file,
        "guest_sessions": guests_file,
        "feedback": _path_from_environment(
            "SHOPPING_APP_FEEDBACK_FILE", PACKAGE_DIR / "feedback.json", environment
        ),
        "admin_audit": _path_from_environment(
            "SHOPPING_APP_ADMIN_SUPPORT_AUDIT_FILE",
            PACKAGE_DIR / "admin_support_audit.json",
            environment,
        ),
        "pdf_share_tokens": EXTRACTOR_DATA_DIR / "pdf_share_links.json",
        "feedback_attachments": feedback_uploads,
        "avatar_uploads": avatar_uploads,
        "shared_pdf_files": EXTRACTOR_DATA_DIR / "pdf",
    }
    config = migration.DurableMigrationConfig(
        global_sources=global_sources,
        workspaces=tuple(workspaces),
        global_workspace=migration.WorkspaceSource(
            workspace_id="global:application",
            workspace_type="system",
            subject_id="application",
            root=PACKAGE_DIR,
            lifecycle_state="active",
        ),
    )
    return DefaultMigrationInventory(
        config=config,
        issues=tuple(issues),
        user_workspace_count=len(user_directory_owners),
        guest_workspace_count=len(guest_ids),
        orphan_guest_workspace_count=len(orphan_guest_directories),
    )


__all__ = [
    "DataMigrationInventoryError",
    "DefaultMigrationInventory",
    "InventoryIssue",
    "build_default_migration_inventory",
]
