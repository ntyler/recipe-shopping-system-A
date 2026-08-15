import json
import os
import secrets
import tempfile
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PACKAGE_DIR.parent
EXTRACTOR_DATA_DIR = PACKAGE_DIR / "services" / "recipe-extractor" / "data"
PDF_DIR = EXTRACTOR_DATA_DIR / "pdf"
PDF_SHARE_LINKS_FILE = EXTRACTOR_DATA_DIR / "pdf_share_links.json"
DEFAULT_SHARE_DAYS = 30
PDF_SHARE_BACKEND_ENV = "SHOPPING_APP_PDF_SHARE_BACKEND"
PDF_SHARE_BACKEND_MODES = frozenset({"json", "shadow", "db_preferred", "db_only"})
PDF_SHARE_DB_PATH = None


class PdfShareStorageError(RuntimeError):
    """Raised when an authoritative PDF-share backend cannot be used safely."""


def utc_now():
    return datetime.utcnow().replace(microsecond=0)


def now_iso():
    return utc_now().isoformat() + "Z"


def iso_from_datetime(value):
    return value.replace(microsecond=0).isoformat() + "Z"


def parse_iso_datetime(value):
    try:
        text = str(value or "")
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        return None


def path_value(path_like):
    return Path(os.fspath(path_like))


def pdf_storage_dir():
    path = path_value(PDF_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pdf_share_links_file(create_parent=False):
    path = path_value(PDF_SHARE_LINKS_FILE)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def pdf_share_backend_mode(environment=None):
    environment = environment if environment is not None else os.environ
    mode = str(environment.get(PDF_SHARE_BACKEND_ENV, "json") or "json").strip().lower()
    if mode not in PDF_SHARE_BACKEND_MODES:
        raise PdfShareStorageError("PDF-share backend mode is invalid.")
    return mode


def pdf_share_db_path():
    if PDF_SHARE_DB_PATH is not None:
        return Path(PDF_SHARE_DB_PATH)
    from PushShoppingList.services.application_data_service import application_data_db_path

    return application_data_db_path()


def pdf_share_encryptor():
    from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor

    return AesGcmDataEncryptor.from_environment()


def _database_is_authoritative(mode):
    if mode not in {"db_preferred", "db_only"}:
        return False
    try:
        from PushShoppingList.services import application_data_service

        status = application_data_service.application_schema_status(pdf_share_db_path())
        if status.get("exists") and not status.get("compatible"):
            raise PdfShareStorageError("PDF-share database schema is incompatible.")
        if not status.get("available"):
            if mode == "db_only":
                raise PdfShareStorageError("PDF-share database schema is unavailable.")
            if (
                status.get("current_version") is not None
                or "application_source_coverage" not in status.get("missing_tables", ())
            ):
                raise PdfShareStorageError("PDF-share database schema is unavailable.")
            return False
        from PushShoppingList.services.pdf_share_migration_service import (
            database_share_records_are_authoritative,
        )

        authoritative = database_share_records_are_authoritative(pdf_share_db_path())
        if not authoritative:
            if mode == "db_only":
                raise PdfShareStorageError(
                    "PDF-share database migration coverage is unavailable."
                )
            return False
        return True
    except PdfShareStorageError:
        raise
    except Exception as exc:
        raise PdfShareStorageError("PDF-share database coverage could not be read.") from exc


def _load_json_share_links():
    path = pdf_share_links_file()

    if not path.exists():
        return {"links": []}

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
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


def load_share_links(include_tokens=True):
    mode = pdf_share_backend_mode()
    if not _database_is_authoritative(mode):
        payload = _load_json_share_links()
        if include_tokens:
            return payload
        return {
            "links": [
                {**record, "token": ""}
                for record in payload.get("links", [])
            ]
        }
    try:
        from PushShoppingList.services.pdf_share_migration_service import database_share_records

        encryptor = pdf_share_encryptor() if include_tokens else None
        return database_share_records(
            pdf_share_db_path(),
            include_tokens=bool(include_tokens),
            encryptor=encryptor,
            require_authoritative=True,
        )
    except Exception as exc:
        if isinstance(exc, PdfShareStorageError):
            raise
        raise PdfShareStorageError("PDF-share database records could not be read.") from exc


def _atomic_save_json_share_links(payload):
    normalized = {
        "links": [
            normalize_share_record(record)
            for record in payload.get("links", [])
            if isinstance(record, dict) and record.get("token")
        ],
    }
    destination = pdf_share_links_file(create_parent=True)
    serialized = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=".%s." % destination.name,
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(destination))
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    return normalized


