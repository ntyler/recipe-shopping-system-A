import json
import logging
from datetime import datetime
from datetime import timezone
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import unquote
from urllib.parse import urlparse

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services.pdf_share_service import format_file_size
from PushShoppingList.services.storage_service import GUEST_DATA_DIR
from PushShoppingList.services.storage_service import LEGACY_EXTRACTOR_DIR
from PushShoppingList.services.storage_service import PACKAGE_DIR
from PushShoppingList.services.storage_service import USER_DATA_DIR


LOGGER = logging.getLogger(__name__)
UNLINKED_PDF_REASON = "No matching normalized Cloudflare/R2 PDF reference was found in app JSON records."


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def existing_json_paths(paths):
    seen = set()
    results = []

    for path in paths:
        candidate = Path(path)
        if not candidate.exists() or not candidate.is_file():
            continue

        resolved = candidate.resolve()
        if resolved in seen:
            continue

        seen.add(resolved)
        results.append(candidate)

    return sorted(results, key=lambda item: str(item).lower())


def workspace_roots():
    roots = [PACKAGE_DIR]

    for base_dir in (USER_DATA_DIR, GUEST_DATA_DIR):
        base = Path(base_dir)
        if not base.exists() or not base.is_dir():
            continue

        roots.extend(child for child in base.iterdir() if child.is_dir())

    return roots


def reference_json_paths_for_root(root):
    root = Path(root)
    paths = list(root.glob("*.json"))
    data_dir = root / "recipe-extractor" / "data"

    paths.extend(data_dir.glob("*.json"))
    for subdir in ("output", "menus", "menu_output"):
        paths.extend((data_dir / subdir).glob("*.json"))

    return paths


def reference_json_paths():
    paths = []
    paths.extend((LEGACY_EXTRACTOR_DIR / "data").glob("*.json"))
    paths.extend((LEGACY_EXTRACTOR_DIR / "data" / "output").glob("*.json"))

    for root in workspace_roots():
        paths.extend(reference_json_paths_for_root(root))

    return existing_json_paths(paths)


def normalized_reference_path(value):
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""

    text = text.split("?", 1)[0].split("#", 1)[0]
    return unquote(text).lstrip("/")


def configured_public_base_paths():
    paths = []
    public_base_url = cloudflare_r2_storage.config_values().get("public_base_url", "")
    parsed = urlparse(public_base_url)
    base_path = normalized_reference_path(parsed.path)

    if base_path:
        paths.append(base_path.rstrip("/"))

    return paths


def expand_candidate_path(candidate, allow_suffix=False):
    candidate = normalized_reference_path(candidate)
    if not candidate:
        return []

    expanded = [(candidate, allow_suffix)]
    bucket = str(cloudflare_r2_storage.config_values().get("bucket_name") or "").strip().strip("/")

    if bucket and candidate.startswith(f"{bucket}/"):
        expanded.append((candidate[len(bucket) + 1:], allow_suffix))

    for base_path in configured_public_base_paths():
        if candidate == base_path:
            continue
        if candidate.startswith(f"{base_path}/"):
            expanded.append((candidate[len(base_path) + 1:], allow_suffix))

    return expanded


def reference_candidate_paths(value):
    text = str(value or "").strip()
    if not text or ".pdf" not in text.lower():
        return []

    candidates = []
    for raw_value in (text, unquote(text)):
        normalized = raw_value.replace("\\", "/").strip()
        if not normalized:
            continue

        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            candidates.extend(expand_candidate_path(parsed.path, allow_suffix=True))

        candidates.extend(expand_candidate_path(normalized, allow_suffix=False))

    deduped = []
    seen = set()
    for candidate, allow_suffix in candidates:
        marker = (candidate, allow_suffix)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(marker)

    return deduped


def normalized_object_key(object_key):
    return normalized_reference_path(object_key)


def known_object_key_lookup(known_object_keys):
    lookup = {}

    for object_key in known_object_keys or []:
        key = str(object_key or "").strip().replace("\\", "/")
        if not key:
            continue
        normalized = normalized_object_key(key)
        if not normalized:
            continue
        lookup.setdefault(normalized, set()).add(key)

    return lookup


