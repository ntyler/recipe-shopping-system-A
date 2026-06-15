import os
from pathlib import Path
from urllib.parse import quote


REQUIRED_ENV_VARS = [
    "R2_ACCOUNT_ID",
    "R2_ENDPOINT",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_BASE_URL",
]
PDF_OBJECT_PREFIX = "recipe-pdfs/"
MENU_PDF_OBJECT_PREFIX = "menu-pdfs/"
ALLOWED_PDF_OBJECT_PREFIXES = (PDF_OBJECT_PREFIX, MENU_PDF_OBJECT_PREFIX)


class CloudflareR2StorageError(Exception):
    pass


def truthy_env(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def delete_local_pdf_after_upload():
    return truthy_env(os.getenv("DELETE_LOCAL_PDF_AFTER_UPLOAD"))


def config_values():
    return {
        "account_id": os.getenv("R2_ACCOUNT_ID", "").strip(),
        "endpoint": os.getenv("R2_ENDPOINT", "").strip(),
        "access_key_id": os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "secret_access_key": os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket_name": os.getenv("R2_BUCKET_NAME", "").strip(),
        "public_base_url": os.getenv("R2_PUBLIC_BASE_URL", "").strip(),
    }


def missing_env_vars():
    return [name for name in REQUIRED_ENV_VARS if not os.getenv(name, "").strip()]


def has_any_r2_config():
    return any(os.getenv(name, "").strip() for name in REQUIRED_ENV_VARS)


def has_required_r2_config():
    return not missing_env_vars()


def r2_client():
    missing = missing_env_vars()
    if missing:
        raise CloudflareR2StorageError(
            f"Missing Cloudflare R2 environment variables: {', '.join(missing)}"
        )

    try:
        import boto3
    except ImportError as exc:
        raise CloudflareR2StorageError("boto3 is required for Cloudflare R2 uploads.") from exc

    values = config_values()
    return boto3.client(
        "s3",
        endpoint_url=values["endpoint"],
        aws_access_key_id=values["access_key_id"],
        aws_secret_access_key=values["secret_access_key"],
        region_name="auto",
    )


def validate_pdf_path(local_pdf_path):
    path = Path(os.fspath(local_pdf_path)).expanduser()

    if path.name != Path(path.name).name or not path.name:
        return None, "Invalid PDF filename."

    if path.suffix.lower() != ".pdf":
        return None, "Only PDF files can be uploaded."

    if not path.exists() or not path.is_file():
        return None, "PDF file was not found."

    return path, ""


def normalize_object_prefix(object_prefix=None):
    prefix = str(object_prefix or PDF_OBJECT_PREFIX).strip().replace("\\", "/")
    if not prefix:
        prefix = PDF_OBJECT_PREFIX
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"
    if prefix.startswith("/") or ".." in prefix.split("/"):
        raise CloudflareR2StorageError("Invalid Cloudflare R2 object prefix.")
    return prefix


def object_key_for_pdf(local_pdf_path, object_prefix=PDF_OBJECT_PREFIX):
    path = Path(os.fspath(local_pdf_path))
    filename = Path(path.name).name

    if not filename or Path(filename).suffix.lower() != ".pdf":
        raise CloudflareR2StorageError("Only PDF files can be uploaded.")

    return f"{normalize_object_prefix(object_prefix)}{filename}"


def validate_object_key(object_key, allowed_prefixes=ALLOWED_PDF_OBJECT_PREFIXES):
    key = str(object_key or "").strip().replace("\\", "/")

    if not key or key.startswith("/") or ".." in key.split("/"):
        raise CloudflareR2StorageError("Invalid Cloudflare R2 object key.")

    allowed_prefixes = tuple(normalize_object_prefix(prefix) for prefix in (allowed_prefixes or (PDF_OBJECT_PREFIX,)))
    if not any(key.startswith(prefix) for prefix in allowed_prefixes):
        raise CloudflareR2StorageError(
            f"Object key must start with one of: {', '.join(allowed_prefixes)}."
        )

    if not key.lower().endswith(".pdf"):
        raise CloudflareR2StorageError("Only PDF objects can be managed.")

    return key


def normalize_object_prefixes(prefixes=None):
    prefixes = prefixes or ALLOWED_PDF_OBJECT_PREFIXES
    normalized = []

    for prefix in prefixes:
        normalized_prefix = normalize_object_prefix(prefix)
        if normalized_prefix not in normalized:
            normalized.append(normalized_prefix)

    return tuple(normalized)


def format_r2_last_modified(value):
    if not value:
        return ""

    if hasattr(value, "isoformat"):
        return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return str(value)


def get_public_url(object_key):
    key = validate_object_key(object_key)
    public_base_url = config_values()["public_base_url"].rstrip("/")

    if not public_base_url:
        raise CloudflareR2StorageError("R2_PUBLIC_BASE_URL is required.")

    return f"{public_base_url}/{quote(key, safe='/')}"


def get_public_url_for_object_key(object_key):
    key = str(object_key or "").strip().replace("\\", "/")
    public_base_url = config_values()["public_base_url"].rstrip("/")

    if not key:
        raise CloudflareR2StorageError("Invalid Cloudflare R2 object key.")

    if not key.lower().endswith(".pdf"):
        raise CloudflareR2StorageError("Only PDF objects can be listed.")

    if not public_base_url:
        raise CloudflareR2StorageError("R2_PUBLIC_BASE_URL is required.")

    return f"{public_base_url}/{quote(key.lstrip('/'), safe='/')}"


def object_exists(object_key):
    key = validate_object_key(object_key)
    values = config_values()
    client = r2_client()

    try:
        client.head_object(Bucket=values["bucket_name"], Key=key)
        return True
    except Exception as exc:
        response = getattr(exc, "response", {}) or {}
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        code = str(error.get("Code") or getattr(exc, "code", "") or "")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode") if isinstance(response, dict) else None

        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False

        raise CloudflareR2StorageError(f"Unable to check Cloudflare R2 object: {exc}") from exc


def list_pdf_objects(prefixes=ALLOWED_PDF_OBJECT_PREFIXES):
    try:
        values = config_values()
        client = r2_client()
        allowed_prefixes = normalize_object_prefixes(prefixes)
        objects_by_key = {}

        for prefix in allowed_prefixes:
            continuation_token = ""

            while True:
                request_args = {
                    "Bucket": values["bucket_name"],
                    "Prefix": prefix,
                }
                if continuation_token:
                    request_args["ContinuationToken"] = continuation_token

                page = client.list_objects_v2(**request_args) or {}

                for item in page.get("Contents", []) or []:
                    object_key = str(item.get("Key") or "").strip()
                    if not object_key.lower().endswith(".pdf"):
                        continue

                    try:
                        object_key = validate_object_key(object_key, allowed_prefixes=allowed_prefixes)
                    except CloudflareR2StorageError:
                        continue

                    objects_by_key[object_key] = {
                        "object_key": object_key,
                        "public_url": get_public_url(object_key),
                        "size": int(item.get("Size") or 0),
                        "last_modified": format_r2_last_modified(item.get("LastModified")),
                        "etag": str(item.get("ETag") or "").strip('"'),
                    }

                if not page.get("IsTruncated"):
                    break

                continuation_token = str(page.get("NextContinuationToken") or "").strip()
                if not continuation_token:
                    break

        objects = sorted(objects_by_key.values(), key=lambda item: item["object_key"].lower())
        return {
            "ok": True,
            "success": True,
            "bucket": values["bucket_name"],
            "objects": objects,
            "object_count": len(objects),
        }
    except CloudflareR2StorageError as exc:
        code = "missing_env" if missing_env_vars() else "list_failed"
        return {
            "ok": False,
            "success": False,
            "code": code,
            "error": str(exc),
            "objects": [],
            "object_count": 0,
        }
    except Exception as exc:
        return {
            "ok": False,
            "success": False,
            "code": "list_failed",
            "error": f"Cloudflare R2 list failed: {exc}",
            "objects": [],
            "object_count": 0,
        }


def list_all_pdf_objects():
    try:
        values = config_values()
        client = r2_client()
        objects_by_key = {}
        continuation_token = ""

        while True:
            request_args = {
                "Bucket": values["bucket_name"],
            }
            if continuation_token:
                request_args["ContinuationToken"] = continuation_token

            page = client.list_objects_v2(**request_args) or {}

            for item in page.get("Contents", []) or []:
                object_key = str(item.get("Key") or "").strip().replace("\\", "/")
                if not object_key.lower().endswith(".pdf"):
                    continue

                objects_by_key[object_key] = {
                    "object_key": object_key,
                    "public_url": get_public_url_for_object_key(object_key),
                    "size": int(item.get("Size") or 0),
                    "last_modified": format_r2_last_modified(item.get("LastModified")),
                    "etag": str(item.get("ETag") or "").strip('"'),
                }

            if not page.get("IsTruncated"):
                break

            continuation_token = str(page.get("NextContinuationToken") or "").strip()
            if not continuation_token:
                break

        objects = sorted(objects_by_key.values(), key=lambda item: item["object_key"].lower())
        return {
            "ok": True,
            "success": True,
            "bucket": values["bucket_name"],
            "objects": objects,
            "object_count": len(objects),
            "scope": "bucket",
        }
    except CloudflareR2StorageError as exc:
        code = "missing_env" if missing_env_vars() else "list_failed"
        return {
            "ok": False,
            "success": False,
            "code": code,
            "error": str(exc),
            "objects": [],
            "object_count": 0,
            "scope": "bucket",
        }
    except Exception as exc:
        return {
            "ok": False,
            "success": False,
            "code": "list_failed",
            "error": f"Cloudflare R2 list failed: {exc}",
            "objects": [],
            "object_count": 0,
            "scope": "bucket",
        }


def upload_pdf(local_pdf_path, object_prefix=PDF_OBJECT_PREFIX):
    path, validation_error = validate_pdf_path(local_pdf_path)
    if validation_error:
        return {
            "ok": False,
            "code": "invalid_file",
            "error": validation_error,
        }

    try:
        object_key = object_key_for_pdf(path, object_prefix=object_prefix)
        public_url = get_public_url(object_key)

        if object_exists(object_key):
            return {
                "ok": False,
                "code": "duplicate_object",
                "error": "PDF already exists in Cloudflare R2.",
                "object_key": object_key,
                "public_url": public_url,
            }

        values = config_values()
        r2_client().upload_file(
            str(path),
            values["bucket_name"],
            object_key,
            ExtraArgs={
                "ContentType": "application/pdf",
            },
        )

        return {
            "ok": True,
            "object_key": object_key,
            "public_url": public_url,
            "bucket": values["bucket_name"],
        }
    except CloudflareR2StorageError as exc:
        code = "missing_env" if missing_env_vars() else "upload_failed"
        return {
            "ok": False,
            "code": code,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": "upload_failed",
            "error": f"Cloudflare R2 upload failed: {exc}",
        }


def delete_pdf(object_key):
    try:
        key = validate_object_key(object_key)
        values = config_values()
        r2_client().delete_object(Bucket=values["bucket_name"], Key=key)

        return {
            "ok": True,
            "object_key": key,
            "public_url": get_public_url(key),
        }
    except CloudflareR2StorageError as exc:
        code = "missing_env" if missing_env_vars() else "delete_failed"
        return {
            "ok": False,
            "code": code,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": "delete_failed",
            "error": f"Cloudflare R2 delete failed: {exc}",
        }
