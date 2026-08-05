import json
from pathlib import Path

import pytest

from PushShoppingList.scripts import repair_generated_recipe_pdfs as repair
from PushShoppingList.services import cloudflare_r2_storage


def one_page_text_pdf(text):
    escaped = str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(value)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(payload)


def write_record(output_folder, filename, payload):
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def configure_fake_r2(monkeypatch, objects, pdf_bytes_by_key):
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "list_pdf_objects",
        lambda prefixes=None: {
            "ok": True,
            "objects": objects,
            "object_count": len(objects),
        },
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "read_pdf_object_bytes",
        lambda key, **_kwargs: {
            "ok": True,
            "object_key": key,
            "bytes": pdf_bytes_by_key[key],
        },
    )


def test_repair_mapping_uses_unique_superseding_menu_item_record(tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    key = "recipe-pdfs/legacy_generated_recipe.pdf"
    old_url = (
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&"
        "menu_item=menu-item-148-AI-Inferred_Black_Pepper_Stir-Fry"
    )
    current_url = (
        "https://www.velasiancuisine.com/rs/menu_home5.action?resInput=RES4902&"
        "menu_item=menu-item-148-Black_Pepper"
    )
    write_record(output, "legacy.json", {
        "source_url": old_url,
        "generated_recipe_pdf_object_key": key,
    })
    write_record(output, "current.json", {
        "source_url": current_url,
        "recipe_title": "Black Pepper",
        "ingredients": [{"ingredient": "beef"}],
        "instructions": [{"instruction": "Stir fry until cooked."}],
    })

    records, failures = repair.scan_recipe_records(data_root, legacy_output=None)
    by_key, by_item = repair.build_record_indexes(records)
    selected, reason = repair.choose_repair_source(by_key[key], by_item)

    assert failures == []
    assert selected.source_url == current_url
    assert reason == "superseded_menu_item_record"


def test_records_without_explicit_object_keys_are_never_legacy_key_guesses(tmp_path):
    shared = "https://example.test/recipes/" + ("same-collision-prefix-" * 10)
    first = repair.RecipeRecord(
        "user-a",
        tmp_path / "first.json",
        shared + "first",
        {"source_url": shared + "first", "recipe_title": "First", "ingredients": ["a"]},
    )
    second = repair.RecipeRecord(
        "user-a",
        tmp_path / "second.json",
        shared + "second",
        {"source_url": shared + "second", "recipe_title": "Second", "ingredients": ["b"]},
    )

    assert repair.legacy_safe_filename(first.source_url) == repair.legacy_safe_filename(second.source_url)
    assert repair.generated_object_keys_for_record(first) == []
    assert repair.generated_object_keys_for_record(second) == []
    by_key, _by_menu = repair.build_record_indexes([first, second])
    assert by_key == {}

    short_a = repair.RecipeRecord(
        "user-a",
        tmp_path / "short-a.json",
        "https://example.test/a+b",
        {"source_url": "https://example.test/a+b", "recipe_title": "A"},
    )
    short_b = repair.RecipeRecord(
        "user-a",
        tmp_path / "short-b.json",
        "https://example.test/a b",
        {"source_url": "https://example.test/a b", "recipe_title": "B"},
    )
    assert repair.legacy_safe_filename(short_a.source_url) == repair.legacy_safe_filename(short_b.source_url)
    assert repair.generated_object_keys_for_record(short_a) == []
    assert repair.generated_object_keys_for_record(short_b) == []


def test_scan_rejects_conflicting_explicit_object_key_aliases(tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    path = write_record(output, "conflict.json", {
        "source_url": "https://example.test/recipe/conflict",
        "generated_recipe_pdf_object_key": "recipe-pdfs/first_generated_recipe.pdf",
        "pdf": {
            "generated_recipe": {
                "r2_object_key": "recipe-pdfs/second_generated_recipe.pdf",
            },
        },
    })

    records, failures = repair.scan_recipe_records(data_root, legacy_output=None)

    assert records == []
    assert failures == [{
        "file": str(path),
        "error": "conflicting_generated_pdf_object_keys",
        "object_keys": [
            "recipe-pdfs/first_generated_recipe.pdf",
            "recipe-pdfs/second_generated_recipe.pdf",
        ],
    }]


def test_dry_report_exposes_record_scan_failures_and_apply_refuses_them(
    monkeypatch,
    tmp_path,
):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    path = write_record(output, "missing-source.json", {
        "generated_recipe_pdf_object_key": "recipe-pdfs/orphan_generated_recipe.pdf",
    })
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "list_pdf_objects",
        lambda prefixes=None: {"ok": True, "objects": [], "object_count": 0},
    )

    dry_result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        report_path=None,
        log=lambda _message: None,
    )

    assert dry_result["invalid_record_files"] == 1
    assert dry_result["record_scan_failures"] == [{
        "file": str(path),
        "error": "missing_source_url_with_generated_pdf_key",
    }]
    with pytest.raises(RuntimeError, match="missing_source_url_with_generated_pdf_key") as exc:
        repair.audit_and_repair_generated_recipe_pdfs(
            data_root=data_root,
            legacy_output=None,
            apply=True,
            confirm_r2_overwrite=True,
            report_path=None,
            log=lambda _message: None,
        )
    assert str(path) in str(exc.value)