def candidate_suffixes(candidate):
    parts = [part for part in str(candidate or "").split("/") if part]
    for index in range(len(parts)):
        yield "/".join(parts[index:])


def known_pdf_object_keys_from_string(value, lookup):
    keys = set()

    for candidate, allow_suffix in reference_candidate_paths(value):
        keys.update(lookup.get(candidate, set()))
        if allow_suffix:
            for suffix in candidate_suffixes(candidate):
                keys.update(lookup.get(suffix, set()))

    return keys


def allowed_prefix_pdf_object_keys_from_string(value):
    keys = set()

    for candidate, _allow_suffix in reference_candidate_paths(value):
        for prefix in cloudflare_r2_storage.ALLOWED_PDF_OBJECT_PREFIXES:
            start = candidate.find(prefix)
            while start >= 0:
                tail = candidate[start:]
                pdf_end = tail.lower().find(".pdf")
                if pdf_end >= 0:
                    object_key = tail[:pdf_end + 4]
                    try:
                        keys.add(cloudflare_r2_storage.validate_object_key(object_key))
                    except cloudflare_r2_storage.CloudflareR2StorageError:
                        pass
                start = candidate.find(prefix, start + 1)

    return keys


def pdf_object_keys_from_string(value, known_lookup=None):
    if known_lookup is not None:
        return known_pdf_object_keys_from_string(value, known_lookup)

    return allowed_prefix_pdf_object_keys_from_string(value)


def pdf_object_keys_from_value(value, known_lookup=None):
    keys = set()

    if isinstance(value, dict):
        for child in value.values():
            keys.update(pdf_object_keys_from_value(child, known_lookup=known_lookup))
        return keys

    if isinstance(value, list):
        for child in value:
            keys.update(pdf_object_keys_from_value(child, known_lookup=known_lookup))
        return keys

    if isinstance(value, str):
        keys.update(pdf_object_keys_from_string(value, known_lookup=known_lookup))

    return keys


def referenced_pdf_object_keys(paths=None, known_object_keys=None):
    references = {}
    paths = list(paths) if paths is not None else reference_json_paths()
    lookup = known_object_key_lookup(known_object_keys) if known_object_keys is not None else None

    for path in existing_json_paths(paths):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for object_key in pdf_object_keys_from_value(payload, known_lookup=lookup):
            references.setdefault(object_key, []).append(str(path))

    return references


def suspected_pdf_type(object_key):
    key = str(object_key or "").strip().replace("\\", "/")
    lower_key = key.lower()
    filename = PurePosixPath(key).name.lower()

    if lower_key.startswith(cloudflare_r2_storage.MENU_PDF_OBJECT_PREFIX):
        return "menu PDF"

    if "generated" in filename or "generated_recipe" in lower_key:
        return "generated recipe PDF"

    if any(marker in filename for marker in ("source", "webpage", "backup", "archive")):
        return "source PDF"

    if lower_key.startswith(cloudflare_r2_storage.PDF_OBJECT_PREFIX):
        return "source PDF"

    if "menu" in lower_key:
        return "menu PDF"

    return "unknown"


def enrich_r2_pdf_object(row):
    row = dict(row or {})
    object_key = str(row.get("object_key") or "").strip().replace("\\", "/")
    size = int(row.get("size") or 0)
    row["object_key"] = object_key
    row["filename"] = PurePosixPath(object_key).name or object_key
    row["size"] = size
    row["size_label"] = format_file_size(size) if size else "Unknown size"
    row["last_modified_label"] = str(row.get("last_modified") or "").strip() or "Unknown modified date"
    row["suspected_type"] = suspected_pdf_type(object_key)
    row["reason"] = UNLINKED_PDF_REASON
    return row


def unlinked_failure_result(list_result):
    return {
        **list_result,
        "checked_at": utc_now_iso(),
        "referenced_pdf_count": 0,
        "reference_file_count": 0,
        "total_cloudflare_pdfs": 0,
        "unlinked_pdf_count": 0,
        "unlinked_pdfs": [],
        "orphaned_pdf_count": 0,
        "orphaned_pdfs": [],
    }