def save_share_links(payload):
    """Compatibility save; JSON remains authoritative in json/shadow modes."""

    mode = pdf_share_backend_mode()
    if _database_is_authoritative(mode):
        raise PdfShareStorageError(
            "Authoritative database share records require a token-scoped operation."
        )
    normalized = _atomic_save_json_share_links(payload)
    if mode == "shadow":
        try:
            from PushShoppingList.services.pdf_share_migration_service import database_upsert_share_record

            encryptor = pdf_share_encryptor()
            mirrored_at = now_iso()
            for record in normalized["links"]:
                database_upsert_share_record(
                    record,
                    pdf_share_db_path(),
                    encryptor,
                    updated_at=mirrored_at,
                )
        except Exception as exc:
            raise PdfShareStorageError("PDF-share shadow write failed.") from exc
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
    payload = payload if payload is not None else load_share_links(include_tokens=True)
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
    payload = load_share_links(include_tokens=True)
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
    payload = payload if payload is not None else load_share_links(include_tokens=True)
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

    payload = load_share_links(include_tokens=True)
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
    mode = pdf_share_backend_mode()
    if _database_is_authoritative(mode):
        try:
            from PushShoppingList.services.pdf_share_migration_service import database_upsert_share_record

            record = database_upsert_share_record(
                record,
                pdf_share_db_path(),
                pdf_share_encryptor(),
                register_artifact=True,
                artifact_path=pdf_path,
                require_authoritative=True,
            )
        except Exception as exc:
            raise PdfShareStorageError("PDF-share database create failed.") from exc
    else:
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

    if payload is None:
        mode = pdf_share_backend_mode()
        if _database_is_authoritative(mode):
            try:
                from PushShoppingList.services.pdf_share_migration_service import database_find_share_record

                return database_find_share_record(
                    token,
                    pdf_share_db_path(),
                    require_authoritative=True,
                )
            except Exception as exc:
                raise PdfShareStorageError("PDF-share database lookup failed.") from exc
        payload = _load_json_share_links()

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
    token = str(token or "").strip()
    mode = pdf_share_backend_mode()
    if _database_is_authoritative(mode):
        try:
            from PushShoppingList.services.pdf_share_migration_service import database_revoke_share_token

            record = database_revoke_share_token(
                token,
                pdf_share_db_path(),
                updated_at=now_iso(),
                require_authoritative=True,
            )
        except Exception as exc:
            raise PdfShareStorageError("PDF-share database revoke failed.") from exc
        if not record:
            return {
                "ok": False,
                "error": "PDF share link was not found.",
            }
        return {"ok": True, "record": record}

    payload = _load_json_share_links()
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
    token = str(token or "").strip()
    mode = pdf_share_backend_mode()
    if _database_is_authoritative(mode):
        try:
            from PushShoppingList.services.pdf_share_migration_service import database_record_share_access

            return database_record_share_access(
                token,
                pdf_share_db_path(),
                accessed_at=now_iso(),
                require_authoritative=True,
            )
        except Exception as exc:
            raise PdfShareStorageError("PDF-share database access update failed.") from exc

    payload = _load_json_share_links()
    record = find_share_record(token, payload)

    if not record:
        return None

    record["access_count"] = int(record.get("access_count") or 0) + 1
    record["last_accessed_at"] = now_iso()
    save_share_links(payload)
    return record