def test_default_dry_run_counts_corrupt_repairable_and_skipped_without_upload(
    monkeypatch,
    tmp_path,
):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    repairable_key = "recipe-pdfs/repairable_generated_recipe.pdf"
    skipped_key = "recipe-pdfs/unmapped_generated_recipe.pdf"
    valid_key = "recipe-pdfs/valid_generated_recipe.pdf"
    target_url = "https://example.test/menu?resInput=R1&menu_item=menu-item-7-old"
    source_url = "https://example.test/menu-v2?resInput=R1&menu_item=menu-item-7-current"
    write_record(output, "target.json", {
        "source_url": target_url,
        "generated_recipe_pdf_object_key": repairable_key,
    })
    write_record(output, "source.json", {
        "source_url": source_url,
        "recipe_title": "Noodle Soup",
        "ingredients": [{"ingredient": "noodles"}],
        "instructions": [{"instruction": "Simmer the broth."}],
    })
    write_record(output, "valid.json", {
        "source_url": "https://example.test/recipe/valid",
        "generated_recipe_pdf_object_key": valid_key,
        "recipe_title": "Noodle Soup",
        "ingredients": [{"ingredient": "noodles"}],
        "instructions": [{"instruction": "Simmer the broth."}],
    })
    objects = [
        {"object_key": repairable_key, "etag": "bad-1"},
        {"object_key": skipped_key, "etag": "bad-2"},
        {"object_key": valid_key, "etag": "good-1"},
    ]
    error_pdf = one_page_text_pdf("Your file couldn't be accessed ERR_FILE_NOT_FOUND")
    configure_fake_r2(
        monkeypatch,
        objects,
        {
            repairable_key: error_pdf,
            skipped_key: error_pdf,
            valid_key: one_page_text_pdf("Noodle Soup Ingredients noodles Instructions simmer"),
        },
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "upload_pdf",
        lambda *_args, **_kwargs: pytest.fail("dry-run attempted an R2 upload"),
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "delete_pdf",
        lambda *_args, **_kwargs: pytest.fail("repair audit attempted an R2 delete"),
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        report_path=None,
        log=lambda _message: None,
    )

    assert result["mode"] == "dry-run"
    assert result["generated_objects"] == 3
    assert result["corrupted"] == 2
    assert result["repairable"] == 1
    assert result["skipped"] == 1
    assert result["valid_unchanged"] == 1
    assert result["failed"] == 0
    assert result["production_r2_mutations"] == 0


def test_mapped_unparseable_pdf_is_structural_corruption_and_repairable(monkeypatch, tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    object_key = "recipe-pdfs/truncated_generated_recipe.pdf"
    write_record(output, "truncated.json", {
        "source_url": "https://example.test/recipe/truncated",
        "generated_recipe_pdf_object_key": object_key,
        "recipe_title": "Recovered Stew",
        "ingredients": [{"ingredient": "stock"}],
        "instructions": [{"instruction": "Simmer."}],
    })
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "truncated-etag"}],
        {object_key: b"%PDF-1.4\ntruncated"},
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        report_path=None,
        log=lambda _message: None,
    )

    assert result["structural_invalid"] == 1
    assert result["corrupted"] == 1
    assert result["repairable"] == 1
    assert result["failed"] == 0


