"""Audit and safely repair generated-recipe PDFs stored in Cloudflare R2.

The command is deliberately read-only by default.  A production repair requires
both ``--apply`` and ``--confirm-r2-overwrite``; repaired objects are uploaded to
their existing deterministic keys and are never deleted first.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPOSITORY_ROOT / "PushShoppingList" / "user_data" / "users"
DEFAULT_LEGACY_OUTPUT = (
    REPOSITORY_ROOT
    / "PushShoppingList"
    / "services"
    / "recipe-extractor"
    / "data"
    / "output"
)
DEFAULT_REPORT_PATH = (
    REPOSITORY_ROOT / "output" / "pdf" / "generated-recipe-pdf-repair-report.json"
)
DEFAULT_STATE_PATH = (
    REPOSITORY_ROOT / "output" / "pdf" / "generated-recipe-pdf-repair-state.jsonl"
)
GENERATED_RECIPE_SUFFIX = "_generated_recipe.pdf"
_AUTO_LEGACY_OUTPUT = object()


def utc_iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_repository_dotenv():
    """Load the repository .env for direct CLI use without overriding shell values."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    except Exception:
        # Launch scripts may already export the environment, and python-dotenv is
        # intentionally not required for importing or testing this module.
        pass


def legacy_safe_filename(value):
    text = re.sub(r"https?://", "", str(value or ""))
    text = re.sub(r"www\.", "", text)
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_")[:120] or "recipe"


@dataclass(frozen=True)
class RecipeRecord:
    workspace_id: str
    output_path: Path
    source_url: str
    data: dict

    @property
    def output_folder(self):
        return self.output_path.parent

    @property
    def data_folder(self):
        return self.output_folder.parent


