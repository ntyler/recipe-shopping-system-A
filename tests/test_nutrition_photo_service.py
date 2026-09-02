import io
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, g
from PIL import Image
from werkzeug.datastructures import FileStorage

from PushShoppingList.services import nutrition_photo_service as photos
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import storage_service


NOW = datetime(2026, 7, 10, 15, 30, tzinfo=timezone.utc)


def image_bytes(image_format="PNG", *, size=(8, 6), color=(40, 130, 80)):
    output = io.BytesIO()
    Image.new("RGB", size, color=color).save(output, format=image_format)
    return output.getvalue()


def upload(raw, filename="meal.png", mime_type="image/png"):
    return FileStorage(
        stream=io.BytesIO(raw),
        filename=filename,
        content_type=mime_type,
        content_length=len(raw),
    )


@contextmanager
def active_workspace(app, user_id="photo-user", *, guest_id=""):
    with app.test_request_context("/"):
        g.session_identity_validated = True
        g.authenticated_user_id = user_id
        g.authenticated_guest_session_id = guest_id
        yield


@pytest.fixture
def photo_app(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    for name in (
        photos.MAX_RAW_BYTES_ENV,
        photos.MAX_NORMALIZED_BYTES_ENV,
        photos.MAX_PIXELS_ENV,
        photos.MAX_DIMENSION_ENV,
        photos.STAGE_TTL_SECONDS_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    app = Flask(__name__)
    app.secret_key = "nutrition-photo-test"
    return app, tmp_path


def assert_path_free(metadata):
    assert (
        metadata["token"]
        == metadata["photo_token"]
        == metadata["photo_id"]
        == metadata["media_id"]
    )
    assert not any("path" in key.lower() or "url" in key.lower() for key in metadata)
    for value in metadata.values():
        if isinstance(value, str):
            assert "user_data" not in value
            assert "\\" not in value


def test_stage_normalizes_to_private_jpeg_and_returns_only_safe_metadata(photo_app):
    app, tmp_path = photo_app
    raw = image_bytes("PNG", size=(17, 11))

    with active_workspace(app):
        metadata = photos.stage_meal_photo(
            upload(raw, "../../My Breakfast.PNG", "image/png"), now=NOW
        )
        staged_path = photos.resolve_staged_photo(metadata["token"])
        stored, read_metadata = photos.read_meal_photo(
            metadata["token"], allow_staged=True
        )

    assert metadata["status"] == "staged"
    assert metadata["mime_type"] == "image/jpeg"
    assert metadata["size_bytes"] == len(stored)
    assert metadata["width"] == 17
    assert metadata["height"] == 11
    assert metadata["original_width"] == 17
    assert metadata["original_height"] == 11
    assert metadata["created_at"] == "2026-07-10T15:30:00Z"
    assert stored.startswith(b"\xff\xd8")
    assert read_metadata == metadata
    assert staged_path.parent == (
        tmp_path / "users" / "photo-user" / "nutrition" / "meal_media" / "staging"
    ).resolve()
    assert staged_path.name == f"{metadata['token']}.jpg"
    assert not list(staged_path.parent.glob(".raw-*"))
    assert_path_free(metadata)
    sidecar = json.loads(staged_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert "My Breakfast" not in json.dumps(sidecar)
    assert not any("path" in key.lower() or "url" in key.lower() for key in sidecar)


def test_real_heic_upload_uses_existing_heif_and_normalization_pipeline(photo_app):
    pillow_heif = pytest.importorskip("pillow_heif")
    app, _tmp_path = photo_app
    source = Image.new("RGB", (5, 4), color=(220, 80, 30))
    output = io.BytesIO()
    pillow_heif.from_pillow(source).save(output, quality=90)

    with active_workspace(app):
        metadata = photos.stage_meal_photo(
            upload(output.getvalue(), "camera.heic", "image/heic"), now=NOW
        )
        stored, _metadata = photos.read_meal_photo(
            metadata["token"], allow_staged=True
        )

    assert metadata["mime_type"] == "image/jpeg"
    assert metadata["original_width"] == 5
    assert metadata["original_height"] == 4
    assert stored.startswith(b"\xff\xd8")


@pytest.mark.parametrize(
    ("raw", "filename", "mime_type", "expected_code"),
    [
        (b"", "meal.png", "image/png", "EMPTY_MEAL_PHOTO"),
        (image_bytes(), "meal.txt", "image/png", "UNSUPPORTED_MEAL_PHOTO_SUFFIX"),
        (image_bytes(), "meal.png", "text/plain", "UNSUPPORTED_MEAL_PHOTO_TYPE"),
        (image_bytes(), "meal.jpg", "image/png", "MEAL_PHOTO_SUFFIX_MISMATCH"),
        (image_bytes(), "meal.png", "image/jpeg", "MEAL_PHOTO_TYPE_MISMATCH"),
        (b"not an image", "meal.png", "image/png", "MEAL_PHOTO_UNREADABLE"),
    ],
)
def test_stage_rejects_empty_unsupported_mismatched_and_corrupt_uploads(
    photo_app, raw, filename, mime_type, expected_code
):
    app, tmp_path = photo_app
    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.stage_meal_photo(
                upload(raw, filename, mime_type), now=NOW
            )

    assert caught.value.code == expected_code
    media_root = tmp_path / "users" / "photo-user" / "nutrition" / "meal_media"
    assert not list(media_root.rglob("*.jpg")) if media_root.exists() else True


def test_stage_enforces_raw_size_before_decode_and_never_leaves_raw_data(
    photo_app, monkeypatch
):
    app, tmp_path = photo_app
    raw = image_bytes("PNG", size=(10, 10))
    monkeypatch.setenv(photos.MAX_RAW_BYTES_ENV, str(len(raw) - 1))

    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.stage_meal_photo(upload(raw), now=NOW)

    assert caught.value.code == "MEAL_PHOTO_TOO_LARGE"
    assert caught.value.status == 413
    assert not list(tmp_path.rglob(".raw-*"))


def test_stage_accepts_exact_raw_limit_and_generic_binary_mime(photo_app, monkeypatch):
    app, _tmp_path = photo_app
    raw = image_bytes("PNG", size=(4, 4))
    monkeypatch.setenv(photos.MAX_RAW_BYTES_ENV, str(len(raw)))

    with active_workspace(app):
        metadata = photos.stage_meal_photo(
            upload(raw, "meal.png", "application/octet-stream"), now=NOW
        )

    assert metadata["status"] == "staged"


def test_stage_enforces_decoded_pixel_and_dimension_limits(photo_app, monkeypatch):
    app, _tmp_path = photo_app
    raw = image_bytes("PNG", size=(3, 2))
    monkeypatch.setenv(photos.MAX_DIMENSION_ENV, "2")

    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.stage_meal_photo(upload(raw), now=NOW)
    assert caught.value.code == "MEAL_PHOTO_DIMENSIONS_TOO_LARGE"

    monkeypatch.setenv(photos.MAX_DIMENSION_ENV, "10")
    monkeypatch.setenv(photos.MAX_PIXELS_ENV, "5")
    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.stage_meal_photo(upload(raw), now=NOW)
    assert caught.value.code == "MEAL_PHOTO_PIXELS_TOO_LARGE"


def test_normalization_failure_and_output_limit_remove_temporary_raw_file(
    photo_app, monkeypatch
):
    app, tmp_path = photo_app
    raw = image_bytes()

    def fail_normalization(*_args, **_kwargs):
        raise RuntimeError("decoder unavailable")

    monkeypatch.setattr(
        recipe_extract_service,
        "normalize_image_bytes_for_openai",
        fail_normalization,
    )
    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.stage_meal_photo(upload(raw), now=NOW)
    assert caught.value.code == "MEAL_PHOTO_NORMALIZATION_FAILED"
    assert not list(tmp_path.rglob(".raw-*"))

    normalized = image_bytes("JPEG", size=(2, 2))
    monkeypatch.setattr(
        recipe_extract_service,
        "normalize_image_bytes_for_openai",
        lambda *_args, **_kwargs: (normalized, "image/jpeg", {}),
    )
    monkeypatch.setenv(photos.MAX_NORMALIZED_BYTES_ENV, str(len(normalized) - 1))
    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.stage_meal_photo(upload(raw), now=NOW)
    assert caught.value.code == "NORMALIZED_MEAL_PHOTO_TOO_LARGE"
    assert not list(tmp_path.rglob(".raw-*"))


def test_configured_limits_are_positive_and_clamped_to_safe_ceilings(
    photo_app, monkeypatch
):
    _app, _tmp_path = photo_app
    monkeypatch.setenv(photos.MAX_RAW_BYTES_ENV, "not-a-number")
    assert photos.max_raw_bytes() == photos.DEFAULT_MAX_RAW_BYTES
    monkeypatch.setenv(photos.MAX_RAW_BYTES_ENV, str(10**12))
    assert photos.max_raw_bytes() == photos.ABSOLUTE_MAX_RAW_BYTES
    monkeypatch.setenv(photos.MAX_PIXELS_ENV, "0")
    assert photos.max_pixels() == 1
    monkeypatch.setenv(photos.STAGE_TTL_SECONDS_ENV, "1")
    assert photos.stage_ttl_seconds() == 60


def test_tokens_resolve_only_in_the_current_workspace_and_commit_stably(photo_app):
    app, _tmp_path = photo_app
    with active_workspace(app, "user-a"):
        staged = photos.stage_meal_photo(upload(image_bytes()), now=NOW)
        token = staged["token"]
        assert photos.resolve_staged_photo(token).is_file()

    with active_workspace(app, "user-b"):
        with pytest.raises(photos.NutritionPhotoNotFoundError):
            photos.resolve_staged_photo(token)
        with pytest.raises(photos.NutritionPhotoNotFoundError):
            photos.commit_meal_photo(token, meal_id="other-meal", now=NOW)
        assert photos.delete_meal_photo(token) is False

    with active_workspace(app, "user-a"):
        committed = photos.commit_meal_photo(
            token, meal_id="meal-123", now=NOW + timedelta(minutes=2)
        )
        repeated = photos.commit_meal_photo(
            token, meal_id="meal-123", now=NOW + timedelta(minutes=3)
        )
        with pytest.raises(photos.NutritionPhotoNotFoundError):
            photos.resolve_staged_photo(token)
        committed_path = photos.resolve_meal_photo(token)
        raw, served = photos.read_meal_photo(token)

    assert committed["token"] == token
    assert repeated == committed
    assert committed["media_id"] == token
    assert committed["status"] == "committed"
    assert committed["committed_at"] == "2026-07-10T15:32:00Z"
    assert committed_path.is_file()
    assert raw.startswith(b"\xff\xd8")
    assert served == committed
    assert_path_free(committed)


def test_guest_and_user_workspaces_with_same_token_cannot_cross_resolve(
    photo_app, monkeypatch
):
    app, tmp_path = photo_app
    tokens = iter(["A" * 43, "A" * 43, "B" * 43])
    monkeypatch.setattr(photos.secrets, "token_urlsafe", lambda _size: next(tokens))

    with active_workspace(app, "user-a"):
        user_photo = photos.stage_meal_photo(upload(image_bytes()), now=NOW)
    with active_workspace(app, "", guest_id="guest-a"):
        guest_photo = photos.stage_meal_photo(upload(image_bytes()), now=NOW)
        assert photos.resolve_staged_photo(guest_photo["token"]).is_file()

    # The first attempted guest token may equal the user's token because token
    # allocation is workspace-local; this is safe because each resolver roots
    # the same opaque value in the active workspace.
    assert user_photo["token"] == guest_photo["token"] == "A" * 43
    assert (tmp_path / "users" / "user-a").is_dir()
    assert (tmp_path / "guests" / "guest-a").is_dir()


def test_commit_rolls_back_to_staging_when_metadata_write_fails(
    photo_app, monkeypatch
):
    app, _tmp_path = photo_app
    with active_workspace(app):
        staged = photos.stage_meal_photo(upload(image_bytes()), now=NOW)

        def fail_write(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(photos.durable_runtime, "atomic_write_json", fail_write)
        with pytest.raises(OSError):
            photos.commit_meal_photo(staged["token"], meal_id="meal-1", now=NOW)
        assert photos.resolve_staged_photo(staged["token"]).is_file()
        with pytest.raises(photos.NutritionPhotoNotFoundError):
            photos.resolve_meal_photo(staged["token"])


def test_delete_handles_staged_and_committed_media_without_touching_other_files(
    photo_app
):
    app, tmp_path = photo_app
    outside = tmp_path / "keep.txt"
    outside.write_text("keep", encoding="utf-8")

    with active_workspace(app):
        staged = photos.stage_meal_photo(upload(image_bytes()), now=NOW)
        assert photos.delete_meal_photo(staged["token"]) is True
        assert photos.delete_meal_photo(staged["token"]) is False

        committed = photos.stage_meal_photo(upload(image_bytes()), now=NOW)
        photos.commit_meal_photo(committed["token"], meal_id="meal-2", now=NOW)
        assert photos.delete_meal_photo(committed["token"]) is True
        with pytest.raises(photos.NutritionPhotoNotFoundError):
            photos.resolve_meal_photo(committed["token"])

        with pytest.raises(photos.NutritionPhotoValidationError):
            photos.delete_meal_photo("../../keep")

    assert outside.read_text(encoding="utf-8") == "keep"


def test_cleanup_removes_only_expired_stages_and_private_temp_artifacts(photo_app):
    app, _tmp_path = photo_app
    old_time = NOW - timedelta(hours=3)

    with active_workspace(app):
        old_photo = photos.stage_meal_photo(upload(image_bytes()), now=old_time)
        current_photo = photos.stage_meal_photo(upload(image_bytes()), now=NOW)
        staging_root = photos.resolve_staged_photo(current_photo["token"]).parent
        old_temp = staging_root / ".raw-abandoned.png"
        old_temp.write_bytes(b"private temporary data")
        orphan_token = "O" * 43
        orphan_image = staging_root / f"{orphan_token}.jpg"
        orphan_image.write_bytes(image_bytes("JPEG"))
        old_timestamp = old_time.timestamp()
        import os

        os.utime(old_temp, (old_timestamp, old_timestamp))
        os.utime(orphan_image, (old_timestamp, old_timestamp))

        result = photos.cleanup_staged_meal_photos(
            older_than_seconds=60 * 60, now=NOW
        )
        with pytest.raises(photos.NutritionPhotoNotFoundError):
            photos.resolve_staged_photo(old_photo["token"])
        assert photos.resolve_staged_photo(current_photo["token"]).is_file()

    assert result == {
        "removed_count": 1,
        "removed_tokens": [old_photo["token"]],
        "removed_artifact_count": 2,
    }
    assert not old_temp.exists()
    assert not orphan_image.exists()


def test_service_fails_closed_without_an_authenticated_request_workspace(
    photo_app
):
    app, tmp_path = photo_app
    candidate = upload(image_bytes())

    with pytest.raises(photos.NutritionPhotoAuthorizationError):
        photos.stage_meal_photo(candidate, now=NOW)

    with app.test_request_context("/"):
        g.session_identity_validated = True
        g.authenticated_user_id = ""
        g.authenticated_guest_session_id = ""
        with pytest.raises(photos.NutritionPhotoAuthorizationError):
            photos.stage_meal_photo(upload(image_bytes()), now=NOW)

    assert not (tmp_path / "users").exists()
    assert not (tmp_path / "guests").exists()


@pytest.mark.parametrize("token", ["", "short", "../" + "a" * 40, "a" * 81])
def test_token_validation_rejects_nonopaque_or_traversal_values(photo_app, token):
    app, _tmp_path = photo_app
    with active_workspace(app):
        with pytest.raises(photos.NutritionPhotoValidationError) as caught:
            photos.resolve_meal_photo(token)
    assert caught.value.code == "INVALID_MEAL_PHOTO_TOKEN"
