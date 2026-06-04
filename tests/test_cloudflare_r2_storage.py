import json
from pathlib import Path

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service


R2_ENV = {
    "R2_ACCOUNT_ID": "account-id",
    "R2_ENDPOINT": "https://account-id.r2.cloudflarestorage.com",
    "R2_ACCESS_KEY_ID": "access-key",
    "R2_SECRET_ACCESS_KEY": "secret-key",
    "R2_BUCKET_NAME": "recipe-shopping-pdfs",
    "R2_PUBLIC_BASE_URL": "https://public.example.com",
}


class FakeR2Client:
    def __init__(self):
        self.uploads = []
        self.deletes = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploads.append({
            "filename": filename,
            "bucket": bucket,
            "key": key,
            "extra_args": ExtraArgs or {},
        })

    def delete_object(self, Bucket, Key):
        self.deletes.append({
            "bucket": Bucket,
            "key": Key,
        })


def set_r2_env(monkeypatch):
    for key, value in R2_ENV.items():
        monkeypatch.setenv(key, value)


def write_sample_pdf(tmp_path, filename="sample.pdf"):
    path = tmp_path / filename
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return path


def test_upload_pdf_reports_missing_environment(monkeypatch, tmp_path):
    for key in R2_ENV:
        monkeypatch.delenv(key, raising=False)

    result = cloudflare_r2_storage.upload_pdf(write_sample_pdf(tmp_path))

    assert result["ok"] is False
    assert result["code"] == "missing_env"
    assert "R2_" in result["error"]


def test_upload_pdf_uses_recipe_pdf_prefix(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    sample_pdf = write_sample_pdf(tmp_path, "enchiladas.pdf")

    monkeypatch.setattr(cloudflare_r2_storage, "object_exists", lambda object_key: False)
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.upload_pdf(sample_pdf)

    assert result["ok"] is True
    assert result["object_key"] == "recipe-pdfs/enchiladas.pdf"
    assert result["public_url"] == "https://public.example.com/recipe-pdfs/enchiladas.pdf"
    assert fake_client.uploads[0]["bucket"] == "recipe-shopping-pdfs"
    assert fake_client.uploads[0]["extra_args"]["ContentType"] == "application/pdf"


def test_upload_pdf_rejects_duplicate_object(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    monkeypatch.setattr(cloudflare_r2_storage, "object_exists", lambda object_key: True)

    result = cloudflare_r2_storage.upload_pdf(write_sample_pdf(tmp_path, "dupe.pdf"))

    assert result["ok"] is False
    assert result["code"] == "duplicate_object"
    assert result["object_key"] == "recipe-pdfs/dupe.pdf"
    assert result["public_url"] == "https://public.example.com/recipe-pdfs/dupe.pdf"


def test_delete_pdf_uses_configured_bucket(monkeypatch):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.delete_pdf("recipe-pdfs/enchiladas.pdf")

    assert result["ok"] is True
    assert fake_client.deletes == [{
        "bucket": "recipe-shopping-pdfs",
        "key": "recipe-pdfs/enchiladas.pdf",
    }]


def test_recipe_pdf_upload_saves_metadata_and_deletes_local(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda path: {
            "ok": True,
            "object_key": f"recipe-pdfs/{Path(path).name}",
            "public_url": f"https://public.example.com/recipe-pdfs/{Path(path).name}",
            "bucket": "recipe-shopping-pdfs",
        },
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "delete_local_pdf_after_upload",
        lambda: True,
    )
    url = "manual://recipe/test"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Test Recipe",
        "ingredients": [],
    })
    pdf_path = recipe_extract_service.recipe_archive_pdf_path(url)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = recipe_edit_service.upload_recipe_pdf_to_cloudflare(url)
    saved = recipe_edit_service.load_recipe_output(url)

    assert result["ok"] is True
    assert result["pdf_public_url"].endswith("/recipe-pdfs/manual_recipe_test.pdf")
    assert result["deleted_local_pdf"] is True
    assert not pdf_path.exists()
    assert saved["pdf"]["cloudflare_r2"]["object_key"] == "recipe-pdfs/manual_recipe_test.pdf"
    assert saved["pdf"]["cloudflare_r2"]["public_url"] == result["pdf_public_url"]


def test_url_import_json_save_auto_uploads_archive_to_cloudflare(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    set_r2_env(monkeypatch)
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda path: {
            "ok": True,
            "object_key": f"recipe-pdfs/{Path(path).name}",
            "public_url": f"https://public.example.com/recipe-pdfs/{Path(path).name}",
            "bucket": "recipe-shopping-pdfs",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "delete_local_pdf_after_upload",
        lambda: False,
    )
    url = "https://example.com/recipes/tacos"
    recipe_extract_service.recipe_archive_pdf_path(url).write_bytes(b"%PDF-1.4\n%%EOF\n")

    ok, json_data = recipe_extract_service.save_json_response(
        url,
        '{"recipe_title":"Tacos","ingredients":["beans"],"instructions":["cook"]}',
    )

    assert ok is True
    assert json_data["pdf"]["cloudflare_r2"]["object_key"] == "recipe-pdfs/example_com_recipes_tacos.pdf"
    assert json_data["pdf"]["cloudflare_r2"]["public_url"] == (
        "https://public.example.com/recipe-pdfs/example_com_recipes_tacos.pdf"
    )


def test_uploaded_doc_save_auto_uploads_archive_and_can_delete_local(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    set_r2_env(monkeypatch)
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda path: {
            "ok": True,
            "object_key": f"recipe-pdfs/{Path(path).name}",
            "public_url": f"https://public.example.com/recipe-pdfs/{Path(path).name}",
            "bucket": "recipe-shopping-pdfs",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "delete_local_pdf_after_upload",
        lambda: True,
    )
    url = "uploaded://sample_doc"
    pdf_path = recipe_extract_service.recipe_archive_pdf_path(url)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    recipe_extract_service.save_extracted_recipe_json(
        url,
        {
            "source_url": url,
            "recipe_title": "Sample Doc",
            "ingredients": ["flour"],
            "instructions": ["mix"],
        },
    )
    saved = json.loads((output_dir / "uploaded_sample_doc.json").read_text(encoding="utf-8"))

    assert saved["pdf"]["cloudflare_r2"]["object_key"] == "recipe-pdfs/uploaded_sample_doc.pdf"
    assert saved["pdf"]["cloudflare_r2"]["public_url"] == (
        "https://public.example.com/recipe-pdfs/uploaded_sample_doc.pdf"
    )
    assert not pdf_path.exists()