def _read_json_object(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _workspace_output_folders(data_root, legacy_output=DEFAULT_LEGACY_OUTPUT):
    data_root = normalized_users_data_root(data_root)
    folders = []
    if data_root.exists():
        folders.extend(
            path
            for path in data_root.glob("*/recipe-extractor/data/output")
            if path.is_dir()
        )
    legacy_output = Path(legacy_output) if legacy_output else None
    if legacy_output and legacy_output.is_dir() and legacy_output not in folders:
        folders.append(legacy_output)
    return data_root, folders


def normalized_users_data_root(data_root):
    data_root = Path(data_root)
    return data_root / "users" if data_root.name.lower() == "user_data" else data_root


def scan_recipe_records(data_root=DEFAULT_DATA_ROOT, legacy_output=DEFAULT_LEGACY_OUTPUT):
    data_root, output_folders = _workspace_output_folders(data_root, legacy_output)
    records = []
    failures = []
    for output_folder in output_folders:
        try:
            relative = output_folder.relative_to(data_root)
            workspace_id = relative.parts[0]
        except ValueError:
            workspace_id = "__legacy__"

        for path in output_folder.glob("*.json"):
            if path.name == "sorted_ingredients.json":
                continue
            data = _read_json_object(path)
            if data is None:
                failures.append({"file": str(path), "error": "invalid_json"})
                continue
            object_keys = persisted_generated_object_keys(data)
            if len(object_keys) > 1:
                failures.append({
                    "file": str(path),
                    "error": "conflicting_generated_pdf_object_keys",
                    "object_keys": object_keys,
                })
                continue
            source_url = str(data.get("source_url") or "").strip()
            if source_url:
                records.append(RecipeRecord(workspace_id, path, source_url, data))
            elif object_keys:
                failures.append({
                    "file": str(path),
                    "error": "missing_source_url_with_generated_pdf_key",
                })
    return records, failures


def _nested_dict(value, key):
    value = value if isinstance(value, dict) else {}
    child = value.get(key)
    return child if isinstance(child, dict) else {}


def persisted_generated_object_keys(data):
    data = data if isinstance(data, dict) else {}
    pdf = _nested_dict(data, "pdf")
    generated = _nested_dict(pdf, "generated_recipe")
    r2 = _nested_dict(generated, "cloudflare_r2")
    keys = []
    for value in (
        data.get("generated_recipe_pdf_object_key"),
        generated.get("r2_object_key"),
        r2.get("object_key"),
    ):
        value = str(value or "").strip().replace("\\", "/")
        if value and value not in keys:
            keys.append(value)
    # Repair authority comes only from a key persisted with the saved record.
    # Reconstructing a key from a URL is unsafe: truncation and punctuation
    # normalization can map distinct recipe identities to the same object.
    return keys


def generated_object_keys_for_record(record):
    return persisted_generated_object_keys(record.data)


def recipe_title(record):
    data = record.data
    return str(
        data.get("recipe_title")
        or data.get("display_name")
        or data.get("item_name")
        or data.get("menu_item_name")
        or ""
    ).strip()


def record_has_recipe_content(record):
    data = record.data
    ingredients = data.get("ingredients") if isinstance(data.get("ingredients"), list) else []
    instructions = data.get("instructions") if isinstance(data.get("instructions"), list) else []
    return bool(recipe_title(record) and (ingredients or instructions))


def _first_query_value(query, key):
    values = query.get(key.lower()) or []
    return str(values[0] if values else "").strip().casefold()


def recipe_menu_item_identity(record):
    """Return a conservative identity for superseded menu-item recipe URLs."""
    parsed = urlparse(record.source_url)
    query = {
        str(key).lower(): value
        for key, value in parse_qs(parsed.query, keep_blank_values=True).items()
    }
    # The URL token is the durable restaurant-menu identity. Saved
    # ``menu_item_id`` values may be newer internal UUIDs and must not hide it.
    match = re.search(r"menu-item-(\d+)", record.source_url, flags=re.IGNORECASE)
    item_value = match.group(1) if match else str(record.data.get("menu_item_id") or "").strip()
    item_match = re.search(r"(?:menu-item-)?(\d+)", item_value, flags=re.IGNORECASE)
    item_id = item_match.group(1) if item_match else ""
    if not item_id:
        return None

    scope = (
        _first_query_value(query, "resinput")
        or str(record.data.get("menu_id") or "").strip().casefold()
        or str(record.data.get("restaurant_id") or "").strip().casefold()
    )
    if not scope:
        source_menu_url = str(record.data.get("source_menu_url") or "").strip()
        scope = source_menu_url.casefold() if source_menu_url else parsed.path.casefold()
    return (
        record.workspace_id,
        (parsed.hostname or "").casefold(),
        scope,
        item_id,
    )


def build_record_indexes(records):
    by_object_key = {}
    by_menu_item = {}
    for record in records:
        for object_key in generated_object_keys_for_record(record):
            by_object_key.setdefault(object_key, []).append(record)
        identity = recipe_menu_item_identity(record)
        if identity:
            by_menu_item.setdefault(identity, []).append(record)
    return by_object_key, by_menu_item


def choose_repair_source(target_records, by_menu_item):
    if len(target_records) > 1:
        return None, "multiple_saved_records_share_the_object_key"
    direct = [record for record in target_records if record_has_recipe_content(record)]
    if len(direct) == 1:
        return direct[0], "direct_saved_record"

    candidates = []
    for target in target_records:
        identity = recipe_menu_item_identity(target)
        for candidate in by_menu_item.get(identity, []) if identity else []:
            if record_has_recipe_content(candidate) and candidate not in candidates:
                candidates.append(candidate)
    if len(candidates) == 1:
        return candidates[0], "superseded_menu_item_record"
    if len(candidates) > 1:
        return None, "multiple_recipe_records_match_the_menu_item"
    if not target_records:
        return None, "no_saved_recipe_record"
    return None, "saved_record_has_no_regeneratable_recipe_content"


def inspect_pdf_bytes(pdf_bytes):
    """Extract enough evidence to identify Chrome/net-error PDFs."""
    from PyPDF2 import PdfReader

    from PushShoppingList.services.recipe_extract_service import browser_error_page_details

    result = {
        "ok": False,
        "browser_error": False,
        "browser_error_code": "",
        "browser_error_marker": "",
        "page_count": 0,
        "text_length": 0,
        "error": "",
    }
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        result["page_count"] = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        result["text_length"] = len(text)
        details = browser_error_page_details(page_source=text)
        result["browser_error"] = bool(details.get("is_error"))
        result["browser_error_code"] = str(details.get("error_code") or "")
        result["browser_error_marker"] = str(details.get("marker") or "")
        result["ok"] = result["page_count"] > 0
        if not result["ok"]:
            result["error"] = "PDF does not contain any pages."
    except Exception as exc:
        result["error"] = f"PDF could not be parsed: {exc}"
    return result


def validate_pdf_bytes_for_recipe_record(pdf_bytes, source_record):
    """Semantically bind a remote PDF to the saved recipe used to regenerate it."""
    from PushShoppingList.services.recipe_extract_service import validate_generated_recipe_pdf

    with tempfile.TemporaryDirectory(prefix="recipe-pdf-audit-") as temp_folder:
        pdf_path = Path(temp_folder) / "remote-generated-recipe.pdf"
        pdf_path.write_bytes(pdf_bytes)
        return validate_generated_recipe_pdf(
            pdf_path,
            expected_recipe=source_record.data,
            expected_title=recipe_title(source_record),
            require_recipe_evidence=True,
        )


def _write_json_atomically(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def repair_state_matches_scope(event, scope):
    event = event if isinstance(event, dict) else {}
    scope = scope if isinstance(scope, dict) else {}
    return bool(scope) and all(
        str(event.get(key) or "") == str(value or "")
        for key, value in scope.items()
    )


def load_repair_state(path, scope=None):
    completed = {}
    path = Path(path)
    if not path.is_file():
        return completed
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if (
            event.get("status") == "success"
            and event.get("object_key")
            and repair_state_matches_scope(event, scope)
        ):
            completed[str(event["object_key"])] = event
    return completed


def append_repair_state(path, event):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as state_file:
            state_file.write(json.dumps(event, ensure_ascii=False) + "\n")
            state_file.flush()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"Unable to append repair state: {exc}"}


@contextmanager
def selected_workspace(data_root, workspace_id, *, output_folder=None):
    if workspace_id == "__legacy__":
        if output_folder is None:
            yield
            return

        from PushShoppingList.services import recipe_edit_service
        from PushShoppingList.services import recipe_extract_service

        previous_edit_output = recipe_edit_service.OUTPUT_FOLDER
        previous_extract_output = recipe_extract_service.OUTPUT_FOLDER
        previous_pdf_folder = recipe_extract_service.PDF_FOLDER
        output_folder = Path(output_folder)
        recipe_edit_service.OUTPUT_FOLDER = output_folder
        recipe_extract_service.OUTPUT_FOLDER = output_folder
        recipe_extract_service.PDF_FOLDER = output_folder.parent / "pdf"
        try:
            yield
        finally:
            recipe_edit_service.OUTPUT_FOLDER = previous_edit_output
            recipe_extract_service.OUTPUT_FOLDER = previous_extract_output
            recipe_extract_service.PDF_FOLDER = previous_pdf_folder
        return

    from flask import Flask, g

    from PushShoppingList.services import storage_service

    previous_root = storage_service.USER_DATA_DIR
    storage_service.USER_DATA_DIR = Path(data_root)
    app = Flask("generated-recipe-pdf-repair")
    app.config["SECRET_KEY"] = "local-repair-command-context-only"
    try:
        with app.test_request_context("/generated-recipe-pdf-repair"):
            g.session_identity_validated = True
            g.authenticated_user_id = workspace_id
            g.authenticated_guest_session_id = ""
            yield
    finally:
        storage_service.USER_DATA_DIR = previous_root


def _stable_local_repair_path(target_record):
    from PushShoppingList.services.recipe_extract_service import safe_unique_filename

    filename = (
        f"{safe_unique_filename(target_record.source_url, max_length=72, hash_length=16)}"
        f"{GENERATED_RECIPE_SUFFIX}"
    )
    return target_record.data_folder / "pdf" / filename


def _replace_validated_local_pdf(source_path, target_path):
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source_path, temporary)
        os.replace(temporary, target_path)
    finally:
        temporary.unlink(missing_ok=True)


