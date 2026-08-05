import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from PushShoppingList.services import recipe_extract_service


PISCO_URL = (
    "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/"
    "?category=1&menu_item=menu-item-1-Papa_Potatoe_a_la_Huancaina"
)
PISCO_ROUTE_URL = (
    "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/"
    "?category%3D1%26menu_item%3Dmenu-item-1-Papa_Potatoe_a_la_Huancaina"
)
EXPECTED_RECIPE = {
    "recipe_title": "Papa Potato a la Huancaina",
    "ingredients": [{"ingredient": "yellow potatoes"}],
    "instructions": [{"instruction": "Boil the potatoes until tender."}],
}


def one_page_text_pdf(text):
    escaped = str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1", errors="replace")
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
    for object_number, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{object_number} 0 obj\n".encode("ascii"))
        payload.extend(obj)
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
    if len(payload) < recipe_extract_service.PDF_MIN_VALID_BYTES:
        payload.extend(b" " * (recipe_extract_service.PDF_MIN_VALID_BYTES - len(payload)))
    return bytes(payload)


def valid_recipe_pdf_bytes():
    return one_page_text_pdf(
        "Papa Potato a la Huancaina Ingredients yellow potatoes "
        "Instructions Boil the potatoes until tender."
    )


def configure_pdf_paths(monkeypatch, tmp_path):
    output_folder = tmp_path / "output"
    pdf_folder = tmp_path / "pdf"
    temp_folder = tmp_path / "rpdf"
    output_folder.mkdir()
    pdf_folder.mkdir()
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_folder)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_folder)
    monkeypatch.setenv("RECIPE_PDF_TEMP_DIR", str(temp_folder))
    return output_folder, pdf_folder, temp_folder


@pytest.mark.parametrize("recipe_url", [PISCO_URL, PISCO_ROUTE_URL])
def test_long_pisco_url_uses_short_unique_pdf_source_path(monkeypatch, tmp_path, recipe_url):
    _output_folder, _pdf_folder, temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    deep_logs = tmp_path / "PushShoppingList" / "user_data" / "users" / ("u" * 32)
    deep_logs = deep_logs / "recipe_extractor" / "logs" / ("nested-workspace" * 3)
    deep_logs.mkdir(parents=True)
    monkeypatch.setattr(recipe_extract_service, "LOG_FOLDER", deep_logs)
    legacy_source = deep_logs / f"{recipe_extract_service.safe_filename(recipe_url)}_PDF_SOURCE.html"

    source_path = recipe_extract_service.write_pdf_source_html(
        recipe_url,
        "<html><body><h1>Papa Potato a la Huancaina</h1></body></html>",
    )
    try:
        assert len(str(legacy_source.resolve())) >= 260
        assert source_path.parent == temp_folder
        assert len(str(source_path.resolve())) < 240
        assert source_path.exists()
    finally:
        recipe_extract_service.remove_temporary_pdf_source(source_path)


def test_concurrent_pdf_generation_uses_unique_temporary_files(monkeypatch, tmp_path):
    _output_folder, _pdf_folder, temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    source_targets = []
    staging_paths = []
    lock = threading.Lock()

    class FakeDriver:
        page_source = "<html><body>Papa Potato a la Huancaina yellow potatoes</body></html>"
        current_url = ""
        title = "Papa Potato a la Huancaina"

        def set_page_load_timeout(self, _timeout):
            return None

        def get(self, target):
            self.current_url = target
            with lock:
                source_targets.append(target)

        def quit(self):
            return None

    def fake_print(_driver, pdf_path):
        with lock:
            staging_paths.append(Path(pdf_path))
        Path(pdf_path).write_bytes(valid_recipe_pdf_bytes())

    monkeypatch.setattr(recipe_extract_service, "create_headless_chrome_driver", lambda **_kwargs: FakeDriver())
    monkeypatch.setattr(recipe_extract_service, "prepare_page_for_pdf_print", lambda _driver: None)
    monkeypatch.setattr(recipe_extract_service, "print_current_browser_page_to_pdf", fake_print)
    destination = tmp_path / "pdf" / "pisco.pdf"

    def generate_pdf(_index):
        return recipe_extract_service.write_recipe_page_pdf(
            PISCO_URL,
            "<html><body><h1>Papa Potato a la Huancaina</h1><p>yellow potatoes</p></body></html>",
            None,
            destination,
            expected_recipe=EXPECTED_RECIPE,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(generate_pdf, range(4)))

    assert results == [destination] * 4
    assert len(source_targets) == len(set(source_targets)) == 4
    assert len(staging_paths) == len(set(staging_paths)) == 4
    assert all(path.parent == destination.parent for path in staging_paths)
    assert destination.read_bytes() == valid_recipe_pdf_bytes()
    assert not list(temp_folder.glob("*.html"))
    assert not list(destination.parent.glob(".*.pdf"))