def with_orphan_aliases(result):
    return {
        **result,
        "orphaned_pdf_count": result.get("unlinked_pdf_count", 0),
        "orphaned_pdfs": result.get("unlinked_pdfs", []),
    }


def log_unlinked_pdf_scan(result):
    LOGGER.info(
        "Cloudflare unlinked PDF scan checked_at=%s bucket=%s total=%s referenced=%s "
        "unlinked=%s reference_files=%s unlinked_sample=%s",
        result.get("checked_at"),
        result.get("bucket", ""),
        result.get("total_cloudflare_pdfs", 0),
        result.get("referenced_pdf_count", 0),
        result.get("unlinked_pdf_count", 0),
        result.get("reference_file_count", 0),
        [row.get("object_key", "") for row in result.get("unlinked_pdfs", [])[:20]],
    )


def log_unlinked_pdf_delete(result):
    LOGGER.info(
        "Cloudflare unlinked PDF delete deleted_at=%s bucket=%s requested=%s deleted=%s "
        "failed=%s skipped=%s deleted_sample=%s",
        result.get("deleted_at"),
        result.get("bucket", ""),
        result.get("requested_count", 0),
        result.get("deleted_count", 0),
        result.get("failed_count", 0),
        result.get("skipped_count", 0),
        [row.get("object_key", "") for row in result.get("deleted_pdfs", [])[:20]],
    )


def scan_unlinked_cloudflare_pdfs():
    list_result = cloudflare_r2_storage.list_all_pdf_objects()
    if not list_result.get("ok"):
        result = with_orphan_aliases(unlinked_failure_result(list_result))
        log_unlinked_pdf_scan(result)
        return result

    pdf_objects = list_result.get("objects", [])
    known_object_keys = [
        str(row.get("object_key") or "").strip().replace("\\", "/")
        for row in pdf_objects
        if str(row.get("object_key") or "").strip()
    ]
    reference_paths = reference_json_paths()
    references = referenced_pdf_object_keys(paths=reference_paths, known_object_keys=known_object_keys)
    unlinked_pdfs = [
        enrich_r2_pdf_object(row)
        for row in pdf_objects
        if row.get("object_key") not in references
    ]

    result = with_orphan_aliases({
        "ok": True,
        "success": True,
        "checked_at": utc_now_iso(),
        "bucket": list_result.get("bucket", ""),
        "total_cloudflare_pdfs": len(pdf_objects),
        "referenced_pdf_count": len(references),
        "reference_file_count": len(reference_paths),
        "unlinked_pdf_count": len(unlinked_pdfs),
        "unlinked_pdfs": unlinked_pdfs,
    })
    log_unlinked_pdf_scan(result)
    return result


def scan_orphaned_cloudflare_pdfs():
    return scan_unlinked_cloudflare_pdfs()


def normalize_requested_object_keys(object_keys):
    if object_keys is None:
        return []

    if isinstance(object_keys, (str, bytes)):
        object_keys = [object_keys]

    normalized = []
    seen = set()
    for item in object_keys:
        if isinstance(item, dict):
            item = item.get("object_key")

        key = str(item or "").strip().replace("\\", "/")
        if not key or key in seen:
            continue

        seen.add(key)
        normalized.append(key)

    return normalized


def delete_failure_result(code, error, requested_keys=None, scan_result=None):
    scan_result = scan_result or {}
    unlinked_pdfs = scan_result.get("unlinked_pdfs", [])
    result = {
        "ok": False,
        "success": False,
        "code": code,
        "error": error,
        "deleted_at": utc_now_iso(),
        "checked_at": scan_result.get("checked_at", ""),
        "bucket": scan_result.get("bucket", ""),
        "total_cloudflare_pdfs": scan_result.get("total_cloudflare_pdfs", 0),
        "referenced_pdf_count": scan_result.get("referenced_pdf_count", 0),
        "reference_file_count": scan_result.get("reference_file_count", 0),
        "requested_count": len(requested_keys or []),
        "deleted_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "deleted_pdfs": [],
        "failed_pdfs": [],
        "skipped_pdfs": [],
        "unlinked_pdf_count": len(unlinked_pdfs),
        "unlinked_pdfs": unlinked_pdfs,
    }
    return with_orphan_aliases(result)