def test_custom_data_root_does_not_implicitly_include_repository_legacy_records(
    monkeypatch,
    tmp_path,
):
    custom_users = tmp_path / "staging" / "users"
    custom_output = custom_users / "user-a" / "recipe-extractor" / "data" / "output"
    legacy_output = tmp_path / "production-legacy" / "output"
    write_record(custom_output, "custom.json", {
        "source_url": "https://staging.example/recipe",
        "recipe_title": "Staging",
        "ingredients": ["beans"],
    })
    write_record(legacy_output, "legacy.json", {
        "source_url": "https://production.example/recipe",
        "recipe_title": "Production",
        "ingredients": ["stock"],
    })
    monkeypatch.setattr(repair, "DEFAULT_LEGACY_OUTPUT", legacy_output)
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "list_pdf_objects",
        lambda prefixes=None: {"ok": True, "bucket": "staging", "objects": []},
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=custom_users,
        report_path=None,
        log=lambda _message: None,
    )

    assert result["saved_records"] == 1


def test_explicit_custom_legacy_metadata_is_saved_to_scanned_record(monkeypatch, tmp_path):
    from PushShoppingList.services import recipe_edit_service
    from PushShoppingList.services import recipe_extract_service

    output = tmp_path / "custom-legacy" / "data" / "output"
    source_url = "https://legacy.example/recipe/custom"
    record_path = write_record(output, "noncanonical-record-name.json", {
        "source_url": source_url,
        "recipe_title": "Custom Legacy",
        "ingredients": [{"ingredient": "beans"}],
    })
    before_files = list(output.glob("*.json"))

    with repair.selected_workspace(
        tmp_path / "users",
        "__legacy__",
        output_folder=output,
    ):
        result = recipe_edit_service.save_recipe_pdf_storage_metadata(
            source_url,
            {
                "object_key": "recipe-pdfs/custom_generated_recipe.pdf",
                "public_url": "https://public.example.com/recipe-pdfs/custom_generated_recipe.pdf",
                "uploaded_at": "2026-08-04T12:00:00Z",
                "etag": "custom-etag",
                "sha256": "c" * 64,
                "size_bytes": 2048,
                "verified": True,
                "validation": {
                    "ok": True,
                    "semantic_validation_required": True,
                    "validation_version": recipe_extract_service.PDF_VALIDATION_VERSION,
                    "sha256": "c" * 64,
                    "size_bytes": 2048,
                },
            },
            output.parent / "pdf" / "custom_generated_recipe.pdf",
            recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
            recipe_output_path=record_path,
        )

    assert result["ok"] is True
    assert list(output.glob("*.json")) == before_files
    saved = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved["pdf"][recipe_extract_service.PDF_KIND_GENERATED_RECIPE]["etag"] == "custom-etag"


def test_apply_uses_same_object_key_and_records_verified_result(monkeypatch, tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    object_key = "recipe-pdfs/stable_generated_recipe.pdf"
    source_url = "https://example.test/recipe/7"
    write_record(output, "recipe.json", {
        "source_url": source_url,
        "generated_recipe_pdf_object_key": object_key,
        "recipe_title": "Stable Soup",
        "ingredients": [{"ingredient": "stock"}],
    })
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "old-etag"}],
        {object_key: one_page_text_pdf("ERR_FILE_NOT_FOUND")},
    )
    calls = []

    def fake_repair(key, target, source, *, data_root, expected_etag=""):
        calls.append((key, target.source_url, source.source_url, Path(data_root), expected_etag))
        return {
            "ok": True,
            "etag": "new-etag",
            "sha256": "a" * 64,
            "size_bytes": 2048,
            "local_path": "D:/short/validated.pdf",
        }

    monkeypatch.setattr(repair, "regenerate_and_replace_object", fake_repair)
    state_path = tmp_path / "state.jsonl"
    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=state_path,
        log=lambda _message: None,
    )

    assert calls == [(object_key, source_url, source_url, data_root, "old-etag")]
    assert result["repaired"] == 1
    assert result["production_r2_mutations"] == 1
    event = json.loads(state_path.read_text(encoding="utf-8").strip())
    assert event["object_key"] == object_key
    assert event["etag"] == "new-etag"


