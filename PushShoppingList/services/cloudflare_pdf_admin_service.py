import json
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services.pdf_share_service import format_file_size
from PushShoppingList.services.storage_service import GUEST_DATA_DIR
from PushShoppingList.services.storage_service import LEGACY_EXTRACTOR_DIR
from PushShoppingList.services.storage_service import PACKAGE_DIR
from PushShoppingList.services.storage_service import USER_DATA_DIR


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


def reference_json_paths():
    paths = [
        PACKAGE_DIR / "restaurant_menus.json",
        LEGACY_EXTRACTOR_DIR / "data" / "pdf_share_links.json",
    ]
    paths.extend((LEGACY_EXTRACTOR_DIR / "data" / "output").glob("*.json"))

    for root in workspace_roots():
        paths.append(root / "restaurant_menus.json")
        paths.append(root / "recipe-extractor" / "data" / "pdf_share_links.json")
        paths.extend((root / "recipe-extractor" / "data" / "output").glob("*.json"))

    return existing_json_paths(paths)


def pdf_object_keys_from_string(value):
    keys = set()
    text = str(value or "").strip()
    if not text:
        return keys

    candidates = set()
    for raw_value in (text, unquote(text)):
        normalized = raw_value.replace("\\", "/").strip()
        if not normalized:
            continue

        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            candidates.add(unquote(parsed.path).lstrip("/"))

        candidates.add(normalized.split("?", 1)[0].split("#", 1)[0].lstrip("/"))

    for candidate in candidates:
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


def pdf_object_keys_from_value(value):
    keys = set()

    if isinstance(value, dict):
        for child in value.values():
            keys.update(pdf_object_keys_from_value(child))
        return keys

    if isinstance(value, list):
        for child in value:
            keys.update(pdf_object_keys_from_value(child))
        return keys

    if isinstance(value, str):
        keys.update(pdf_object_keys_from_string(value))

    return keys


def referenced_pdf_object_keys(paths=None):
    references = {}
    paths = list(paths) if paths is not None else reference_json_paths()

    for path in existing_json_paths(paths):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for object_key in pdf_object_keys_from_value(payload):
            references.setdefault(object_key, []).append(str(path))

    return references


def enrich_r2_pdf_object(row):
    row = dict(row or {})
    size = int(row.get("size") or 0)
    row["size"] = size
    row["size_label"] = format_file_size(size) if size else "Unknown size"
    row["last_modified_label"] = str(row.get("last_modified") or "").strip() or "Unknown modified date"
    return row


def scan_orphaned_cloudflare_pdfs():
    list_result = cloudflare_r2_storage.list_pdf_objects()
    if not list_result.get("ok"):
        return {
            **list_result,
            "checked_at": utc_now_iso(),
            "referenced_pdf_count": 0,
            "reference_file_count": 0,
            "orphaned_pdf_count": 0,
            "orphaned_pdfs": [],
        }

    references = referenced_pdf_object_keys()
    orphaned_pdfs = [
        enrich_r2_pdf_object(row)
        for row in list_result.get("objects", [])
        if row.get("object_key") not in references
    ]

    return {
        "ok": True,
        "success": True,
        "checked_at": utc_now_iso(),
        "bucket": list_result.get("bucket", ""),
        "total_cloudflare_pdfs": len(list_result.get("objects", [])),
        "referenced_pdf_count": len(references),
        "reference_file_count": len(reference_json_paths()),
        "orphaned_pdf_count": len(orphaned_pdfs),
        "orphaned_pdfs": orphaned_pdfs,
    }


def delete_orphaned_cloudflare_pdfs():
    scan = scan_orphaned_cloudflare_pdfs()
    if not scan.get("ok"):
        return scan

    deleted_pdfs = []
    failed_pdfs = []

    for row in scan.get("orphaned_pdfs", []):
        object_key = row.get("object_key", "")
        delete_result = cloudflare_r2_storage.delete_pdf(object_key)
        if delete_result.get("ok"):
            deleted_pdfs.append({
                **row,
                "delete_result": delete_result,
            })
        else:
            failed_pdfs.append({
                **row,
                "error": delete_result.get("error", "Unable to delete PDF."),
                "delete_result": delete_result,
            })

    return {
        **scan,
        "ok": True,
        "success": not failed_pdfs,
        "deleted_count": len(deleted_pdfs),
        "failed_count": len(failed_pdfs),
        "deleted_pdfs": deleted_pdfs,
        "failed_pdfs": failed_pdfs,
        "orphaned_pdf_count": len(failed_pdfs),
        "orphaned_pdfs": failed_pdfs,
    }