def regenerate_and_replace_object(
    object_key,
    target_record,
    source_record,
    *,
    data_root=DEFAULT_DATA_ROOT,
    expected_etag="",
):
    """Regenerate locally, validate, overwrite the same key, and verify metadata."""
    from PushShoppingList.services import cloudflare_r2_storage
    from PushShoppingList.services import recipe_edit_service
    from PushShoppingList.services.recipe_extract_service import build_video_text_pdf_html
    from PushShoppingList.services.recipe_extract_service import validate_generated_recipe_pdf
    from PushShoppingList.services.recipe_extract_service import write_recipe_page_pdf

    data_root = normalized_users_data_root(data_root)

    if source_record.workspace_id != target_record.workspace_id:
        return {"ok": False, "error": "Repair source belongs to a different user workspace."}

    title = recipe_title(source_record)
    with selected_workspace(
        data_root,
        source_record.workspace_id,
        output_folder=target_record.output_folder,
    ):
        recipe_data = recipe_edit_service.recipe_with_menu_metadata(dict(source_record.data))
        html_text = build_video_text_pdf_html(
            source_record.source_url,
            "",
            title,
            recipe_data=recipe_data,
        )
        with tempfile.TemporaryDirectory(prefix="recipe-pdf-repair-") as temporary_folder:
            staged_pdf = Path(temporary_folder) / "validated-recipe.pdf"
            write_recipe_page_pdf(
                source_record.source_url,
                html_text,
                None,
                staged_pdf,
                expected_recipe=recipe_data,
                expected_title=title,
            )
            validation = validate_generated_recipe_pdf(
                staged_pdf,
                expected_recipe=recipe_data,
                expected_title=title,
                require_recipe_evidence=True,
            )
            if not validation.get("ok"):
                return {
                    "ok": False,
                    "error": validation.get("error") or "Regenerated PDF failed validation.",
                    "validation": validation,
                }

            local_path = _stable_local_repair_path(target_record)
            _replace_validated_local_pdf(staged_pdf, local_path)
            upload_result = cloudflare_r2_storage.upload_pdf(
                local_path,
                object_key=object_key,
                overwrite=True,
                expected_etag=expected_etag,
                validated=True,
                validation=validation,
            )
            upload_result["validation"] = validation
            if not upload_result.get("ok") or not upload_result.get("verified"):
                return {
                    "ok": False,
                    "remote_repaired": bool(upload_result.get("remote_repaired")),
                    "remote_mutation_unknown": bool(
                        upload_result.get("remote_mutation_unknown")
                    ),
                    "etag": upload_result.get("etag", ""),
                    "sha256": upload_result.get("sha256", validation.get("sha256", "")),
                    "size_bytes": upload_result.get(
                        "size_bytes",
                        validation.get("size_bytes", 0),
                    ),
                    "error": upload_result.get("error") or "R2 replacement verification failed.",
                    "validation": validation,
                    "cloudflare_upload": upload_result,
                    "local_path": str(local_path),
                }

        metadata_result = recipe_edit_service.save_recipe_pdf_storage_metadata(
            target_record.source_url,
            upload_result,
            local_path,
            recipe_edit_service.PDF_KIND_GENERATED_RECIPE,
            recipe_output_path=target_record.output_path,
        )
        if not metadata_result.get("ok"):
            return {
                "ok": False,
                "remote_repaired": True,
                "etag": upload_result.get("etag", ""),
                "sha256": upload_result.get("sha256", ""),
                "size_bytes": upload_result.get("size_bytes", 0),
                "error": (
                    "R2 was repaired and verified, but saved metadata could not be updated: "
                    f"{metadata_result.get('error') or 'unknown metadata error'}"
                ),
                "cloudflare_upload": upload_result,
                "validation": validation,
                "local_path": str(local_path),
            }

    return {
        "ok": True,
        "object_key": object_key,
        "public_url": upload_result.get("public_url", ""),
        "etag": upload_result.get("etag", ""),
        "sha256": upload_result.get("sha256", ""),
        "size_bytes": upload_result.get("size_bytes", 0),
        "local_path": str(local_path),
        "validation": validation,
        "remote_verified": True,
    }


