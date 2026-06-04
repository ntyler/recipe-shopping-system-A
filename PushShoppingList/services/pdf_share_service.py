import json
import os
import secrets
from datetime import datetime
from datetime import timedelta
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PACKAGE_DIR.parent
EXTRACTOR_DATA_DIR = PACKAGE_DIR / "services" / "recipe-extractor" / "data"
PDF_DIR = EXTRACTOR_DATA_DIR / "pdf"
PDF_SHARE_LINKS_FILE = EXTRACTOR_DATA_DIR / "pdf_share_links.json"
DEFAULT_SHARE_DAYS = 30


def utc_now():
    return datetime.utcnow().replace(microsecond=0)


def now_iso():
    return utc_now().isoformat() + "Z"


def iso_from_datetime(value):
    return value.replace(microsecond=0).isoformat() + "Z"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None


def path_value(path_like):
    return Path(os.fspath(path_like))


def pdf_storage_dir():
    path = path_value(PDF_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pdf_share_links_file():
    path = path_value(PDF_SHARE_LINKS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_share_links():
    path = pdf_share_links_file()

    if not path.exists():
        return {"links": []}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"links": []}

    if isinstance(payload, list):
        links = payload
    elif isinstance(payload, dict):
        links = payload.get("links", [])
    else:
        links = []

    return {
        "links": [
            normalize_share_record(record)
            for record in links
            if isinstance(record, dict) and record.get("token")
        ],
    }


def save_share_links(payload):
    normalized = {
        "links": [
            normalize_share_record(record)
            for record in payload.get("links", [])
            if isinstance(record, dict) and record.get("token")
        ],
    }
    pdf_share_links_file().write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return normalized


def normalize_share_record(record):
    record = record if isinstance(record, dict) else {}
    return {
        "token": str(record.get("token") or "").strip(),
        "pdf_filename": Path(str(record.get("pdf_filename") or "")).name,
        "pdf_path": str(record.get("pdf_path") or ""),
        "original_filename": Path(str(record.get("original_filename") or record.get("pdf_filename") or "")).name,
        "created_at": str(record.get("created_at") or ""),
        "expires_at": str(record.get("expires_at") or ""),
        "created_by_user_id": str(record.get("created_by_user_id") or ""),
        "created_by_email": str(record.get("created_by_email") or ""),
        "allow_download": bool(record.get("allow_download", True)),
        "revoked": bool(record.get("revoked", False)),
        "access_count": int(record.get("access_count") or 0),
        "last_accessed_at": record.get("last_accessed_at") or None,
    }


def pdf_path_for_metadata(path):
    try:
        return path.resolve().relative_to(REPO_DIR.resolve()).as_posix()
    except ValueError:
        return path.name


def safe_resolve_pdf_path(pdf_filename):
    filename = Path(str(pdf_filename or "")).name

    if not filename or filename != str(pdf_filename or "").strip():
        return None

    if Path(filename).suffix.lower() != ".pdf":
        return None

    pdf_dir = pdf_storage_dir().resolve()
    candidate = (pdf_dir / filename).resolve()

    try:
        candidate.relative_to(pdf_dir)
    except ValueError:
        return None

    return candidate


def format_file_size(size):
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 0

    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value = value / 1024

    return f"{size} B"


def active_share_for_pdf(pdf_filename, payload=None):
    payload = payload or load_share_links()
    filename = Path(str(pdf_filename or "")).name

    for record in reversed(payload.get("links", [])):
        if record.get("pdf_filename") != filename:
            continue
        if is_share_active(record):
            return record

    return None


def cloudflare_pdf_metadata_rows():
    try:
        from PushShoppingList.services.recipe_edit_service import list_recipe_pdf_storage_metadata
    except Exception:
        return []

    try:
        return list_recipe_pdf_storage_metadata()
    except Exception:
        return []


def cloudflare_pdf_metadata_by_filename():
    rows = {}

    for row in cloudflare_pdf_metadata_rows():
        filename = Path(str(row.get("pdf_filename") or "")).name
        public_url = str(row.get("public_url") or "").strip()

        if filename and public_url:
            rows[filename] = row

    return rows


def list_available_pdfs():
    pdf_dir = pdf_storage_dir()
    payload = load_share_links()
    r2_metadata = cloudflare_pdf_metadata_by_filename()
    rows = []
    seen_filenames = set()

    for path in sorted(pdf_dir.glob("*.pdf"), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue

        stat = path.stat()
        modified = datetime.utcfromtimestamp(stat.st_mtime).replace(microsecond=0)
        active_share = active_share_for_pdf(path.name, payload)
        r2_row = r2_metadata.get(path.name, {})
        seen_filenames.add(path.name)
        rows.append({
            "pdf_filename": path.name,
            "original_filename": path.name,
            "size": stat.st_size,
            "size_label": format_file_size(stat.st_size),
            "modified_at": iso_from_datetime(modified),
            "modified_label": modified.strftime("%Y-%m-%d %H:%M UTC"),
            "active_share": active_share,
            "local_available": True,
            "recipe_url": r2_row.get("source_url", ""),
            "r2_object_key": r2_row.get("object_key", ""),
            "r2_public_url": r2_row.get("public_url", ""),
            "r2_uploaded_at": r2_row.get("uploaded_at", ""),
        })

    for filename, r2_row in sorted(r2_metadata.items(), key=lambda item: item[0].lower()):
        if filename in seen_filenames:
            continue

        uploaded_at = str(r2_row.get("uploaded_at") or "").strip()
        rows.append({
            "pdf_filename": filename,
            "original_filename": filename,
            "size": 0,
            "size_label": "Cloudflare R2",
            "modified_at": uploaded_at,
            "modified_label": uploaded_at or "Uploaded to Cloudflare R2",
            "active_share": None,
            "local_available": False,
            "recipe_url": r2_row.get("source_url", ""),
            "r2_object_key": r2_row.get("object_key", ""),
            "r2_public_url": r2_row.get("public_url", ""),
            "r2_uploaded_at": uploaded_at,
        })

    return rows


def generate_share_token(payload=None):
    payload = payload or load_share_links()
    existing_tokens = {
        str(record.get("token") or "")
        for record in payload.get("links", [])
    }

    for _ in range(10):
        token = secrets.token_urlsafe(32)
        if token not in existing_tokens:
            return token

    raise RuntimeError("Unable to create a unique PDF share token.")


def create_pdf_share_link(pdf_filename, current_user=None, expires_days=DEFAULT_SHARE_DAYS, allow_download=True):
    pdf_path = safe_resolve_pdf_path(pdf_filename)

    if not pdf_path or not pdf_path.exists():
        return {
            "ok": False,
            "error": "PDF file was not found.",
        }

    payload = load_share_links()
    existing = active_share_for_pdf(pdf_path.name, payload)

    if existing:
        return {
            "ok": True,
            "record": existing,
            "created": False,
        }

    created_at = utc_now()
    expires_at = created_at + timedelta(days=int(expires_days or DEFAULT_SHARE_DAYS))
    current_user = current_user if isinstance(current_user, dict) else {}
    record = {
        "token": generate_share_token(payload),
        "pdf_filename": pdf_path.name,
        "pdf_path": pdf_path_for_metadata(pdf_path),
        "original_filename": pdf_path.name,
        "created_at": iso_from_datetime(created_at),
        "expires_at": iso_from_datetime(expires_at),
        "created_by_user_id": str(current_user.get("user_id") or ""),
        "created_by_email": str(current_user.get("email") or ""),
        "allow_download": bool(allow_download),
        "revoked": False,
        "access_count": 0,
        "last_accessed_at": None,
    }
    payload["links"].append(record)
    save_share_links(payload)

    return {
        "ok": True,
        "record": record,
        "created": True,
    }


def find_share_record(token, payload=None):
    token = str(token or "").strip()

    if not token:
        return None

    payload = payload or load_share_links()

    for record in payload.get("links", []):
        if record.get("token") == token:
            return record

    return None


def is_share_expired(record):
    expires_at = parse_iso_datetime(record.get("expires_at"))
    return True if not expires_at else expires_at <= utc_now()


def is_share_active(record):
    return bool(record and not record.get("revoked") and not is_share_expired(record))


def resolve_share_token(token):
    record = find_share_record(token)

    if not record:
        return {
            "ok": False,
            "status": 404,
            "error": "PDF share link was not found.",
        }

    if record.get("revoked"):
        return {
            "ok": False,
            "status": 410,
            "error": "PDF share link has been revoked.",
        }

    if is_share_expired(record):
        return {
            "ok": False,
            "status": 410,
            "error": "PDF share link has expired.",
        }

    pdf_path = safe_resolve_pdf_path(record.get("pdf_filename"))

    if not pdf_path or not pdf_path.exists():
        return {
            "ok": False,
            "status": 404,
            "error": "The shared PDF file is no longer available.",
        }

    return {
        "ok": True,
        "record": record,
        "pdf_path": pdf_path,
    }


def revoke_share_token(token):
    payload = load_share_links()
    record = find_share_record(token, payload)

    if not record:
        return {
            "ok": False,
            "error": "PDF share link was not found.",
        }

    record["revoked"] = True
    save_share_links(payload)

    return {
        "ok": True,
        "record": record,
    }


def record_share_access(token):
    payload = load_share_links()
    record = find_share_record(token, payload)

    if not record:
        return None

    record["access_count"] = int(record.get("access_count") or 0) + 1
    record["last_accessed_at"] = now_iso()
    save_share_links(payload)
    return record