def test_large_chrome_err_file_not_found_page_is_rejected_and_cleaned(monkeypatch, tmp_path):
    _output_folder, _pdf_folder, temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    print_calls = []

    class ErrorDriver:
        page_source = (
            "<html><body><h1>Your file couldn’t be accessed</h1>"
            "<div>ERR_FILE_NOT_FOUND</div>" + ("x" * 1500) + "</body></html>"
        )
        current_url = "chrome-error://chromewebdata/"
        title = "file:///missing is not available"

        def set_page_load_timeout(self, _timeout):
            return None

        def get(self, _target):
            raise TimeoutError("page load timed out")

        def quit(self):
            return None

    monkeypatch.setattr(
        recipe_extract_service,
        "create_headless_chrome_driver",
        lambda **_kwargs: ErrorDriver(),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "print_current_browser_page_to_pdf",
        lambda *_args: print_calls.append(True),
    )
    destination = tmp_path / "pdf" / "recipe.pdf"

    with pytest.raises(RuntimeError, match="Chrome could not load"):
        recipe_extract_service.write_recipe_page_pdf(
            PISCO_URL,
            "<html><body>Papa Potato</body></html>",
            None,
            destination,
        )

    assert print_calls == []
    assert not destination.exists()
    assert not list(temp_folder.glob("*.html"))
    assert not list(destination.parent.glob(".*.pdf"))


def test_large_non_error_page_source_does_not_override_navigation_failure(monkeypatch, tmp_path):
    _output_folder, _pdf_folder, temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    print_calls = []

    class TimedOutDriver:
        page_source = "<html><body>Papa Potato yellow potatoes" + ("x" * 4000) + "</body></html>"
        current_url = "file:///partial-recipe.html"
        title = "Papa Potato a la Huancaina"

        def set_page_load_timeout(self, _timeout):
            return None

        def get(self, _target):
            raise TimeoutError("navigation timeout")

        def quit(self):
            return None

    monkeypatch.setattr(
        recipe_extract_service,
        "create_headless_chrome_driver",
        lambda **_kwargs: TimedOutDriver(),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "print_current_browser_page_to_pdf",
        lambda *_args: print_calls.append(True),
    )
    destination = tmp_path / "pdf" / "partial.pdf"

    with pytest.raises(RuntimeError, match="navigation did not complete"):
        recipe_extract_service.write_recipe_page_pdf(
            PISCO_URL,
            "<html><body>Papa Potato</body></html>",
            None,
            destination,
            expected_recipe=EXPECTED_RECIPE,
        )

    assert print_calls == []
    assert not destination.exists()
    assert not list(temp_folder.glob("*.html"))


def test_recipe_pdf_validation_rejects_split_chrome_error_text(tmp_path):
    pdf_path = tmp_path / "chrome-error.pdf"
    pdf_path.write_bytes(
        one_page_text_pdf(
            "Your file couldn’t be accessed. It may have been moved, edited, or deleted. "
            "ERR_FILE_NO T_FOUND"
        )
    )

    result = recipe_extract_service.validate_generated_recipe_pdf(pdf_path)

    assert result["ok"] is False
    assert result["browser_error"] is True
    assert result["browser_error_code"] == "ERR_FILE_NOT_FOUND"
    assert "error page" in result["error"].lower()
    assert result["page_count"] == 1
    assert len(result["sha256"]) == 64


