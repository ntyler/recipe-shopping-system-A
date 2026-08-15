from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import artifact_ownership_service as ownership
from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services import pantry_service
from PushShoppingList.services import storage_service


def install_schema(database):
    result = application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    assert result["action"] in {"installed", "upgraded", "unchanged"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def source(workspace_root, source_path, workspace_id, *, lifecycle_state="active", roots=()):
    workspace_type = "guest" if workspace_id.startswith("guest:") else "user"
    subject_id = workspace_id.split(":", 1)[1] if workspace_type == "guest" else workspace_id
    return ownership.ArtifactDocumentSource(
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
        workspace_root=workspace_root,
        source_path=source_path,
        source_name="recipe_json",
        lifecycle_state=lifecycle_state,
        artifact_roots=tuple(roots),
    )


def artifact_rows(database):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM artifacts ORDER BY storage_key")]


def test_preview_finds_exact_local_variants_and_verified_r2_without_leaking_owner(tmp_path):
    workspace = tmp_path / "guest-a"
    image = workspace / "recipe-extractor" / "data" / "uploads" / "dish.png"
    variant = image.with_name("dish__thumb.webp")
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    variant.write_bytes(b"variant")
    document_path = write_json(
        workspace / "recipe-extractor" / "data" / "output" / "dish.json",
        {
            "cover_image": {"path": "data/uploads/dish.png"},
            "pdf": {
                "cloudflare_r2": {
                    "object_key": "recipe-pdfs/dish.pdf",
                    "etag": "immutable-etag",
                }
            },
        },
    )

    preview = ownership.preview_artifact_ownership(
        [source(workspace, document_path, "guest:guest-secret")]
    )

    assert preview.counts == {
        "sources": 1,
        "references": 3,
        "artifacts": 3,
        "ready": 3,
        "shared": 0,
        "missing": 0,
        "blocked": 0,
        "local": 2,
        "r2": 1,
    }
    assert all(
        item.exclusive_owner
        for item in preview.candidates
        if item.storage_backend == "local"
    )
    assert next(
        item for item in preview.candidates if item.storage_backend == "r2"
    ).exclusive_owner is False
    report_text = json.dumps(preview.to_dict())
    assert "guest-secret" not in report_text
    assert str(workspace) not in report_text


def test_forged_verified_r2_reference_never_gains_physical_delete_authority(
    tmp_path,
):
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    guest_root = tmp_path / "guest"
    document_path = write_json(
        guest_root / "recipe.json",
        {
            "cloudflare_r2": {
                "object_key": "recipe-pdfs/unrelated-owner.pdf",
                "sha256": "a" * 64,
                "etag": "publicly-observable-etag",
                "version_id": "public-version",
            }
        },
    )
    preview = ownership.preview_artifact_ownership(
        [source(guest_root, document_path, "guest:forged-owner")]
    )

    assert preview.counts["r2"] == 1
    assert preview.candidates[0].exclusive_owner is False
    ownership.apply_artifact_ownership(
        preview,
        db_path=database,
        authorized=True,
        approval=ownership.APPLY_APPROVAL_PHRASE,
    )
    stored = artifact_rows(database)[0]
    assert stored["storage_backend"] == "r2"
    assert stored["exclusive_owner"] == 0


def test_shared_file_is_global_nonexclusive_and_backfill_is_idempotent(tmp_path):
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    shared_root = tmp_path / "approved-generated"
    shared_root.mkdir()
    shared_image = shared_root / "shared.png"
    shared_image.write_bytes(b"shared")
    first_root = tmp_path / "guest-one"
    second_root = tmp_path / "user-two"
    first_source = write_json(first_root / "recipe.json", {"image_url": str(shared_image)})
    second_source = write_json(second_root / "recipe.json", {"image_url": str(shared_image)})
    preview = ownership.preview_artifact_ownership(
        [
            source(first_root, first_source, "guest:one", roots=(shared_root,)),
            source(second_root, second_source, "user-two", roots=(shared_root,)),
        ]
    )

    candidate = preview.candidates[0]
    assert candidate.workspace_id == ownership.GLOBAL_WORKSPACE_ID
    assert candidate.owner_count == 2
    assert candidate.exclusive_owner is False
    first = ownership.apply_artifact_ownership(
        preview,
        db_path=database,
        authorized=True,
        approval=ownership.APPLY_APPROVAL_PHRASE,
    )
    second = ownership.apply_artifact_ownership(
        preview,
        db_path=database,
        authorized=True,
        approval=ownership.APPLY_APPROVAL_PHRASE,
    )

    assert first.inserted == 1
    assert second.unchanged == 1
    row = artifact_rows(database)[0]
    assert row["workspace_id"] == ownership.GLOBAL_WORKSPACE_ID
    assert row["exclusive_owner"] == 0
    assert shared_image.exists()


def test_partial_failure_rolls_back_and_same_preview_can_be_retried(tmp_path):
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    guest_root = tmp_path / "guest"
    user_root = tmp_path / "user"
    guest_image = guest_root / "guest.png"
    user_image = user_root / "user.png"
    guest_root.mkdir()
    user_root.mkdir()
    guest_image.write_bytes(b"guest")
    user_image.write_bytes(b"user")
    guest_source = write_json(guest_root / "data.json", {"image_url": "guest.png"})
    user_source = write_json(user_root / "data.json", {"image_url": "user.png"})
    preview = ownership.preview_artifact_ownership(
        [
            source(guest_root, guest_source, "guest:expired", lifecycle_state="inactive"),
            source(user_root, user_source, "unrelated-user"),
        ]
    )

    def fail_after_first(stage, context):
        if stage == "after_artifact" and context["index"] == 0:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        ownership.apply_artifact_ownership(
            preview,
            db_path=database,
            authorized=True,
            approval=ownership.APPLY_APPROVAL_PHRASE,
            failure_injector=fail_after_first,
        )
    assert artifact_rows(database) == []

    result = ownership.apply_artifact_ownership(
        preview,
        db_path=database,
        authorized=True,
        approval=ownership.APPLY_APPROVAL_PHRASE,
    )
    assert result.inserted == 2
    assert {row["workspace_id"] for row in artifact_rows(database)} == {
        "guest:expired",
        "unrelated-user",
    }


def test_stale_or_unsafe_cross_workspace_reference_cannot_gain_delete_authority(tmp_path):
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    guest_root = tmp_path / "guest-a"
    other_root = tmp_path / "guest-b"
    guest_root.mkdir()
    other_root.mkdir()
    other_asset = other_root / "other.png"
    other_asset.write_bytes(b"not-owned")
    bundled_asset = tmp_path / "application" / "static" / "logo.png"
    bundled_asset.parent.mkdir(parents=True)
    bundled_asset.write_bytes(b"bundled")
    document_path = write_json(
        guest_root / "recipe.json",
        {
            "image_url": str(other_asset),
            "step_image_url": str(bundled_asset),
        },
    )
    preview = ownership.preview_artifact_ownership(
        [source(guest_root, document_path, "guest:attacker")]
    )

    assert preview.counts["blocked"] == 2
    assert not any(item.exclusive_owner for item in preview.candidates)
    with pytest.raises(ownership.ArtifactOwnershipPreviewError):
        ownership.apply_artifact_ownership(
            preview,
            db_path=database,
            authorized=True,
            approval=ownership.APPLY_APPROVAL_PHRASE,
        )
    assert artifact_rows(database) == []

    # A valid preview is also stale if the exact source changes before apply.
    owned = guest_root / "owned.png"
    owned.write_bytes(b"owned")
    write_json(document_path, {"image_url": "owned.png"})
    valid_preview = ownership.preview_artifact_ownership(
        [source(guest_root, document_path, "guest:attacker")]
    )
    write_json(document_path, {"image_url": "owned.png", "changed": True})
    with pytest.raises(ownership.StaleArtifactOwnershipPreviewError):
        ownership.apply_artifact_ownership(
            valid_preview,
            db_path=database,
            authorized=True,
            approval=ownership.APPLY_APPROVAL_PHRASE,
        )


def test_database_runtime_registers_only_explicit_new_global_image_as_exclusive(
    monkeypatch, tmp_path
):
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    user_data = tmp_path / "users"
    workspace = user_data / "user-a"
    workspace.mkdir(parents=True)
    generated_root = tmp_path / "generated"
    generated_root.mkdir()
    image = generated_root / "pantry.png"
    image.write_bytes(b"new-image")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", user_data)
    monkeypatch.setattr(ownership, "APPROVED_GLOBAL_GENERATED_ROOTS", (generated_root,))
    monkeypatch.setenv(durable_runtime.DURABLE_BACKEND_ENV, "db_only")
    legacy_called = []

    durable_runtime.save_json_document(
        {"items": [{"image_url": str(image)}]},
        lambda value: legacy_called.append(value),
        domain="pantry",
        document_key="inventory",
        source_key="pantry_inventory",
        source_ref="pantry_inventory.json",
        workspace_id="user-a",
        workspace_type="user",
        subject_id="user-a",
        db_path=database,
        new_artifact_paths=(str(image),),
    )
    durable_runtime.save_json_document(
        {"items": [{"image_url": str(image), "quantity": 2}]},
        lambda value: legacy_called.append(value),
        domain="pantry",
        document_key="inventory",
        source_key="pantry_inventory",
        source_ref="pantry_inventory.json",
        workspace_id="user-a",
        workspace_type="user",
        subject_id="user-a",
        db_path=database,
    )

    assert legacy_called == []
    row = artifact_rows(database)[0]
    assert row["workspace_id"] == "user-a"
    assert row["exclusive_owner"] == 1
    metadata = json.loads(row["metadata_json"])
    assert metadata["trusted_write"] is True


def test_pantry_new_file_is_removed_when_durable_persistence_fails(monkeypatch, tmp_path):
    package = tmp_path / "PushShoppingList"
    image_root = package / "static" / "generated" / "pantry_items"
    monkeypatch.setattr(ownership, "PACKAGE_DIR", package)
    monkeypatch.setattr(pantry_service, "PANTRY_IMAGE_FOLDER", image_root)
    monkeypatch.setattr(
        pantry_service,
        "load_pantry_inventory",
        lambda **_kwargs: {"items": [{"id": "item-1", "ingredient_name": "Beans"}]},
    )

    def fail_save(*_args, **_kwargs):
        raise RuntimeError("registry failed")

    monkeypatch.setattr(pantry_service, "save_pantry_inventory", fail_save)
    upload = FileStorage(
        stream=io.BytesIO(b"not-a-real-image-but-a-written-file"),
        filename="beans.png",
        content_type="image/png",
    )

    with pytest.raises(RuntimeError, match="registry failed"):
        pantry_service.save_pantry_item_image_upload("item-1", upload)

    assert not list(image_root.glob("*"))


def test_feedback_attachment_uses_exact_user_owner_without_delete_authority(
    monkeypatch, tmp_path
):
    package = tmp_path / "PushShoppingList"
    feedback_root = package / "static" / "uploads" / "feedback"
    attachment = feedback_root / "RSL-1001" / "evidence.txt"
    attachment.parent.mkdir(parents=True)
    attachment.write_text("evidence", encoding="utf-8")
    monkeypatch.setattr(ownership, "PACKAGE_DIR", package)
    monkeypatch.setattr(ownership, "FEEDBACK_UPLOAD_DIR", feedback_root)
    feedback_json = write_json(
        tmp_path / "feedback.json",
        {
            "feedback": [
                {
                    "user": {"user_id": "user-exact"},
                    "attachments": [
                        {"path": "uploads/feedback/RSL-1001/evidence.txt"}
                    ],
                }
            ]
        },
    )
    feedback_source = ownership.ArtifactDocumentSource(
        ownership.GLOBAL_WORKSPACE_ID,
        ownership.GLOBAL_WORKSPACE_TYPE,
        ownership.GLOBAL_SUBJECT_ID,
        package,
        feedback_json,
        "feedback",
    )

    preview = ownership.preview_artifact_ownership([feedback_source])

    assert len(preview.candidates) == 1
    assert preview.candidates[0].workspace_id == "user-exact"
    assert preview.candidates[0].artifact_kind == "attachment"
    assert preview.candidates[0].exclusive_owner is False


def test_unverified_r2_key_is_registered_metadata_only_and_apply_gate_is_exact(tmp_path):
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    workspace = tmp_path / "guest"
    document_path = write_json(
        workspace / "recipe.json",
        {"pdf": {"cloudflare_r2": {"object_key": "recipe-pdfs/unverified.pdf"}}},
    )
    preview = ownership.preview_artifact_ownership(
        [source(workspace, document_path, "guest:expired")]
    )

    assert preview.candidates[0].storage_backend == "r2"
    assert preview.candidates[0].exclusive_owner is False
    with pytest.raises(ownership.ArtifactOwnershipApprovalError):
        ownership.apply_artifact_ownership(
            preview,
            db_path=database,
            authorized=True,
            approval="almost correct",
        )
    result = ownership.apply_artifact_ownership(
        preview,
        db_path=database,
        authorized=True,
        approval=ownership.APPLY_APPROVAL_PHRASE,
    )

    assert result.inserted == 1
    row = artifact_rows(database)[0]
    assert row["exclusive_owner"] == 0
    metadata = json.loads(row["metadata_json"])
    assert metadata["physical_delete_blocked"] is True


def test_default_run_is_read_only_and_does_not_create_database(tmp_path):
    workspace = tmp_path / "user"
    document_path = write_json(workspace / "recipe.json", {"recipe_title": "No files"})
    database = tmp_path / "must-not-exist.sqlite3"

    result = ownership.run_artifact_ownership_backfill(
        sources=[source(workspace, document_path, "user-one")],
        db_path=database,
    )

    assert isinstance(result, ownership.ArtifactOwnershipPreview)
    assert result.to_dict()["dry_run"] is True
    assert not database.exists()