def test_apply_records_pending_metadata_after_verified_remote_repair(monkeypatch, tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    object_key = "recipe-pdfs/pending_generated_recipe.pdf"
    source_url = "https://example.test/recipe/pending"
    write_record(output, f"{repair.legacy_safe_filename(source_url)}.json", {
        "source_url": source_url,
        "generated_recipe_pdf_object_key": object_key,
        "recipe_title": "Pending Soup",
        "ingredients": [{"ingredient": "stock"}],
    })
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "old-etag"}],
        {object_key: one_page_text_pdf("ERR_FILE_NOT_FOUND")},
    )
    monkeypatch.setattr(
        repair,
        "regenerate_and_replace_object",
        lambda *_args, **_kwargs: {
            "ok": False,
            "remote_repaired": True,
            "error": "metadata disk write failed",
            "etag": "new-etag",
            "sha256": "b" * 64,
            "size_bytes": 2048,
        },
    )
    state_path = tmp_path / "state.jsonl"

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=state_path,
        log=lambda _message: None,
    )

    event = json.loads(state_path.read_text(encoding="utf-8").strip())
    assert result["failed"] == 1
    assert result["production_r2_mutations"] == 1
    assert event["status"] == "remote_repaired_pending_metadata"
    assert event["etag"] == "new-etag"


def test_apply_continues_after_one_recipe_regeneration_raises(monkeypatch, tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    first_key = "recipe-pdfs/first_generated_recipe.pdf"
    second_key = "recipe-pdfs/second_generated_recipe.pdf"
    for index, key in enumerate((first_key, second_key), start=1):
        url = f"https://example.test/recipe/{index}"
        write_record(output, f"recipe-{index}.json", {
            "source_url": url,
            "generated_recipe_pdf_object_key": key,
            "recipe_title": f"Soup {index}",
            "ingredients": [{"ingredient": "stock"}],
        })
    error_pdf = one_page_text_pdf("ERR_FILE_NOT_FOUND")
    configure_fake_r2(
        monkeypatch,
        [
            {"object_key": first_key, "etag": "first-old"},
            {"object_key": second_key, "etag": "second-old"},
        ],
        {first_key: error_pdf, second_key: error_pdf},
    )

    def fake_repair(key, *_args, **_kwargs):
        if key == first_key:
            raise OSError("Chrome crashed")
        return {
            "ok": True,
            "etag": "second-new",
            "sha256": "d" * 64,
            "size_bytes": 2048,
            "local_path": "D:/short/second.pdf",
        }

    monkeypatch.setattr(repair, "regenerate_and_replace_object", fake_repair)
    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=tmp_path / "state.jsonl",
        log=lambda _message: None,
    )

    assert result["failed"] == 1
    assert result["repaired"] == 1
    assert result["production_r2_mutations"] == 1
    assert result["production_r2_mutations_possible"] == 1


def test_verified_repair_with_unwritable_state_forces_incomplete_failure(monkeypatch, tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    object_key = "recipe-pdfs/state-failure_generated_recipe.pdf"
    source_url = "https://example.test/recipe/state-failure"
    write_record(output, "state-failure.json", {
        "source_url": source_url,
        "generated_recipe_pdf_object_key": object_key,
        "recipe_title": "State Soup",
        "ingredients": [{"ingredient": "stock"}],
    })
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "old-etag"}],
        {object_key: one_page_text_pdf("ERR_FILE_NOT_FOUND")},
    )
    monkeypatch.setattr(
        repair,
        "regenerate_and_replace_object",
        lambda *_args, **_kwargs: {
            "ok": True,
            "etag": "new-etag",
            "sha256": "e" * 64,
            "size_bytes": 2048,
            "local_path": "D:/short/state.pdf",
        },
    )
    monkeypatch.setattr(
        repair,
        "append_repair_state",
        lambda *_args, **_kwargs: {"ok": False, "error": "state disk full"},
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=tmp_path / "unwritable" / "state.jsonl",
        log=lambda _message: None,
    )

    assert result["repaired"] == 1
    assert result["production_r2_mutations"] == 1
    assert result["state_write_failures"] == 1
    assert result["failed"] == 1
    assert result["incomplete"] is True
    assert result["ok"] is False


