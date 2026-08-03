"""Normalize saved recipe fraction typography to portable slash fractions."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PushShoppingList.services.ingredient_unit_service import normalize_fraction_text


PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = PACKAGE_DIR / "user_data"
BACKUP_FOLDER_NAME = ".fraction-normalization-backups"

PROTECTED_STRING_KEYS = {
    "id",
    "key",
    "path",
    "filename",
    "object_key",
    "source_url",
    "document_source_url",
    "menu_item_url",
    "source_display_url",
    "menu_order_url",
    "deep_link_url",
    "recipe_record_url",
    "ingredient_image_url",
    "instruction_image_url",
    "equipment_image_url",
    "pdf_url",
    "pdf_path",
}


def protected_string_key(key):
    key = str(key or "").strip().lower()
    return bool(
        key in PROTECTED_STRING_KEYS
        or key.endswith(("_id", "_url", "_uri", "_path", "_filename"))
    )


def normalize_json_fraction_values(value, key=""):
    """Return ``(normalized_value, changed_string_count)`` for JSON data."""
    if isinstance(value, dict):
        changed = 0
        for child_key, child_value in list(value.items()):
            normalized, child_changed = normalize_json_fraction_values(
                child_value,
                child_key,
            )
            value[child_key] = normalized
            changed += child_changed
        return value, changed
    if isinstance(value, list):
        changed = 0
        for index, child_value in enumerate(value):
            normalized, child_changed = normalize_json_fraction_values(child_value, key)
            value[index] = normalized
            changed += child_changed
        return value, changed
    if isinstance(value, str) and not protected_string_key(key):
        normalized = normalize_fraction_text(value)
        return normalized, int(normalized != value)
    return value, 0


def write_json_atomically(path, data):
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def migrate_recipe_fraction_text(data_root=DEFAULT_DATA_ROOT, apply_changes=False):
    data_root = Path(data_root).resolve()
    json_paths = [
        path
        for path in data_root.rglob("*.json")
        if BACKUP_FOLDER_NAME not in path.parts
    ]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = data_root / BACKUP_FOLDER_NAME / timestamp
    summary = {
        "ok": True,
        "mode": "apply" if apply_changes else "dry-run",
        "data_root": str(data_root),
        "files_scanned": 0,
        "files_changed": 0,
        "strings_changed": 0,
        "files_failed": 0,
        "changed_files": [],
        "errors": [],
        "backup_root": str(backup_root) if apply_changes else "",
    }

    for path in json_paths:
        summary["files_scanned"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            normalized, changed = normalize_json_fraction_values(data)
            if not changed:
                continue
            relative_path = path.relative_to(data_root)
            summary["files_changed"] += 1
            summary["strings_changed"] += changed
            summary["changed_files"].append(str(relative_path))
            if apply_changes:
                backup_path = backup_root / relative_path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_path)
                write_json_atomically(path, normalized)
        except Exception as exc:
            summary["files_failed"] += 1
            summary["errors"].append({"file": str(path), "error": str(exc)})

    summary["ok"] = summary["files_failed"] == 0
    if apply_changes and not summary["files_changed"]:
        summary["backup_root"] = ""
    return summary


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Convert saved Unicode recipe fractions such as ½ and ¾ "
            "to plain 1/2 and 3/4 text."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes after backing up every affected JSON file.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="User-data directory to scan (defaults to PushShoppingList/user_data).",
    )
    args = parser.parse_args()
    result = migrate_recipe_fraction_text(
        data_root=args.data_root,
        apply_changes=args.apply,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
