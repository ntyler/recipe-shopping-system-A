"""Private, workspace-scoped storage for meal photos.

The browser-facing Nutrition APIs should persist only the opaque token returned
by :func:`stage_meal_photo`.  Paths are deliberately absent from public
metadata.  A token is resolved against the *current* authenticated workspace,
so possession of a token from another account is not storage authority.

Uploads are bounded before they are decoded, verified with Pillow, and then
normalized through the recipe vision pipeline.  Only the normalized JPEG is
kept.  Staged media can be supplied to meal analysis and is moved to the
private committed directory only after a reviewed meal is saved.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from flask import has_request_context

from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import storage_service
from PushShoppingList.services.file_lock_service import workspace_write_lock


DEFAULT_MAX_RAW_BYTES = 15 * 1024 * 1024
ABSOLUTE_MAX_RAW_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_NORMALIZED_BYTES = 4 * 1024 * 1024
ABSOLUTE_MAX_NORMALIZED_BYTES = 12 * 1024 * 1024
DEFAULT_MAX_PIXELS = 40_000_000
ABSOLUTE_MAX_PIXELS = 80_000_000
DEFAULT_MAX_DIMENSION = 12_000
ABSOLUTE_MAX_DIMENSION = 20_000
DEFAULT_STAGE_TTL_SECONDS = 24 * 60 * 60
ABSOLUTE_MAX_STAGE_TTL_SECONDS = 30 * 24 * 60 * 60

MAX_RAW_BYTES_ENV = "SHOPPING_APP_NUTRITION_PHOTO_MAX_BYTES"
MAX_NORMALIZED_BYTES_ENV = "SHOPPING_APP_NUTRITION_PHOTO_MAX_NORMALIZED_BYTES"
MAX_PIXELS_ENV = "SHOPPING_APP_NUTRITION_PHOTO_MAX_PIXELS"
MAX_DIMENSION_ENV = "SHOPPING_APP_NUTRITION_PHOTO_MAX_DIMENSION"
STAGE_TTL_SECONDS_ENV = "SHOPPING_APP_NUTRITION_PHOTO_STAGE_TTL_SECONDS"

MEDIA_DIRECTORY = ("nutrition", "meal_media")
STAGING_DIRECTORY = "staging"
COMMITTED_DIRECTORY = "meals"
MEDIA_MIME_TYPE = "image/jpeg"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
_MEAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
    "image/tif": "image/tiff",
}
_ALLOWED_MIME_TYPES = (
    set(recipe_extract_service.VISION_SUPPORTED_IMAGE_MIME_TYPES)
    | set(recipe_extract_service.VISION_CONVERTIBLE_IMAGE_MIME_TYPES)
    | set(_MIME_ALIASES)
)
_ALLOWED_SUFFIXES = (
    set(recipe_extract_service.VISION_SUPPORTED_IMAGE_SUFFIXES)
    | set(recipe_extract_service.VISION_CONVERTIBLE_IMAGE_SUFFIXES)
)
_FORMAT_SUFFIXES = {
    "JPEG": {".jpg", ".jpeg"},
    "PNG": {".png"},
    "WEBP": {".webp"},
    "GIF": {".gif"},
    "BMP": {".bmp"},
    "TIFF": {".tif", ".tiff"},
    "AVIF": {".avif"},
    "HEIF": {".heic", ".heif"},
    "HEIC": {".heic", ".heif"},
    "MPO": {".mpo"},
}
_FORMAT_MIME_TYPES = {
    "JPEG": {"image/jpeg"},
    "PNG": {"image/png"},
    "WEBP": {"image/webp"},
    "GIF": {"image/gif"},
    "BMP": {"image/bmp", "image/x-ms-bmp"},
    "TIFF": {"image/tiff"},
    "AVIF": {"image/avif"},
    "HEIF": {
        "image/heic",
        "image/heif",
        "image/heic-sequence",
        "image/heif-sequence",
    },
    "HEIC": {
        "image/heic",
        "image/heif",
        "image/heic-sequence",
        "image/heif-sequence",
    },
    "MPO": {"image/mpo"},
}
_PUBLIC_METADATA_FIELDS = (
    "token",
    "photo_token",
    "photo_id",
    "media_id",
    "status",
    "mime_type",
    "size_bytes",
    "width",
    "height",
    "original_width",
    "original_height",
    "created_at",
    "committed_at",
)


class NutritionPhotoError(ValueError):
    """Base error with a stable API-facing code and HTTP status hint."""

    def __init__(self, message, *, code="MEAL_PHOTO_ERROR", status=400):
        super().__init__(message)
        self.code = str(code)
        self.status = int(status)
        self.field = "photo"


class NutritionPhotoValidationError(NutritionPhotoError):
    """The uploaded file or supplied token is invalid."""


class NutritionPhotoAuthorizationError(NutritionPhotoError):
    """There is no authenticated workspace for this operation."""

    def __init__(self, message="Sign in before uploading a meal photo."):
        super().__init__(message, code="MEAL_PHOTO_WORKSPACE_REQUIRED", status=401)


class NutritionPhotoNotFoundError(NutritionPhotoError):
    """A token does not name media in the active workspace."""

    def __init__(self, message="Meal photo not found."):
        super().__init__(message, code="MEAL_PHOTO_NOT_FOUND", status=404)


def _configured_limit(name, default, ceiling, *, minimum=1):
    raw = str(os.getenv(name, "") or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except (TypeError, ValueError):
        value = int(default)
    return min(max(int(minimum), value), int(ceiling))


def max_raw_bytes():
    return _configured_limit(
        MAX_RAW_BYTES_ENV, DEFAULT_MAX_RAW_BYTES, ABSOLUTE_MAX_RAW_BYTES
    )


def max_normalized_bytes():
    return _configured_limit(
        MAX_NORMALIZED_BYTES_ENV,
        DEFAULT_MAX_NORMALIZED_BYTES,
        ABSOLUTE_MAX_NORMALIZED_BYTES,
    )


def max_pixels():
    return _configured_limit(MAX_PIXELS_ENV, DEFAULT_MAX_PIXELS, ABSOLUTE_MAX_PIXELS)


def max_dimension():
    return _configured_limit(
        MAX_DIMENSION_ENV, DEFAULT_MAX_DIMENSION, ABSOLUTE_MAX_DIMENSION
    )


def stage_ttl_seconds():
    return _configured_limit(
        STAGE_TTL_SECONDS_ENV,
        DEFAULT_STAGE_TTL_SECONDS,
        ABSOLUTE_MAX_STAGE_TTL_SECONDS,
        minimum=60,
    )


def _utc_iso(now=None):
    moment = now or datetime.now(timezone.utc)
    if not isinstance(moment, datetime):
        raise TypeError("now must be a datetime value.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (
        moment.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _timestamp_seconds(value, fallback):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return float(fallback)


def _workspace_root():
    # storage_service intentionally falls back to the package directory outside
    # a request.  Private upload storage must fail closed instead.
    if not has_request_context():
        raise NutritionPhotoAuthorizationError()
    user_id = storage_service.active_user_id()
    guest_id = storage_service.active_guest_session_id()
    if not user_id and not guest_id:
        raise NutritionPhotoAuthorizationError()
    return Path(storage_service.workspace_data_root()).resolve()


def _media_root():
    workspace = _workspace_root()
    root = workspace
    for part in MEDIA_DIRECTORY:
        candidate = root / part
        if candidate.is_symlink():
            raise NutritionPhotoAuthorizationError(
                "Meal photo storage is outside the active workspace."
            )
        candidate.mkdir(exist_ok=True)
        resolved = candidate.resolve()
        if resolved.parent != root or not resolved.is_dir():
            raise NutritionPhotoAuthorizationError(
                "Meal photo storage is outside the active workspace."
            )
        root = resolved
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve()


def _directory(status):
    name = STAGING_DIRECTORY if status == "staged" else COMMITTED_DIRECTORY
    media_root = _media_root()
    candidate = media_root / name
    if candidate.is_symlink():
        raise NutritionPhotoAuthorizationError(
            "Meal photo storage is outside the active workspace."
        )
    candidate.mkdir(exist_ok=True)
    target = candidate.resolve()
    if target.parent != media_root:
        raise NutritionPhotoAuthorizationError(
            "Meal photo storage is outside the active workspace."
        )
    try:
        target.chmod(0o700)
    except OSError:
        pass
    return target.resolve()


def _normalized_token(token):
    value = str(token or "").strip()
    if not _TOKEN_RE.fullmatch(value):
        raise NutritionPhotoValidationError(
            "Meal photo token is invalid.", code="INVALID_MEAL_PHOTO_TOKEN"
        )
    return value


def _paths(token, status):
    token = _normalized_token(token)
    root = _directory(status)
    image_path = root / f"{token}.jpg"
    metadata_path = root / f"{token}.json"
    # The strict token grammar should make traversal impossible.  Keep an
    # independent resolved-parent check so later token changes fail safely.
    if image_path.parent.resolve() != root or metadata_path.parent.resolve() != root:
        raise NutritionPhotoValidationError(
            "Meal photo token is invalid.", code="INVALID_MEAL_PHOTO_TOKEN"
        )
    return image_path, metadata_path


def _safe_existing_file(path, root):
    if Path(path).is_symlink():
        return None
    try:
        resolved = Path(path).resolve(strict=True)
        expected_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if resolved.parent != expected_root or not resolved.is_file():
        return None
    return resolved


def _metadata_for(token, status, *, required=True):
    image_path, metadata_path = _paths(token, status)
    root = image_path.parent
    safe_image = _safe_existing_file(image_path, root)
    safe_metadata = _safe_existing_file(metadata_path, root)
    if safe_image is None or safe_metadata is None:
        if required:
            raise NutritionPhotoNotFoundError()
        return None, None
    try:
        metadata = json.loads(safe_metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        if required:
            raise NutritionPhotoNotFoundError()
        return None, None
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("token") != token
        or metadata.get("status") != status
        or metadata.get("mime_type") != MEDIA_MIME_TYPE
    ):
        if required:
            raise NutritionPhotoNotFoundError()
        return None, None
    return safe_image, dict(metadata)


def _public_metadata(metadata):
    return {
        key: metadata[key]
        for key in _PUBLIC_METADATA_FIELDS
        if key in metadata and metadata[key] not in (None, "")
    }


def _filename_and_mime(upload, filename, mime_type):
    resolved_filename = str(filename or getattr(upload, "filename", "") or "").strip()
    if "\x00" in resolved_filename:
        raise NutritionPhotoValidationError(
            "Choose a valid meal photo.", code="INVALID_MEAL_PHOTO_NAME"
        )
    # Only inspect the basename; a client-supplied name is never used as a path.
    basename = resolved_filename.replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(basename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise NutritionPhotoValidationError(
            "Choose a JPEG, PNG, WebP, GIF, HEIC, HEIF, BMP, TIFF, MPO, or AVIF meal photo.",
            code="UNSUPPORTED_MEAL_PHOTO_SUFFIX",
        )

    resolved_mime = str(
        mime_type
        or getattr(upload, "mimetype", "")
        or getattr(upload, "content_type", "")
        or ""
    ).split(";", 1)[0].strip().lower()
    resolved_mime = _MIME_ALIASES.get(resolved_mime, resolved_mime)
    if resolved_mime not in _GENERIC_MIME_TYPES and resolved_mime not in _ALLOWED_MIME_TYPES:
        raise NutritionPhotoValidationError(
            "The selected file is not a supported meal photo.",
            code="UNSUPPORTED_MEAL_PHOTO_TYPE",
        )
    return suffix, resolved_mime


def _read_bounded(upload, limit):
    if isinstance(upload, (bytes, bytearray, memoryview)):
        raw = bytes(upload)
        if len(raw) > limit:
            raise NutritionPhotoValidationError(
                f"Meal photos must be {limit // (1024 * 1024) or 1} MB or smaller.",
                code="MEAL_PHOTO_TOO_LARGE",
                status=413,
            )
        if not raw:
            raise NutritionPhotoValidationError(
                "Choose a meal photo before continuing.", code="EMPTY_MEAL_PHOTO"
            )
        return raw

    content_length = getattr(upload, "content_length", None)
    try:
        if content_length is not None and int(content_length) > limit:
            raise NutritionPhotoValidationError(
                f"Meal photos must be {limit // (1024 * 1024) or 1} MB or smaller.",
                code="MEAL_PHOTO_TOO_LARGE",
                status=413,
            )
    except (TypeError, ValueError):
        pass

    stream = getattr(upload, "stream", upload)
    if stream is None or not callable(getattr(stream, "read", None)):
        raise NutritionPhotoValidationError(
            "Choose a meal photo before continuing.", code="MEAL_PHOTO_REQUIRED"
        )

    chunks = []
    total = 0
    while total <= limit:
        try:
            chunk = stream.read(min(64 * 1024, limit + 1 - total))
        except (OSError, ValueError) as exc:
            raise NutritionPhotoValidationError(
                "The selected meal photo could not be read.",
                code="MEAL_PHOTO_UNREADABLE",
            ) from exc
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise NutritionPhotoValidationError(
                "The selected meal photo could not be read.",
                code="MEAL_PHOTO_UNREADABLE",
            )
        chunks.append(bytes(chunk))
        total += len(chunk)
    if total > limit:
        raise NutritionPhotoValidationError(
            f"Meal photos must be {limit // (1024 * 1024) or 1} MB or smaller.",
            code="MEAL_PHOTO_TOO_LARGE",
            status=413,
        )
    raw = b"".join(chunks)
    if not raw:
        raise NutritionPhotoValidationError(
            "Choose a meal photo before continuing.", code="EMPTY_MEAL_PHOTO"
        )
    return raw


def _decoded_image_details(raw, suffix, declared_mime):
    try:
        recipe_extract_service.ensure_heif_image_support()
        from PIL import Image
    except Exception as exc:
        raise NutritionPhotoValidationError(
            "Meal photo validation is temporarily unavailable.",
            code="MEAL_PHOTO_VALIDATION_UNAVAILABLE",
            status=503,
        ) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                image_format = str(image.format or "").upper()
                width, height = (int(image.size[0]), int(image.size[1]))
                if width <= 0 or height <= 0:
                    raise ValueError("image dimensions are empty")
                if width > max_dimension() or height > max_dimension():
                    raise NutritionPhotoValidationError(
                        f"Meal photos may be at most {max_dimension()} pixels on either side.",
                        code="MEAL_PHOTO_DIMENSIONS_TOO_LARGE",
                        status=413,
                    )
                if width * height > max_pixels():
                    raise NutritionPhotoValidationError(
                        "This meal photo has too many pixels to process safely.",
                        code="MEAL_PHOTO_PIXELS_TOO_LARGE",
                        status=413,
                    )
                image.verify()
            # verify() checks structure; load() catches truncated pixel data.
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
    except NutritionPhotoValidationError:
        raise
    except Exception as exc:
        message = recipe_extract_service.unsupported_phone_image_message(declared_mime)
        if suffix not in {".heic", ".heif"}:
            message = "The selected meal photo is damaged or unreadable."
        raise NutritionPhotoValidationError(
            message, code="MEAL_PHOTO_UNREADABLE"
        ) from exc

    allowed_suffixes = _FORMAT_SUFFIXES.get(image_format)
    if not allowed_suffixes or suffix not in allowed_suffixes:
        raise NutritionPhotoValidationError(
            "The meal photo contents do not match its file extension.",
            code="MEAL_PHOTO_SUFFIX_MISMATCH",
        )
    allowed_mimes = _FORMAT_MIME_TYPES.get(image_format, set())
    if declared_mime not in _GENERIC_MIME_TYPES and declared_mime not in allowed_mimes:
        raise NutritionPhotoValidationError(
            "The meal photo contents do not match its file type.",
            code="MEAL_PHOTO_TYPE_MISMATCH",
        )
    return {
        "format": image_format,
        "width": width,
        "height": height,
    }


def _verify_normalized_jpeg(raw):
    if not raw or len(raw) > max_normalized_bytes():
        raise NutritionPhotoValidationError(
            "The normalized meal photo is too large to store safely.",
            code="NORMALIZED_MEAL_PHOTO_TOO_LARGE",
            status=413,
        )
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            if str(image.format or "").upper() != "JPEG":
                raise ValueError("normalizer did not return JPEG")
            width, height = int(image.size[0]), int(image.size[1])
            image.load()
    except Exception as exc:
        raise NutritionPhotoValidationError(
            "The meal photo could not be prepared for review.",
            code="MEAL_PHOTO_NORMALIZATION_FAILED",
            status=422,
        ) from exc
    return width, height


def _atomic_write_bytes(path, raw):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(str(temporary), str(destination))
        try:
            destination.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _new_token(status):
    for _attempt in range(10):
        token = secrets.token_urlsafe(32)
        image_path, metadata_path = _paths(token, status)
        if not image_path.exists() and not metadata_path.exists():
            return token
    raise RuntimeError("Could not allocate a meal photo token.")


def stage_meal_photo(upload, *, filename="", mime_type="", now=None):
    """Validate, normalize, and privately stage one uploaded meal photo.

    ``upload`` may be a Werkzeug ``FileStorage``, a binary file-like object, or
    bytes.  Bytes require explicit ``filename`` and normally ``mime_type``.
    The returned mapping is safe to serialize in an API response.
    """

    _workspace_root()  # Authenticate before consuming an upload stream.
    suffix, declared_mime = _filename_and_mime(upload, filename, mime_type)
    raw = _read_bounded(upload, max_raw_bytes())
    decoded = _decoded_image_details(raw, suffix, declared_mime)

    staging_root = _directory("staged")
    raw_path = staging_root / f".raw-{secrets.token_hex(16)}{suffix}"
    try:
        _atomic_write_bytes(raw_path, raw)
        try:
            normalized, normalized_mime, _details = (
                recipe_extract_service.normalize_image_bytes_for_openai(
                    raw_path, declared_mime
                )
            )
        except Exception as exc:
            raise NutritionPhotoValidationError(
                "The meal photo could not be prepared for review.",
                code="MEAL_PHOTO_NORMALIZATION_FAILED",
                status=422,
            ) from exc
    finally:
        raw_path.unlink(missing_ok=True)

    if normalized_mime != MEDIA_MIME_TYPE:
        raise NutritionPhotoValidationError(
            "The meal photo could not be prepared for review.",
            code="MEAL_PHOTO_NORMALIZATION_FAILED",
            status=422,
        )
    width, height = _verify_normalized_jpeg(normalized)
    created_at = _utc_iso(now)

    with workspace_write_lock("nutrition-meal-media"):
        token = _new_token("staged")
        image_path, metadata_path = _paths(token, "staged")
        metadata = {
            "schema_version": 1,
            "token": token,
            "photo_token": token,
            "photo_id": token,
            "media_id": token,
            "status": "staged",
            "mime_type": MEDIA_MIME_TYPE,
            "size_bytes": len(normalized),
            "width": width,
            "height": height,
            "original_format": decoded["format"],
            "original_mime_type": declared_mime or "application/octet-stream",
            "original_size_bytes": len(raw),
            "original_width": decoded["width"],
            "original_height": decoded["height"],
            "created_at": created_at,
        }
        try:
            _atomic_write_bytes(image_path, normalized)
            durable_runtime.atomic_write_json(metadata_path, metadata)
            try:
                metadata_path.chmod(0o600)
            except OSError:
                pass
        except Exception:
            image_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            raise
    return _public_metadata(metadata)


def resolve_staged_photo(token):
    """Resolve a staged token for trusted server-side analysis only."""

    image_path, _metadata = _metadata_for(
        _normalized_token(token), "staged", required=True
    )
    return image_path


def resolve_meal_photo(token):
    """Resolve a committed token inside the active workspace."""

    image_path, _metadata = _metadata_for(
        _normalized_token(token), "committed", required=True
    )
    return image_path


def get_meal_photo_metadata(token, *, allow_staged=False):
    """Return path-free metadata for a committed photo (or a staged preview)."""

    token = _normalized_token(token)
    _path, metadata = _metadata_for(token, "committed", required=False)
    if metadata is None and allow_staged:
        _path, metadata = _metadata_for(token, "staged", required=False)
    if metadata is None:
        raise NutritionPhotoNotFoundError()
    return _public_metadata(metadata)


def read_meal_photo(token, *, allow_staged=False):
    """Return normalized bytes and safe metadata for a trusted serving route."""

    token = _normalized_token(token)
    path, metadata = _metadata_for(token, "committed", required=False)
    if path is None and allow_staged:
        path, metadata = _metadata_for(token, "staged", required=False)
    if path is None or metadata is None:
        raise NutritionPhotoNotFoundError()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NutritionPhotoNotFoundError() from exc
    if len(raw) != int(metadata.get("size_bytes") or -1):
        raise NutritionPhotoNotFoundError()
    return raw, _public_metadata(metadata)


def commit_meal_photo(token, *, meal_id="", now=None):
    """Move a reviewed staged photo into private meal media storage."""

    token = _normalized_token(token)
    normalized_meal_id = str(meal_id or "").strip()
    if normalized_meal_id and not _MEAL_ID_RE.fullmatch(normalized_meal_id):
        raise NutritionPhotoValidationError(
            "Meal id is invalid.", code="INVALID_MEAL_ID"
        )

    with workspace_write_lock("nutrition-meal-media"):
        committed_image, committed_metadata = _metadata_for(
            token, "committed", required=False
        )
        source_image, metadata = _metadata_for(token, "staged", required=False)
        if committed_image is not None and committed_metadata is not None:
            recorded_meal_id = str(committed_metadata.get("meal_id") or "")
            if (
                normalized_meal_id
                and recorded_meal_id
                and normalized_meal_id != recorded_meal_id
            ):
                raise NutritionPhotoValidationError(
                    "This meal photo belongs to another meal.",
                    code="MEAL_PHOTO_ALREADY_COMMITTED",
                    status=409,
                )
            return _public_metadata(committed_metadata)
        if source_image is None or metadata is None:
            raise NutritionPhotoNotFoundError()
        _source_image, source_metadata = _paths(token, "staged")
        destination_image, destination_metadata = _paths(token, "committed")
        if destination_image.exists() or destination_metadata.exists():
            raise NutritionPhotoValidationError(
                "This meal photo has already been committed.",
                code="MEAL_PHOTO_ALREADY_COMMITTED",
                status=409,
            )
        committed = dict(metadata)
        committed["status"] = "committed"
        committed["committed_at"] = _utc_iso(now)
        if normalized_meal_id:
            committed["meal_id"] = normalized_meal_id
        try:
            os.replace(str(source_image), str(destination_image))
            try:
                destination_image.chmod(0o600)
            except OSError:
                pass
            durable_runtime.atomic_write_json(destination_metadata, committed)
            try:
                destination_metadata.chmod(0o600)
            except OSError:
                pass
        except Exception:
            if destination_image.exists() and not source_image.exists():
                try:
                    os.replace(str(destination_image), str(source_image))
                except OSError:
                    pass
            destination_metadata.unlink(missing_ok=True)
            raise
        try:
            source_metadata.unlink(missing_ok=True)
        except OSError:
            pass
    return _public_metadata(committed)


def delete_meal_photo(token, *, include_staged=True):
    """Delete committed media, optionally falling back to an abandoned stage."""

    token = _normalized_token(token)
    statuses = ["committed"]
    if include_staged:
        statuses.append("staged")
    with workspace_write_lock("nutrition-meal-media"):
        for status in statuses:
            image_path, metadata_path = _paths(token, status)
            if not image_path.exists() and not metadata_path.exists():
                continue
            image_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            return True
    return False


def cleanup_staged_meal_photos(*, older_than_seconds=None, now=None):
    """Remove abandoned staged files and incomplete temporary artifacts."""

    ttl = stage_ttl_seconds() if older_than_seconds is None else float(older_than_seconds)
    if ttl < 0:
        raise ValueError("older_than_seconds must be zero or more.")
    if now is None:
        reference = time.time()
    elif isinstance(now, datetime):
        moment = now
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        reference = moment.timestamp()
    else:
        reference = float(now)
    root = _directory("staged")
    removed_tokens = set()
    removed_artifacts = 0

    with workspace_write_lock("nutrition-meal-media"):
        for metadata_path in list(root.glob("*.json")):
            token = metadata_path.stem
            if not _TOKEN_RE.fullmatch(token):
                continue
            image_path, expected_metadata = _paths(token, "staged")
            if expected_metadata != metadata_path:
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                metadata = {}
            try:
                fallback = metadata_path.stat().st_mtime
            except OSError:
                fallback = reference
            created = _timestamp_seconds(metadata.get("created_at"), fallback)
            if reference - created < ttl:
                continue
            image_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            removed_tokens.add(token)

        # Failed writes never become valid tokens.  Clear only old artifacts
        # with the exact private temp prefixes created by this module.
        for pattern in (".raw-*", ".*.tmp"):
            for artifact in list(root.glob(pattern)):
                try:
                    age = reference - artifact.stat().st_mtime
                except OSError:
                    continue
                if age >= ttl and artifact.is_file():
                    artifact.unlink(missing_ok=True)
                    removed_artifacts += 1

        for image_path in list(root.glob("*.jpg")):
            token = image_path.stem
            if not _TOKEN_RE.fullmatch(token):
                continue
            _expected_image, metadata_path = _paths(token, "staged")
            if metadata_path.exists():
                continue
            try:
                age = reference - image_path.stat().st_mtime
            except OSError:
                continue
            if age >= ttl and image_path.is_file() and not image_path.is_symlink():
                image_path.unlink(missing_ok=True)
                removed_artifacts += 1

    return {
        "removed_count": len(removed_tokens),
        "removed_tokens": sorted(removed_tokens),
        "removed_artifact_count": removed_artifacts,
    }


__all__ = [
    "ABSOLUTE_MAX_DIMENSION",
    "ABSOLUTE_MAX_NORMALIZED_BYTES",
    "ABSOLUTE_MAX_PIXELS",
    "ABSOLUTE_MAX_RAW_BYTES",
    "NutritionPhotoAuthorizationError",
    "NutritionPhotoError",
    "NutritionPhotoNotFoundError",
    "NutritionPhotoValidationError",
    "cleanup_staged_meal_photos",
    "commit_meal_photo",
    "delete_meal_photo",
    "get_meal_photo_metadata",
    "max_dimension",
    "max_normalized_bytes",
    "max_pixels",
    "max_raw_bytes",
    "read_meal_photo",
    "resolve_meal_photo",
    "resolve_staged_photo",
    "stage_meal_photo",
    "stage_ttl_seconds",
]