def test_apply_requires_separate_overwrite_confirmation(tmp_path):
    with pytest.raises(PermissionError, match="confirm-r2-overwrite"):
        repair.audit_and_repair_generated_recipe_pdfs(
            data_root=tmp_path,
            legacy_output=None,
            apply=True,
            confirm_r2_overwrite=False,
            report_path=None,
        )


def test_apply_refuses_invalid_saved_json_before_r2_access(monkeypatch, tmp_path):
    data_root = tmp_path / "users"
    output = data_root / "user-a" / "recipe-extractor" / "data" / "output"
    output.mkdir(parents=True)
    (output / "broken.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "list_pdf_objects",
        lambda **_kwargs: pytest.fail("apply accessed R2 despite incomplete record scan"),
    )

    with pytest.raises(RuntimeError, match="invalid record file|could not be parsed"):
        repair.audit_and_repair_generated_recipe_pdfs(
            data_root=data_root,
            legacy_output=None,
            apply=True,
            confirm_r2_overwrite=True,
            report_path=None,
        )


def test_apply_reports_incomplete_when_corrupt_object_cannot_be_mapped(monkeypatch, tmp_path):
    object_key = "recipe-pdfs/unmapped_generated_recipe.pdf"
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "bad-etag"}],
        {object_key: one_page_text_pdf("ERR_FILE_NOT_FOUND")},
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=tmp_path / "users",
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=tmp_path / "state.jsonl",
        log=lambda _message: None,
    )

    assert result["skipped"] == 1
    assert result["incomplete"] is True
    assert result["ok"] is False


def test_apply_reports_incomplete_for_unverified_unmapped_pdf(monkeypatch, tmp_path):
    object_key = "recipe-pdfs/unverified_generated_recipe.pdf"
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "unverified-etag"}],
        {object_key: one_page_text_pdf("A parseable document with no saved recipe mapping")},
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=tmp_path / "users",
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=tmp_path / "state.jsonl",
        log=lambda _message: None,
    )

    assert result["unverified_unchanged"] == 1
    assert result["incomplete"] is True
    assert result["ok"] is False


def test_requested_missing_object_is_failure_and_apply_refuses(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "list_pdf_objects",
        lambda prefixes=None: {"ok": True, "bucket": "test", "objects": []},
    )
    missing_key = "recipe-pdfs/missing_generated_recipe.pdf"

    dry = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=tmp_path / "users",
        legacy_output=None,
        object_keys=[missing_key],
        report_path=None,
        log=lambda _message: None,
    )
    assert dry["ok"] is False
    assert dry["missing_requested_object_keys"] == [missing_key]

    with pytest.raises(RuntimeError, match="were not found"):
        repair.audit_and_repair_generated_recipe_pdfs(
            data_root=tmp_path / "users",
            legacy_output=None,
            apply=True,
            confirm_r2_overwrite=True,
            object_keys=[missing_key],
            report_path=None,
        )


