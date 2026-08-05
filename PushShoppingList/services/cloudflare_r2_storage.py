import hashlib
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


def client_supports_conditional_put(client):
    """Detect botocore models old enough to silently lack safe PUT parameters."""
    try:
        members = client.meta.service_model.operation_model("PutObject").input_shape.members
    except AttributeError:
        # Lightweight test clients do not expose botocore's model metadata.
        return True
    except Exception:
        return False
    return "IfMatch" in members and "IfNoneMatch" in members


def validate_pdf_path(local_pdf_path):
    path = Path(os.fspath(local_pdf_path)).expanduser()

    if path.name != Path(path.name).name or not path.name:
        return None, "Invalid PDF filename."

    if path.suffix.lower() != ".pdf":
        return None, "Only PDF files can be uploaded."

    if not path.exists() or not path.is_file():
        return None, "PDF file was not found."

    return path, ""


def pdf_file_sha256(local_pdf_path):
    """Return the SHA-256 for a local PDF without loading it all into memory."""
    digest = hashlib.sha256()
    with Path(local_pdf_path).open("rb") as pdf_file:
        for chunk in iter(lambda: pdf_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def validate_pdf_object_key(object_key):
    key = str(object_key or "").strip().replace("\\", "/")

    if not key or key.startswith("/") or ".." in key.split("/"):
        raise CloudflareR2StorageError("Invalid Cloudflare R2 object key.")

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


def r2_error_is_not_found(exc):
    response = getattr(exc, "response", {}) or {}
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = str(error.get("Code") or getattr(exc, "code", "") or "")
    status = (
        response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(response, dict)
        else None
    )
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


def r2_error_is_write_precondition_failed(exc):
    response = getattr(exc, "response", {}) or {}
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = str(error.get("Code") or getattr(exc, "code", "") or "")
    status = (
        response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(response, dict)
        else None
    )
    return code in {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"} or status in {
        409,
        412,
    }


def head_pdf_object(object_key):
    """Fetch lightweight metadata for a PDF object without downloading its body."""
    try:
        key = validate_pdf_object_key(object_key)
        values = config_values()
        response = r2_client().head_object(Bucket=values["bucket_name"], Key=key) or {}
        custom_metadata = response.get("Metadata") if isinstance(response.get("Metadata"), dict) else {}

        return {
            "ok": True,
            "success": True,
            "exists": True,
            "bucket": values["bucket_name"],
            "object_key": key,
            "public_url": get_public_url_for_object_key(key),
            "size": int(response.get("ContentLength") or 0),
            "size_bytes": int(response.get("ContentLength") or 0),
            "etag": str(response.get("ETag") or "").strip('"'),
            "last_modified": format_r2_last_modified(response.get("LastModified")),
            "uploaded_at": format_r2_last_modified(response.get("LastModified")),
            "content_type": str(response.get("ContentType") or "").strip(),
            "sha256": str(custom_metadata.get("sha256") or "").strip().lower(),
            "semantically_validated": truthy_env(custom_metadata.get("semantically-validated")),
            "validation_version": str(
                custom_metadata.get("validation-version") or ""
            ).strip(),
            "metadata": custom_metadata,
        }
    except CloudflareR2StorageError as exc:
        code = "missing_env" if missing_env_vars() else "head_failed"
        return {
            "ok": False,
            "success": False,
            "exists": False,
            "code": code,
            "error": str(exc),
            "object_key": str(object_key or ""),
        }
    except Exception as exc:
        if r2_error_is_not_found(exc):
            key = str(object_key or "").strip().replace("\\", "/")
            return {
                "ok": True,
                "success": True,
                "exists": False,
                "code": "not_found",
                "object_key": key,
            }
        return {
            "ok": False,
            "success": False,
            "exists": False,
            "code": "head_failed",
            "error": f"Unable to check Cloudflare R2 object: {exc}",
            "object_key": str(object_key or ""),
        }


def read_pdf_object_bytes(object_key, max_bytes=None, *, expected_etag=None):
    """Download a PDF object explicitly (used by repair/audit tooling, not link opens)."""
    try:
        key = validate_pdf_object_key(object_key)
        values = config_values()
        request_args = {"Bucket": values["bucket_name"], "Key": key}
        expected_etag = str(expected_etag or "").strip().strip('"')
        if expected_etag:
            request_args["IfMatch"] = expected_etag
        if max_bytes is not None:
            byte_limit = int(max_bytes)
            if byte_limit <= 0:
                raise CloudflareR2StorageError("max_bytes must be greater than zero.")
            request_args["Range"] = f"bytes=0-{byte_limit - 1}"

        response = r2_client().get_object(**request_args) or {}
        body = response.get("Body")
        data = body.read() if hasattr(body, "read") else bytes(body or b"")
        return {
            "ok": True,
            "success": True,
            "object_key": key,
            "public_url": get_public_url_for_object_key(key),
            "bytes": data,
            "size_bytes": len(data),
            "etag": str(response.get("ETag") or "").strip('"'),
            "content_range": str(response.get("ContentRange") or ""),
        }
    except CloudflareR2StorageError as exc:
        code = "missing_env" if missing_env_vars() else "download_failed"
        return {
            "ok": False,
            "success": False,
            "code": code,
            "error": str(exc),
            "object_key": str(object_key or ""),
        }
    except Exception as exc:
        if r2_error_is_write_precondition_failed(exc):
            code = "read_precondition_failed"
        else:
            code = "not_found" if r2_error_is_not_found(exc) else "download_failed"
        return {
            "ok": False,
            "success": False,
            "code": code,
            "error": (
                "Cloudflare R2 PDF object was not found."
                if code == "not_found"
                else "Cloudflare R2 PDF changed before its validated read could complete."
                if code == "read_precondition_failed"
                else f"Cloudflare R2 download failed: {exc}"
            ),
            "object_key": str(object_key or ""),
        }


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
    result = head_pdf_object(key)
    if not result.get("ok"):
        raise CloudflareR2StorageError(
            result.get("error") or "Unable to check Cloudflare R2 object."
        )
    return bool(result.get("exists"))


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


def upload_pdf(
    local_pdf_path,
    object_prefix=PDF_OBJECT_PREFIX,
    *,
    object_key=None,
    overwrite=False,
    expected_etag=None,
    validated=False,
    validation=None,
):
    """Upload a PDF and verify the resulting R2 object.

    Existing objects remain protected by default. Callers may overwrite only by
    explicitly opting in and asserting that the exact local artifact passed
    semantic validation. When a validation result supplies a SHA-256, it must
    match the bytes uploaded.
    """
    path, validation_error = validate_pdf_path(local_pdf_path)
    if validation_error:
        return {
            "ok": False,
            "code": "invalid_file",
            "error": validation_error,
        }

    validation = validation if isinstance(validation, dict) else {}
    validation_ok = bool(
        validated
        and validation.get("ok")
        and validation.get("semantic_validation_required") is True
        and str(validation.get("validation_version") or "").strip()
    )
    if overwrite and not validation_ok:
        return {
            "ok": False,
            "success": False,
            "code": "overwrite_requires_validation",
            "error": (
                "Cloudflare R2 overwrite requires an explicit successful validation result."
            ),
        }

    try:
        resolved_object_key = (
            validate_object_key(object_key)
            if str(object_key or "").strip()
            else object_key_for_pdf(path, object_prefix=object_prefix)
        )
        public_url = get_public_url(resolved_object_key)
        local_sha256 = pdf_file_sha256(path)
        validation_sha256 = str(
            validation.get("sha256")
            or validation.get("content_sha256")
            or ""
        ).strip().lower()

        if validation and not validation.get("ok"):
            return {
                "ok": False,
                "success": False,
                "code": "invalid_pdf",
                "error": validation.get("error") or "The local PDF did not pass validation.",
                "object_key": resolved_object_key,
                "public_url": public_url,
            }

        if validation_sha256 and validation_sha256 != local_sha256:
            return {
                "ok": False,
                "success": False,
                "code": "validation_mismatch",
                "error": "The local PDF changed after validation; upload was refused.",
                "object_key": resolved_object_key,
                "public_url": public_url,
                "sha256": local_sha256,
            }

        if overwrite and not validation_sha256:
            return {
                "ok": False,
                "success": False,
                "code": "overwrite_requires_validation_hash",
                "error": "Cloudflare R2 overwrite requires the validated PDF SHA-256.",
                "object_key": resolved_object_key,
                "public_url": public_url,
            }

        values = config_values()
        object_already_exists = bool(overwrite)
        conditional_etag = str(expected_etag or "").strip().strip('"')
        if overwrite and not conditional_etag:
            before_write = head_pdf_object(resolved_object_key)
            if not before_write.get("ok"):
                return {
                    "ok": False,
                    "success": False,
                    "code": "overwrite_precondition_check_failed",
                    "error": before_write.get("error") or "Unable to verify the overwrite target.",
                    "object_key": resolved_object_key,
                    "public_url": public_url,
                }
            if not before_write.get("exists"):
                return {
                    "ok": False,
                    "success": False,
                    "code": "overwrite_target_missing",
                    "error": "The requested Cloudflare R2 overwrite target no longer exists.",
                    "object_key": resolved_object_key,
                    "public_url": public_url,
                }
            conditional_etag = str(before_write.get("etag") or "").strip().strip('"')
        if overwrite and not conditional_etag:
            return {
                "ok": False,
                "success": False,
                "code": "overwrite_requires_etag",
                "error": "Cloudflare R2 overwrite requires the current target ETag.",
                "object_key": resolved_object_key,
                "public_url": public_url,
            }

        object_metadata = {"sha256": local_sha256}
        if validation_ok:
            object_metadata["semantically-validated"] = "true"
            validation_version = str(validation.get("validation_version") or "").strip()
            if validation_version:
                object_metadata["validation-version"] = validation_version

        put_args = {
            "Bucket": values["bucket_name"],
            "Key": resolved_object_key,
            "ContentType": "application/pdf",
            "ContentLength": path.stat().st_size,
            "Metadata": object_metadata,
        }
        if overwrite:
            put_args["IfMatch"] = conditional_etag
        else:
            put_args["IfNoneMatch"] = "*"

        client = r2_client()
        if not client_supports_conditional_put(client):
            return {
                "ok": False,
                "success": False,
                "code": "conditional_upload_unsupported",
                "error": (
                    "The installed boto3/botocore version does not support safe conditional "
                    "PutObject writes. Install requirements.txt (boto3>=1.37.32) before upload."
                ),
                "object_key": resolved_object_key,
                "public_url": public_url,
            }

        try:
            with path.open("rb") as pdf_file:
                client.put_object(Body=pdf_file, **put_args)
        except Exception as exc:
            if r2_error_is_write_precondition_failed(exc):
                return {
                    "ok": False,
                    "success": False,
                    "code": (
                        "overwrite_precondition_failed" if overwrite else "duplicate_object"
                    ),
                    "error": (
                        "The Cloudflare R2 object changed after validation; overwrite was refused."
                        if overwrite
                        else "PDF already exists in Cloudflare R2."
                    ),
                    "object_key": resolved_object_key,
                    "public_url": public_url,
                    "sha256": local_sha256,
                    "size_bytes": path.stat().st_size,
                    "expected_etag": conditional_etag,
                }
            # Once PutObject has started, a transport/client exception cannot
            # prove that R2 rejected the body.  The server may have committed
            # the conditional write before the response was lost, so callers
            # (especially the repair CLI) must reconcile rather than report a
            # definite no-write failure.
            return {
                "ok": False,
                "success": False,
                "code": "upload_outcome_unknown",
                "error": (
                    "Cloudflare R2 PutObject did not return a conclusive result; "
                    f"the remote mutation state is unknown: {exc}"
                ),
                "object_key": resolved_object_key,
                "public_url": public_url,
                "sha256": local_sha256,
                "size_bytes": path.stat().st_size,
                "expected_etag": conditional_etag,
                "remote_write_succeeded": False,
                "remote_repaired": False,
                "remote_mutation_unknown": True,
            }

        remote = head_pdf_object(resolved_object_key)
        local_size = path.stat().st_size
        verification_errors = []
        if not remote.get("ok"):
            verification_errors.append(
                remote.get("error") or "Unable to read the uploaded object metadata."
            )
        elif not remote.get("exists"):
            verification_errors.append("The uploaded object was not found in Cloudflare R2.")
        else:
            if int(remote.get("size_bytes") or 0) != local_size:
                verification_errors.append(
                    "The uploaded object size does not match the validated local PDF."
                )
            if str(remote.get("sha256") or "").strip().lower() != local_sha256:
                verification_errors.append(
                    "The uploaded object SHA-256 metadata does not match the validated local PDF."
                )
            if validation_ok and not remote.get("semantically_validated"):
                verification_errors.append(
                    "The uploaded object is missing its semantic-validation marker."
                )
            validation_version = str(validation.get("validation_version") or "").strip()
            if validation_version and str(remote.get("validation_version") or "").strip() != validation_version:
                verification_errors.append(
                    "The uploaded object validation version does not match the local validation result."
                )

        if verification_errors:
            return {
                "ok": False,
                "success": False,
                "code": "upload_verification_failed",
                "error": " ".join(verification_errors),
                "object_key": resolved_object_key,
                "public_url": public_url,
                "sha256": local_sha256,
                "size_bytes": local_size,
                "remote_metadata": remote,
                "overwritten": bool(overwrite and object_already_exists),
                "expected_etag": conditional_etag,
                "remote_write_succeeded": True,
                "remote_repaired": bool(overwrite),
            }

        return {
            "ok": True,
            "success": True,
            "object_key": resolved_object_key,
            "public_url": public_url,
            "bucket": values["bucket_name"],
            "sha256": local_sha256,
            "size_bytes": local_size,
            "etag": remote.get("etag", ""),
            "uploaded_at": remote.get("uploaded_at", ""),
            "verified": True,
            "semantically_validated": bool(validation_ok),
            "validation_version": str(validation.get("validation_version") or "").strip(),
            "overwritten": bool(overwrite and object_already_exists),
            "expected_etag": conditional_etag,
            "remote_write_succeeded": True,
            "remote_metadata": remote,
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


def delete_pdf_object(object_key):
    try:
        key = validate_pdf_object_key(object_key)
        values = config_values()
        r2_client().delete_object(Bucket=values["bucket_name"], Key=key)

        return {
            "ok": True,
            "object_key": key,
            "public_url": get_public_url_for_object_key(key),
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