def reconcile_validated_repair_metadata(
    object_key,
    target_record,
    source_record,
    pdf_bytes,
    validation,
    *,
    data_root=DEFAULT_DATA_ROOT,
):
    """Finish metadata/local persistence after an interrupted verified R2 repair."""
    from PushShoppingList.services import cloudflare_r2_storage
    from PushShoppingList.services import recipe_edit_service
    from PushShoppingList.services.recipe_extract_service import PDF_VALIDATION_VERSION

    data_root = normalized_users_data_root(data_root)

    remote = cloudflare_r2_storage.head_pdf_object(object_key)
    expected_sha = str(validation.get("sha256") or "").strip().lower()
    if not (
        remote.get("ok")
        and remote.get("exists")
        and remote.get("semantically_validated")
        and str(remote.get("validation_version") or "").strip() == PDF_VALIDATION_VERSION
        and str(remote.get("sha256") or "").strip().lower() == expected_sha
        and int(remote.get("size_bytes") or 0) == len(pdf_bytes)
    ):
        return {"ok": True, "reconciled": False}

    if source_record.workspace_id != target_record.workspace_id:
        return {"ok": False, "error": "Repair metadata source belongs to another workspace."}

    validation = dict(validation)
    validation["remote_etag"] = str(remote.get("etag") or "").strip()
    validation["remote_size_bytes"] = int(remote.get("size_bytes") or 0)
    with selected_workspace(
        data_root,
        target_record.workspace_id,
        output_folder=target_record.output_folder,
    ):
        current_recipe = recipe_edit_service.load_recipe_output(target_record.source_url) or {}
        current_metadata = recipe_edit_service.normalize_recipe_pdf_storage_metadata(
            current_recipe,
            recipe_edit_service.PDF_KIND_GENERATED_RECIPE,
        )
        if recipe_edit_service.generated_pdf_cache_has_positive_validation(
            current_metadata,
            remote,
        ):
            return {
                "ok": True,
                "reconciled": False,
                "already_reconciled": True,
                "etag": remote.get("etag", ""),
                "sha256": expected_sha,
                "size_bytes": len(pdf_bytes),
            }

        local_path = _stable_local_repair_path(target_record)
        with tempfile.TemporaryDirectory(prefix="recipe-pdf-reconcile-") as temp_folder:
            source_path = Path(temp_folder) / "verified-remote.pdf"
            source_path.write_bytes(pdf_bytes)
            _replace_validated_local_pdf(source_path, local_path)

        metadata_result = recipe_edit_service.save_recipe_pdf_storage_metadata(
            target_record.source_url,
            {
                "ok": True,
                "object_key": object_key,
                "public_url": remote.get("public_url", ""),
                "bucket": remote.get("bucket", ""),
                "uploaded_at": remote.get("uploaded_at", ""),
                "etag": remote.get("etag", ""),
                "sha256": expected_sha,
                "size_bytes": len(pdf_bytes),
                "verified": True,
                "validation": validation,
            },
            local_path,
            recipe_edit_service.PDF_KIND_GENERATED_RECIPE,
            recipe_output_path=target_record.output_path,
        )
        if not metadata_result.get("ok"):
            return {
                "ok": False,
                "error": metadata_result.get("error") or "Unable to reconcile repair metadata.",
            }

    return {
        "ok": True,
        "reconciled": True,
        "etag": remote.get("etag", ""),
        "sha256": expected_sha,
        "size_bytes": len(pdf_bytes),
        "local_path": str(local_path),
    }