def test_matching_success_state_resumes_without_downloading(monkeypatch, tmp_path):
    object_key = "recipe-pdfs/already-repaired_generated_recipe.pdf"
    state_path = tmp_path / "state.jsonl"
    scope = {
        "r2_bucket": "test-bucket",
        "r2_account_id": "test-account",
        "r2_endpoint": "https://test.r2.example",
        "data_root_scope": str(tmp_path.resolve()),
        "legacy_output_scope": "__none__",
    }
    state_path.write_text(
        json.dumps({
            **scope,
            "status": "success",
            "object_key": object_key,
            "etag": "verified-etag",
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "list_pdf_objects",
        lambda prefixes=None: {
            "ok": True,
            "bucket": "test-bucket",
            "objects": [{"object_key": object_key, "etag": "verified-etag"}],
        },
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "config_values",
        lambda: {
            "bucket_name": "test-bucket",
            "account_id": "test-account",
            "endpoint": "https://test.r2.example",
        },
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "read_pdf_object_bytes",
        lambda _key: pytest.fail("resumed object was downloaded again"),
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=tmp_path,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=state_path,
        log=lambda _message: None,
    )

    assert result["resumed"] == 1
    assert result["objects_scanned"] == 0
    assert result["production_r2_mutations"] == 0


def test_resume_state_is_not_reused_across_r2_or_data_scopes(tmp_path):
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        json.dumps({
            "status": "success",
            "object_key": "recipe-pdfs/same.pdf",
            "etag": "same-etag",
            "r2_bucket": "production",
            "r2_account_id": "prod-account",
            "r2_endpoint": "https://prod.r2.example",
            "data_root_scope": "D:/production/users",
            "legacy_output_scope": "D:/production/legacy-output",
        })
        + "\n",
        encoding="utf-8",
    )

    loaded = repair.load_repair_state(
        state_path,
        {
            "r2_bucket": "staging",
            "r2_account_id": "stage-account",
            "r2_endpoint": "https://stage.r2.example",
            "data_root_scope": "D:/staging/users",
            "legacy_output_scope": "__none__",
        },
    )

    assert loaded == {}


def test_regenerate_chain_validates_conditional_overwrite_and_saves_metadata(
    monkeypatch,
    tmp_path,
):
    from PushShoppingList.services import recipe_edit_service
    from PushShoppingList.services import recipe_extract_service

    data_root = tmp_path / "user_data"
    users_root = data_root / "users"
    output = users_root / "user-a" / "recipe-extractor" / "data" / "output"
    source_url = "https://example.test/recipe/stable-soup"
    object_key = "recipe-pdfs/stable-soup_generated_recipe.pdf"
    record_path = write_record(output, f"{repair.legacy_safe_filename(source_url)}.json", {
        "source_url": source_url,
        "generated_recipe_pdf_object_key": object_key,
        "recipe_title": "Stable Soup",
        "ingredients": [{"ingredient": "vegetable stock"}],
        "instructions": [{"instruction": "Simmer until hot."}],
    })
    records, failures = repair.scan_recipe_records(data_root, legacy_output=None)
    assert failures == []
    target = records[0]

    monkeypatch.setattr(recipe_edit_service, "recipe_with_menu_metadata", lambda data: data)
    monkeypatch.setattr(
        repair,
        "_replace_validated_local_pdf",
        repair._replace_validated_local_pdf,
    )

    def fake_write(_url, _html, _html_path, pdf_path, **_kwargs):
        Path(pdf_path).write_bytes(
            one_page_text_pdf(
                "Stable Soup Ingredients vegetable stock Instructions Simmer until hot."
            )
        )
        return Path(pdf_path)

    monkeypatch.setattr(recipe_extract_service, "write_recipe_page_pdf", fake_write)
    # The repair module imports this symbol inside the function.
    monkeypatch.setattr(recipe_extract_service, "build_video_text_pdf_html", lambda *_a, **_k: "<html></html>")
    uploads = []

    def fake_upload(path, **kwargs):
        uploads.append({"path": Path(path), **kwargs})
        validation = kwargs["validation"]
        return {
            "ok": True,
            "verified": True,
            "object_key": kwargs["object_key"],
            "public_url": f"https://public.example.com/{kwargs['object_key']}",
            "bucket": "recipe-shopping-pdfs",
            "uploaded_at": "2026-08-04T12:00:00Z",
            "etag": "new-etag",
            "sha256": validation["sha256"],
            "size_bytes": Path(path).stat().st_size,
        }

    monkeypatch.setattr(cloudflare_r2_storage, "upload_pdf", fake_upload)

    result = repair.regenerate_and_replace_object(
        object_key,
        target,
        target,
        data_root=data_root,
        expected_etag="old-etag",
    )

    assert result["ok"] is True, result.get("error")
    assert uploads[0]["object_key"] == object_key
    assert uploads[0]["overwrite"] is True
    assert uploads[0]["expected_etag"] == "old-etag"
    assert uploads[0]["validation"]["semantic_validation_required"] is True
    saved = json.loads(record_path.read_text(encoding="utf-8"))
    generated = saved["pdf"][recipe_extract_service.PDF_KIND_GENERATED_RECIPE]
    assert generated["r2_object_key"] == object_key
    assert generated["etag"] == "new-etag"
    assert generated["validation"]["ok"] is True


def test_apply_reconciles_metadata_after_crash_without_second_r2_write(monkeypatch, tmp_path):
    from PushShoppingList.services import recipe_extract_service

    data_root = tmp_path / "user_data"
    users_root = data_root / "users"
    output = users_root / "user-a" / "recipe-extractor" / "data" / "output"
    source_url = "https://example.test/recipe/recovered-soup"
    object_key = "recipe-pdfs/recovered-soup_generated_recipe.pdf"
    record_path = write_record(output, f"{repair.legacy_safe_filename(source_url)}.json", {
        "source_url": source_url,
        "generated_recipe_pdf_object_key": object_key,
        "recipe_title": "Recovered Soup",
        "ingredients": [{"ingredient": "vegetable stock"}],
        "instructions": [{"instruction": "Simmer until hot."}],
    })
    remote_bytes = one_page_text_pdf(
        "Recovered Soup Ingredients vegetable stock Instructions Simmer until hot."
    )
    remote_sha = __import__("hashlib").sha256(remote_bytes).hexdigest()
    configure_fake_r2(
        monkeypatch,
        [{"object_key": object_key, "etag": "repaired-etag"}],
        {object_key: remote_bytes},
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "head_pdf_object",
        lambda key: {
            "ok": True,
            "exists": True,
            "object_key": key,
            "public_url": f"https://public.example.com/{key}",
            "bucket": "recipe-shopping-pdfs",
            "uploaded_at": "2026-08-04T12:00:00Z",
            "etag": "repaired-etag",
            "sha256": remote_sha,
            "size_bytes": len(remote_bytes),
            "semantically_validated": True,
            "validation_version": recipe_extract_service.PDF_VALIDATION_VERSION,
        },
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "upload_pdf",
        lambda *_args, **_kwargs: pytest.fail("metadata resume attempted a second R2 write"),
    )
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        json.dumps({
            "status": "remote_repaired_pending_metadata",
            "object_key": object_key,
            "etag": "repaired-etag",
        })
        + "\n",
        encoding="utf-8",
    )

    result = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=state_path,
        log=lambda _message: None,
    )

    assert result["metadata_reconciled"] == 1
    assert result["production_r2_mutations"] == 0
    saved = json.loads(record_path.read_text(encoding="utf-8"))
    generated = saved["pdf"][recipe_extract_service.PDF_KIND_GENERATED_RECIPE]
    assert generated["etag"] == "repaired-etag"
    assert generated["sha256"] == remote_sha
    assert json.loads(state_path.read_text(encoding="utf-8").splitlines()[-1])["status"] == "success"

    # Simulate the checkpoint append having failed after metadata was saved.
    # The next apply must recover the success checkpoint without another PUT.
    state_path.unlink()
    resumed = repair.audit_and_repair_generated_recipe_pdfs(
        data_root=data_root,
        legacy_output=None,
        apply=True,
        confirm_r2_overwrite=True,
        report_path=None,
        state_path=state_path,
        log=lambda _message: None,
    )
    recovered_event = json.loads(state_path.read_text(encoding="utf-8").strip())
    assert resumed["metadata_reconciled"] == 0
    assert resumed["production_r2_mutations"] == 0
    assert resumed["items"][0]["status"] == "metadata_checkpoint_recovered"
    assert recovered_event["status"] == "success"
    assert recovered_event["metadata_already_reconciled"] is True