def test_recipe_pdf_validation_rejects_unrelated_structurally_valid_pdf(tmp_path):
    pdf_path = tmp_path / "unrelated.pdf"
    pdf_path.write_bytes(one_page_text_pdf("Quarterly account statement and payment details."))

    result = recipe_extract_service.validate_generated_recipe_pdf(
        pdf_path,
        expected_recipe=EXPECTED_RECIPE,
    )

    assert result["ok"] is False
    assert "expected recipe title" in " ".join(result["errors"]).lower()
    assert result["page_count"] == 1


def test_recipe_pdf_validation_accepts_valid_one_page_recipe(tmp_path):
    pdf_path = tmp_path / "valid-recipe.pdf"
    pdf_bytes = valid_recipe_pdf_bytes()
    pdf_path.write_bytes(pdf_bytes)

    result = recipe_extract_service.validate_generated_recipe_pdf(
        pdf_path,
        expected_recipe=EXPECTED_RECIPE,
    )

    assert result["ok"] is True
    assert result["page_count"] == 1
    assert result["sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert "papa potato a la huancaina" in result["matched_evidence"]
    assert result["text_length"] > 50


def test_generated_semantic_validation_rejects_title_only_stub(tmp_path):
    pdf_path = tmp_path / "title-only.pdf"
    pdf_path.write_bytes(one_page_text_pdf("Pork Dumpling Source https://example.test/menu"))

    result = recipe_extract_service.validate_generated_recipe_pdf(
        pdf_path,
        expected_recipe={"recipe_title": "Pork Dumpling"},
        expected_title="Pork Dumpling",
        require_recipe_evidence=True,
    )

    assert result["ok"] is False
    assert result["semantic_validation_required"] is True
    assert "ingredient" in " ".join(result["errors"]).lower()


def test_recipe_pdf_validation_allows_extractor_inserted_spaces_inside_title_words(tmp_path):
    pdf_path = tmp_path / "wrapped-title-recipe.pdf"
    pdf_path.write_bytes(
        one_page_text_pdf(
            "Papa Potato a la H uancaina Ingredients yellow potatoes "
            "Instructions Boil the potatoes until tender."
        )
    )

    result = recipe_extract_service.validate_generated_recipe_pdf(
        pdf_path,
        expected_recipe=EXPECTED_RECIPE,
    )

    assert result["ok"] is True
    assert "papa potato a la huancaina" in result["matched_evidence"]


def test_invalid_generation_does_not_replace_existing_valid_pdf(monkeypatch, tmp_path):
    _output_folder, _pdf_folder, temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    destination = tmp_path / "pdf" / "existing.pdf"
    existing_bytes = valid_recipe_pdf_bytes()
    destination.write_bytes(existing_bytes)

    class FakeDriver:
        page_source = "<html><body>Papa Potato a la Huancaina</body></html>"
        current_url = ""
        title = "Papa Potato a la Huancaina"

        def set_page_load_timeout(self, _timeout):
            return None

        def get(self, target):
            self.current_url = target

        def quit(self):
            return None

    monkeypatch.setattr(recipe_extract_service, "create_headless_chrome_driver", lambda **_kwargs: FakeDriver())
    monkeypatch.setattr(recipe_extract_service, "prepare_page_for_pdf_print", lambda _driver: None)
    monkeypatch.setattr(
        recipe_extract_service,
        "print_current_browser_page_to_pdf",
        lambda _driver, path: Path(path).write_bytes(one_page_text_pdf("Unrelated document")),
    )

    with pytest.raises(RuntimeError, match="expected recipe title"):
        recipe_extract_service.write_recipe_page_pdf(
            PISCO_URL,
            "<html><body><h1>Papa Potato a la Huancaina</h1></body></html>",
            None,
            destination,
            expected_recipe=EXPECTED_RECIPE,
        )

    assert destination.read_bytes() == existing_bytes
    assert not list(temp_folder.glob("*.html"))
    assert not list(destination.parent.glob(".*.pdf"))


def test_new_long_recipe_internal_filenames_do_not_collide(monkeypatch, tmp_path):
    output_folder, pdf_folder, _temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    shared_prefix = "https://example.test/recipes/" + ("same-path-segment-" * 12)
    first_url = shared_prefix + "first"
    second_url = shared_prefix + "second"

    assert recipe_extract_service.safe_filename(first_url) == recipe_extract_service.safe_filename(second_url)
    assert recipe_extract_service.recipe_internal_filename(first_url) != recipe_extract_service.recipe_internal_filename(second_url)
    assert len(recipe_extract_service.recipe_internal_filename(first_url)) <= 80
    assert recipe_extract_service.recipe_output_json_path(first_url).parent == output_folder
    assert recipe_extract_service.recipe_output_json_path(first_url) != recipe_extract_service.recipe_output_json_path(second_url)
    assert recipe_extract_service.generated_recipe_pdf_path(first_url).parent == pdf_folder
    assert recipe_extract_service.generated_recipe_pdf_path(first_url) != recipe_extract_service.generated_recipe_pdf_path(second_url)


def test_existing_long_recipe_keeps_legacy_local_and_public_filename(monkeypatch, tmp_path):
    output_folder, pdf_folder, _temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    legacy_stem = recipe_extract_service.safe_filename(PISCO_URL)
    legacy_output = output_folder / f"{legacy_stem}.json"
    legacy_output.write_text(json.dumps({"source_url": PISCO_URL}), encoding="utf-8")

    assert recipe_extract_service.recipe_internal_filename(PISCO_URL) == legacy_stem
    assert recipe_extract_service.recipe_output_json_path(PISCO_URL) == legacy_output
    assert recipe_extract_service.generated_recipe_pdf_path(PISCO_URL) == (
        pdf_folder / f"{legacy_stem}_generated_recipe.pdf"
    )
    assert recipe_extract_service.legacy_recipe_pdf_path(
        PISCO_URL,
        recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
    ).name == f"{legacy_stem}_generated_recipe.pdf"


def test_new_long_recipe_upload_uses_collision_safe_key(monkeypatch, tmp_path):
    output_folder, _pdf_folder, _temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    shared_prefix = "https://example.test/recipes/" + ("same-path-segment-" * 12)
    first_url = shared_prefix + "first"
    second_url = shared_prefix + "second"
    captured_keys = []

    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "has_any_r2_config",
        lambda: True,
    )
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda _path, **kwargs: captured_keys.append(kwargs["object_key"])
        or {"ok": False, "code": "test_stop", "error": "stop after key capture"},
    )
    for url in (first_url, second_url):
        recipe_extract_service.recipe_archive_pdf_path(url).write_bytes(valid_recipe_pdf_bytes())
        recipe_extract_service.maybe_upload_recipe_archive_pdf_to_cloudflare(url)

    assert not list(output_folder.glob("*.json"))
    assert len(captured_keys) == len(set(captured_keys)) == 2
    assert all(key.startswith("recipe-pdfs/") for key in captured_keys)
    assert all(key.endswith(".pdf") for key in captured_keys)


def test_existing_long_recipe_upload_preserves_legacy_object_key(monkeypatch, tmp_path):
    output_folder, _pdf_folder, _temp_folder = configure_pdf_paths(monkeypatch, tmp_path)
    legacy_stem = recipe_extract_service.safe_filename(PISCO_URL)
    (output_folder / f"{legacy_stem}.json").write_text(
        json.dumps({"source_url": PISCO_URL}),
        encoding="utf-8",
    )
    recipe_extract_service.recipe_archive_pdf_path(PISCO_URL).write_bytes(valid_recipe_pdf_bytes())
    captured = {}
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "has_any_r2_config",
        lambda: True,
    )
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda _path, **kwargs: captured.update(kwargs)
        or {"ok": False, "code": "test_stop", "error": "stop after key capture"},
    )

    recipe_extract_service.maybe_upload_recipe_archive_pdf_to_cloudflare(PISCO_URL)

    assert captured["object_key"] == f"recipe-pdfs/{legacy_stem}.pdf"