def audit_and_repair_generated_recipe_pdfs(
    *,
    data_root=DEFAULT_DATA_ROOT,
    legacy_output=_AUTO_LEGACY_OUTPUT,
    apply=False,
    confirm_r2_overwrite=False,
    report_path=None,
    state_path=DEFAULT_STATE_PATH,
    object_keys=None,
    log=print,
):
    """Audit generated PDFs and optionally repair validated mappings in place."""
    if apply and not confirm_r2_overwrite:
        raise PermissionError(
            "Production repair requires both --apply and --confirm-r2-overwrite."
        )

    from PushShoppingList.services import cloudflare_r2_storage

    data_root = normalized_users_data_root(data_root)
    if legacy_output is _AUTO_LEGACY_OUTPUT:
        legacy_output = (
            DEFAULT_LEGACY_OUTPUT
            if data_root.resolve() == normalized_users_data_root(DEFAULT_DATA_ROOT).resolve()
            else None
        )
    started_at = utc_iso_now()
    records, record_failures = scan_recipe_records(data_root, legacy_output)
    if apply and record_failures:
        failure_details = "; ".join(
            f"{item.get('file', '<unknown>')}: {item.get('error', 'scan_failed')}"
            for item in record_failures
        )
        raise RuntimeError(
            "Production repair was refused because one or more invalid record files could "
            "not be safely mapped. Run the dry audit, repair every record scan failure, and "
            f"retry. Failures: {failure_details}"
        )
    by_object_key, by_menu_item = build_record_indexes(records)
    list_result = cloudflare_r2_storage.list_pdf_objects(
        prefixes=(cloudflare_r2_storage.PDF_OBJECT_PREFIX,)
    )
    if not list_result.get("ok"):
        raise RuntimeError(list_result.get("error") or "Unable to list Cloudflare R2 PDFs.")

    requested_keys = {str(key).strip() for key in object_keys or [] if str(key).strip()}
    available_generated_keys = {
        str(item.get("object_key") or "")
        for item in list_result.get("objects", [])
        if str(item.get("object_key") or "").lower().endswith(GENERATED_RECIPE_SUFFIX)
    }
    missing_requested_keys = sorted(requested_keys - available_generated_keys)
    if apply and missing_requested_keys:
        raise RuntimeError(
            "Production repair was refused because requested R2 object keys were not found: "
            + ", ".join(missing_requested_keys)
        )
    remote_objects = [
        item
        for item in list_result.get("objects", [])
        if str(item.get("object_key") or "").lower().endswith(GENERATED_RECIPE_SUFFIX)
        and (not requested_keys or str(item.get("object_key")) in requested_keys)
    ]
    r2_config = cloudflare_r2_storage.config_values()
    state_scope = {
        "r2_bucket": str(list_result.get("bucket") or r2_config.get("bucket_name") or ""),
        "r2_account_id": str(r2_config.get("account_id") or ""),
        "r2_endpoint": str(r2_config.get("endpoint") or ""),
        "data_root_scope": str(Path(data_root).resolve()),
        "legacy_output_scope": (
            str(Path(legacy_output).resolve()) if legacy_output else "__none__"
        ),
    }
    completed_state = load_repair_state(state_path, state_scope) if apply else {}
    summary = {
        "mode": "apply" if apply else "dry-run",
        "started_at": started_at,
        "completed_at": "",
        "data_root": str(Path(data_root).resolve()),
        **state_scope,
        "generated_objects": len(remote_objects),
        "objects_scanned": 0,
        "corrupted": 0,
        "browser_error_corrupted": 0,
        "semantic_invalid": 0,
        "structural_invalid": 0,
        "repairable": 0,
        "repaired": 0,
        "valid_unchanged": 0,
        "unverified_unchanged": 0,
        "metadata_reconciled": 0,
        "skipped": 0,
        "failed": len(missing_requested_keys),
        "resumed": 0,
        "saved_records": len(records),
        "invalid_record_files": len(record_failures),
        "record_scan_failures": record_failures,
        "production_r2_mutations": 0,
        "production_r2_mutations_possible": 0,
        "state_write_failures": 0,
        "requested_object_keys": sorted(requested_keys),
        "missing_requested_object_keys": missing_requested_keys,
        "items": [
            {
                "object_key": object_key,
                "status": "failed",
                "error": "Requested generated-recipe R2 object was not found.",
            }
            for object_key in missing_requested_keys
        ],
    }

    for index, remote in enumerate(remote_objects, start=1):
        object_key = str(remote.get("object_key") or "")
        remote_etag = str(remote.get("etag") or "").strip()
        state_event = completed_state.get(object_key)
        if apply and state_event and str(state_event.get("etag") or "") == remote_etag:
            summary["resumed"] += 1
            summary["items"].append({
                "object_key": object_key,
                "status": "resumed_verified",
                "etag": remote_etag,
            })
            log(f"[{index}/{len(remote_objects)}] resumed {object_key}")
            continue

        try:
            read_result = cloudflare_r2_storage.read_pdf_object_bytes(
                object_key,
                expected_etag=remote_etag,
            )
        except Exception as exc:
            read_result = {"ok": False, "error": f"R2 PDF read raised unexpectedly: {exc}"}
        summary["objects_scanned"] += 1
        if not read_result.get("ok"):
            summary["failed"] += 1
            item = {
                "object_key": object_key,
                "status": "failed",
                "error": read_result.get("error") or "R2 PDF download failed.",
            }
            summary["items"].append(item)
            log(f"[{index}/{len(remote_objects)}] failed {object_key}: {item['error']}")
            continue

        inspection = inspect_pdf_bytes(read_result.get("bytes") or b"")
        targets = by_object_key.get(object_key, [])
        source_record, mapping = choose_repair_source(targets, by_menu_item)
        semantic_validation = {}
        corruption_type = ""
        if not inspection.get("ok"):
            corruption_type = "structural_invalid"
            summary["structural_invalid"] += 1
        elif inspection.get("browser_error"):
            corruption_type = "browser_error"
            summary["browser_error_corrupted"] += 1
        elif source_record is not None:
            try:
                semantic_validation = validate_pdf_bytes_for_recipe_record(
                    read_result.get("bytes") or b"",
                    source_record,
                )
            except Exception as exc:
                summary["failed"] += 1
                summary["items"].append({
                    "object_key": object_key,
                    "status": "failed",
                    "error": f"Semantic PDF validation raised unexpectedly: {exc}",
                })
                continue
            if semantic_validation.get("ok"):
                reconciliation = {"ok": True, "reconciled": False}
                if apply and len(targets) == 1:
                    try:
                        reconciliation = reconcile_validated_repair_metadata(
                            object_key,
                            targets[0],
                            source_record,
                            read_result.get("bytes") or b"",
                            semantic_validation,
                            data_root=data_root,
                        )
                    except Exception as exc:
                        reconciliation = {
                            "ok": False,
                            "error": f"Metadata reconciliation raised unexpectedly: {exc}",
                        }
                    if not reconciliation.get("ok"):
                        summary["failed"] += 1
                        summary["items"].append({
                            "object_key": object_key,
                            "status": "metadata_reconcile_failed",
                            "etag": remote_etag,
                            "error": reconciliation.get("error") or "Metadata reconciliation failed.",
                        })
                        continue
                    if reconciliation.get("reconciled") or reconciliation.get(
                        "already_reconciled"
                    ):
                        if reconciliation.get("reconciled"):
                            summary["metadata_reconciled"] += 1
                        state_result = append_repair_state(
                            state_path,
                            {
                                **state_scope,
                                "timestamp": utc_iso_now(),
                                "status": "success",
                                "object_key": object_key,
                                "etag": reconciliation.get("etag", ""),
                                "sha256": reconciliation.get("sha256", ""),
                                "size_bytes": reconciliation.get("size_bytes", 0),
                                "metadata_reconciled": bool(
                                    reconciliation.get("reconciled")
                                ),
                                "metadata_already_reconciled": bool(
                                    reconciliation.get("already_reconciled")
                                ),
                            },
                        )
                        if not state_result.get("ok"):
                            summary["state_write_failures"] += 1
                            summary["failed"] += 1
                            reconciliation["state_write_error"] = state_result.get("error")
                summary["valid_unchanged"] += 1
                summary["items"].append({
                    "object_key": object_key,
                    "status": (
                        "metadata_checkpoint_state_write_failed"
                        if reconciliation.get("state_write_error")
                        else "metadata_reconciled"
                        if reconciliation.get("reconciled")
                        else "metadata_checkpoint_recovered"
                        if reconciliation.get("already_reconciled")
                        else "valid_unchanged"
                    ),
                    "etag": remote_etag,
                    "page_count": inspection.get("page_count", 0),
                    "text_length": inspection.get("text_length", 0),
                    "mapping": mapping,
                    "validation_version": semantic_validation.get("validation_version", ""),
                    "state_write_error": reconciliation.get("state_write_error", ""),
                })
                continue
            corruption_type = "semantic_invalid"
            summary["semantic_invalid"] += 1
        else:
            summary["unverified_unchanged"] += 1
            summary["items"].append({
                "object_key": object_key,
                "status": "unverified_unchanged",
                "etag": remote_etag,
                "page_count": inspection.get("page_count", 0),
                "text_length": inspection.get("text_length", 0),
                "reason": mapping,
            })
            continue

        summary["corrupted"] += 1
        if source_record is None:
            summary["skipped"] += 1
            item = {
                "object_key": object_key,
                "status": "skipped",
                "reason": mapping,
                "browser_error_code": inspection.get("browser_error_code", ""),
                "corruption_type": corruption_type,
                "validation_error": semantic_validation.get("error", ""),
                "structural_error": inspection.get("error", ""),
                "saved_record_count": len(targets),
            }
            summary["items"].append(item)
            log(f"[{index}/{len(remote_objects)}] skipped {object_key}: {mapping}")
            continue

        summary["repairable"] += 1
        target_record = targets[0]
        item = {
            "object_key": object_key,
            "status": "repairable" if not apply else "repairing",
            "mapping": mapping,
            "workspace_id": target_record.workspace_id,
            "target_source_url": target_record.source_url,
            "repair_source_url": source_record.source_url,
            "recipe_title": recipe_title(source_record),
            "browser_error_code": inspection.get("browser_error_code", ""),
            "corruption_type": corruption_type,
            "validation_error": semantic_validation.get("error", ""),
            "structural_error": inspection.get("error", ""),
        }
        if not apply:
            summary["items"].append(item)
            log(f"[{index}/{len(remote_objects)}] repairable {object_key}")
            continue

        try:
            repair_result = regenerate_and_replace_object(
                object_key,
                target_record,
                source_record,
                data_root=data_root,
                expected_etag=remote_etag,
            )
        except Exception as exc:
            repair_result = {
                "ok": False,
                "remote_repaired": False,
                "remote_mutation_unknown": True,
                "error": f"Repair raised unexpectedly; R2 mutation state is unknown: {exc}",
            }
        if not repair_result.get("ok"):
            summary["failed"] += 1
            if repair_result.get("remote_repaired"):
                summary["production_r2_mutations"] += 1
            if repair_result.get("remote_mutation_unknown"):
                summary["production_r2_mutations_possible"] += 1
            item.update({
                "status": "failed",
                "error": repair_result.get("error") or "Repair failed.",
                "remote_repaired": bool(repair_result.get("remote_repaired")),
                "remote_mutation_unknown": bool(
                    repair_result.get("remote_mutation_unknown")
                ),
            })
            state_result = append_repair_state(
                state_path,
                {
                    **state_scope,
                    "timestamp": utc_iso_now(),
                    "status": (
                        "remote_repaired_pending_metadata"
                        if item["remote_repaired"]
                        else "repair_failed_mutation_unknown"
                        if item["remote_mutation_unknown"]
                        else "failed"
                    ),
                    "object_key": object_key,
                    "error": item["error"],
                    "remote_repaired": item["remote_repaired"],
                    "remote_mutation_unknown": item["remote_mutation_unknown"],
                    "etag": repair_result.get("etag", ""),
                    "sha256": repair_result.get("sha256", ""),
                    "size_bytes": repair_result.get("size_bytes", 0),
                },
            )
            if not state_result.get("ok"):
                summary["state_write_failures"] += 1
                item["state_write_error"] = state_result.get("error", "")
            summary["items"].append(item)
            log(f"[{index}/{len(remote_objects)}] failed {object_key}: {item['error']}")
            continue

        summary["repaired"] += 1
        summary["production_r2_mutations"] += 1
        item.update({
            "status": "repaired",
            "etag": repair_result.get("etag", ""),
            "sha256": repair_result.get("sha256", ""),
            "size_bytes": repair_result.get("size_bytes", 0),
            "remote_verified": True,
            "local_path": repair_result.get("local_path", ""),
        })
        state_result = append_repair_state(
            state_path,
            {
                **state_scope,
                "timestamp": utc_iso_now(),
                "status": "success",
                "object_key": object_key,
                "etag": item["etag"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            },
        )
        if not state_result.get("ok"):
            summary["state_write_failures"] += 1
            summary["failed"] += 1
            item["status"] = "repaired_state_write_failed"
            item["state_write_error"] = state_result.get("error", "")
        summary["items"].append(item)
        log(f"[{index}/{len(remote_objects)}] repaired and verified {object_key}")

    summary["completed_at"] = utc_iso_now()
    summary["ok"] = bool(
        summary["failed"] == 0
        and (
            not apply
            or (summary["skipped"] == 0 and summary["unverified_unchanged"] == 0)
        )
    )
    summary["incomplete"] = bool(
        apply
        and (
            summary["skipped"]
            or summary["unverified_unchanged"]
            or summary["state_write_failures"]
        )
    )
    if report_path:
        _write_json_atomically(report_path, summary)
    return summary


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Audit generated-recipe PDFs in Cloudflare R2. Defaults to a read-only dry run."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Regenerate, validate, and overwrite repairable objects at their existing R2 keys.",
    )
    parser.add_argument(
        "--confirm-r2-overwrite",
        action="store_true",
        help="Required with --apply to authorize production R2 overwrites.",
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    legacy_group = parser.add_mutually_exclusive_group()
    legacy_group.add_argument(
        "--legacy-output",
        type=Path,
        default=None,
        help="Explicit legacy recipe output folder to include.",
    )
    legacy_group.add_argument(
        "--no-legacy-output",
        action="store_true",
        help="Exclude the repository legacy recipe output folder.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--object-key",
        action="append",
        default=[],
        help="Restrict the audit/repair to one object key; may be supplied more than once.",
    )
    return parser


def main(argv=None):
    load_repository_dotenv()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.confirm_r2_overwrite:
        parser.error("--apply requires --confirm-r2-overwrite")
    if args.no_legacy_output:
        legacy_output = None
    elif args.legacy_output is not None:
        legacy_output = args.legacy_output
    elif normalized_users_data_root(args.data_root).resolve() == normalized_users_data_root(
        DEFAULT_DATA_ROOT
    ).resolve():
        legacy_output = DEFAULT_LEGACY_OUTPUT
    else:
        legacy_output = None

    result = audit_and_repair_generated_recipe_pdfs(
        data_root=args.data_root,
        legacy_output=legacy_output,
        apply=args.apply,
        confirm_r2_overwrite=args.confirm_r2_overwrite,
        report_path=args.report,
        state_path=args.state_file,
        object_keys=args.object_key,
    )
    concise = {key: value for key, value in result.items() if key != "items"}
    print(json.dumps(concise, indent=2, ensure_ascii=False))
    print(f"Detailed report: {Path(args.report).resolve()}")
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