def delete_unlinked_cloudflare_pdfs(object_keys):
    requested_keys = normalize_requested_object_keys(object_keys)
    if not requested_keys:
        result = delete_failure_result(
            "no_selection",
            "Select at least one unlinked PDF to delete.",
            requested_keys,
        )
        log_unlinked_pdf_delete(result)
        return result

    scan_result = scan_unlinked_cloudflare_pdfs()
    if not scan_result.get("ok"):
        result = delete_failure_result(
            scan_result.get("code", "scan_failed"),
            scan_result.get("error", "Unable to check unlinked PDFs before deletion."),
            requested_keys,
            scan_result=scan_result,
        )
        log_unlinked_pdf_delete(result)
        return result

    unlinked_pdfs = scan_result.get("unlinked_pdfs", [])
    unlinked_by_key = {
        str(row.get("object_key") or "").strip().replace("\\", "/"): row
        for row in unlinked_pdfs
        if str(row.get("object_key") or "").strip()
    }
    deleted_pdfs = []
    failed_pdfs = []
    skipped_pdfs = []

    for object_key in requested_keys:
        row = unlinked_by_key.get(object_key)
        if not row:
            skipped_pdfs.append({
                "object_key": object_key,
                "reason": "PDF is no longer unlinked or was not found in the latest scan.",
            })
            continue

        delete_result = cloudflare_r2_storage.delete_pdf_object(object_key)
        if delete_result.get("ok"):
            deleted_pdfs.append({
                **row,
                "public_url": delete_result.get("public_url", row.get("public_url", "")),
            })
        else:
            failed_pdfs.append({
                **row,
                "code": delete_result.get("code", "delete_failed"),
                "error": delete_result.get("error", "Unable to delete PDF from Cloudflare R2."),
            })

    deleted_keys = {row["object_key"] for row in deleted_pdfs}
    remaining_unlinked_pdfs = [
        row for row in unlinked_pdfs
        if row.get("object_key") not in deleted_keys
    ]
    deleted_count = len(deleted_pdfs)
    total_cloudflare_pdfs = max(int(scan_result.get("total_cloudflare_pdfs") or 0) - deleted_count, 0)
    failed_count = len(failed_pdfs)
    skipped_count = len(skipped_pdfs)
    ok = failed_count == 0
    message = f"Deleted {deleted_count} selected unlinked PDF{'s' if deleted_count != 1 else ''}."
    if failed_count:
        message = f"Deleted {deleted_count} selected unlinked PDFs; {failed_count} failed."
    elif deleted_count == 0 and skipped_count:
        message = "No selected PDFs were still unlinked in the latest scan."

    result = with_orphan_aliases({
        "ok": ok,
        "success": ok,
        "code": "" if ok else "delete_failed",
        "error": "" if ok else message,
        "message": message,
        "deleted_at": utc_now_iso(),
        "checked_at": scan_result.get("checked_at", ""),
        "bucket": scan_result.get("bucket", ""),
        "total_cloudflare_pdfs": total_cloudflare_pdfs,
        "referenced_pdf_count": scan_result.get("referenced_pdf_count", 0),
        "reference_file_count": scan_result.get("reference_file_count", 0),
        "requested_count": len(requested_keys),
        "deleted_count": deleted_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "deleted_pdfs": deleted_pdfs,
        "failed_pdfs": failed_pdfs,
        "skipped_pdfs": skipped_pdfs,
        "unlinked_pdf_count": len(remaining_unlinked_pdfs),
        "unlinked_pdfs": remaining_unlinked_pdfs,
    })
    log_unlinked_pdf_delete(result)
    return result


def delete_orphaned_cloudflare_pdfs():
    return delete_unlinked_cloudflare_pdfs(None)
