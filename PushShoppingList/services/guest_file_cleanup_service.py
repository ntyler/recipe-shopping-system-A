"""Exact, retryable filesystem cleanup for one guest workspace."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from PushShoppingList.services import storage_service


class GuestWorkspacePathError(ValueError):
    """Raised when a guest id cannot safely identify one workspace root."""


def guest_workspace_base(base_dir=None):
    return Path(base_dir if base_dir is not None else storage_service.GUEST_DATA_DIR)


def validated_guest_workspace_path(guest_session_id, *, base_dir=None):
    raw_id = str(guest_session_id or "")
    if not raw_id or raw_id != raw_id.strip():
        raise GuestWorkspacePathError("Guest session id must be non-empty and exact.")
    if storage_service.safe_user_id(raw_id) != raw_id:
        raise GuestWorkspacePathError(
            "Guest session id is not an exact filesystem-safe workspace name."
        )

    base = guest_workspace_base(base_dir).resolve()
    candidate = guest_workspace_base(base_dir) / raw_id
    resolved = candidate.resolve()
    if resolved == base or base not in resolved.parents:
        raise GuestWorkspacePathError("Guest workspace resolves outside its configured root.")
    return candidate, resolved, base


def _is_reparse_point(path):
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _workspace_inventory(root):
    if not root.exists():
        return {"file_count": 0, "directory_count": 0, "size_bytes": 0}
    if root.is_symlink() or _is_reparse_point(root):
        raise GuestWorkspacePathError("Guest workspace root cannot be a link or reparse point.")

    file_count = 0
    directory_count = 0
    size_bytes = 0
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current_root)
        for name in list(directory_names):
            path = current_path / name
            if path.is_symlink() or _is_reparse_point(path):
                raise GuestWorkspacePathError(
                    "Guest workspace contains a link or reparse point; refusing recursive deletion."
                )
            directory_count += 1
        for name in file_names:
            path = current_path / name
            if path.is_symlink() or _is_reparse_point(path):
                raise GuestWorkspacePathError(
                    "Guest workspace contains a linked file; refusing recursive deletion."
                )
            file_count += 1
            try:
                size_bytes += path.stat().st_size
            except OSError as exc:
                raise GuestWorkspacePathError(
                    "Guest workspace could not be inventoried safely."
                ) from exc
    return {
        "file_count": file_count,
        "directory_count": directory_count,
        "size_bytes": size_bytes,
    }


def preview_guest_workspace_cleanup(guest_session_id, *, base_dir=None):
    try:
        candidate, resolved, base = validated_guest_workspace_path(
            guest_session_id,
            base_dir=base_dir,
        )
        inventory = _workspace_inventory(candidate)
    except (GuestWorkspacePathError, OSError) as exc:
        return {
            "ok": False,
            "dry_run": True,
            "code": "unsafe_workspace",
            "error": str(exc),
        }
    return {
        "ok": True,
        "dry_run": True,
        "code": "preview_complete",
        "exists": candidate.exists(),
        "workspace_name": candidate.name,
        "workspace_relative_path": resolved.relative_to(base).as_posix(),
        **inventory,
    }


def delete_guest_workspace(
    guest_session_id,
    *,
    base_dir=None,
    failure_injector=None,
):
    """Delete one exact workspace; missing targets are idempotent success."""
    preview = preview_guest_workspace_cleanup(guest_session_id, base_dir=base_dir)
    if not preview.get("ok"):
        return {**preview, "dry_run": False, "applied": False}

    candidate, _resolved, _base = validated_guest_workspace_path(
        guest_session_id,
        base_dir=base_dir,
    )
    if not candidate.exists():
        return {
            **preview,
            "dry_run": False,
            "applied": True,
            "no_op": True,
            "code": "delete_complete",
        }

    try:
        if callable(failure_injector):
            failure_injector("before_delete", {"workspace_name": candidate.name})
        shutil.rmtree(candidate)
        if candidate.exists():
            raise OSError("Guest workspace still exists after recursive deletion.")
        if callable(failure_injector):
            failure_injector("after_delete", {"workspace_name": candidate.name})
    except Exception as exc:
        return {
            **preview,
            "dry_run": False,
            "applied": False,
            "code": "delete_failed",
            "error": str(exc),
        }
    return {
        **preview,
        "dry_run": False,
        "applied": True,
        "no_op": False,
        "exists": False,
        "code": "delete_complete",
    }


__all__ = [
    "GuestWorkspacePathError",
    "delete_guest_workspace",
    "guest_workspace_base",
    "preview_guest_workspace_cleanup",
    "validated_guest_workspace_path",
]
