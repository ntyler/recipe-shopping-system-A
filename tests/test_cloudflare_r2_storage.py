import json
from datetime import datetime
from datetime import timezone
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
        self.list_pages = {}
        self.list_calls = []

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

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        prefix = kwargs.get("Prefix", "")
        token = kwargs.get("ContinuationToken", "")
        pages = self.list_pages.get(prefix, [])
        index = int(token or 0)
        page = pages[index] if index < len(pages) else {"Contents": []}

        if index + 1 < len(pages):
            return {
                **page,
                "IsTruncated": True,
                "NextContinuationToken": str(index + 1),
            }

        return {
            **page,
            "IsTruncated": False,
        }


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


def test_list_pdf_objects_paginates_allowed_prefixes(monkeypatch):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    fake_client.list_pages = {
        "recipe-pdfs/": [
            {
                "Contents": [
                    {
                        "Key": "recipe-pdfs/linked.pdf",
                        "Size": 1200,
                        "LastModified": datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
                        "ETag": '"abc"',
                    },
                    {"Key": "recipe-pdfs/not-a-pdf.txt", "Size": 20},
                ],
            },
            {
                "Contents": [
                    {
                        "Key": "recipe-pdfs/orphan.pdf",
                        "Size": 2400,
                    },
                ],
            },
        ],
        "menu-pdfs/": [
            {
                "Contents": [
                    {
                        "Key": "menu-pdfs/menu.pdf",
                        "Size": 4800,
                    },
                ],
            },
        ],
    }
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.list_pdf_objects()

    assert result["ok"] is True
    assert [row["object_key"] for row in result["objects"]] == [
        "menu-pdfs/menu.pdf",
        "recipe-pdfs/linked.pdf",
        "recipe-pdfs/orphan.pdf",
    ]
    assert result["objects"][1]["public_url"] == "https://public.example.com/recipe-pdfs/linked.pdf"
    assert result["objects"][1]["last_modified"] == "2026-06-01T12:30:00Z"
    assert [call["Prefix"] for call in fake_client.list_calls] == [
        "recipe-pdfs/",
        "recipe-pdfs/",
        "menu-pdfs/",
    ]


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
    assert saved["source_pdf_path"] == str(pdf_path)
    assert saved["source_cloudflare_pdf_url"] == result["pdf_public_url"]
    assert saved["source_cloudflare_pdf_path"] == result["pdf_public_url"]
    assert saved["webpage_backup_pdf_path"] == str(pdf_path)
    assert saved["webpage_backup_pdf_url"] == result["pdf_public_url"]


def test_generated_pdf_upload_saves_generated_fields_without_overwriting_source(monkeypatch, tmp_path):
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
        lambda: False,
    )
    url = "https://example.com/recipes/tacos"
    source_path = "D:/recipes/source-backup.pdf"
    source_url = "https://public.example.com/recipe-pdfs/source-backup.pdf"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Tacos",
        "ingredients": [],
        "source_pdf_path": source_path,
        "source_cloudflare_pdf_url": source_url,
    })
    generated_path = recipe_extract_service.generated_recipe_pdf_path(url)
    generated_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = recipe_edit_service.upload_recipe_pdf_to_cloudflare(
        url,
        pdf_kind=recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
    )
    saved = recipe_edit_service.load_recipe_output(url)

    assert result["ok"] is True
    assert saved["source_pdf_path"] == source_path
    assert saved["source_cloudflare_pdf_url"] == source_url
    assert saved["source_cloudflare_pdf_path"] == source_url
    assert saved["generated_pdf_path"] == str(generated_path)
    assert saved["generated_cloudflare_pdf_url"] == result["pdf_public_url"]
    assert saved["generated_cloudflare_pdf_path"] == result["pdf_public_url"]
    assert saved["generated_recipe_pdf_path"] == str(generated_path)
    assert saved["generated_recipe_pdf_url"] == result["pdf_public_url"]


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
    assert json_data["source_url"] == url
    assert json_data["source_pdf_path"] == str(recipe_extract_service.recipe_archive_pdf_path(url))
    assert json_data["source_cloudflare_pdf_url"] == (
        "https://public.example.com/recipe-pdfs/example_com_recipes_tacos.pdf"
    )
    assert json_data["source_cloudflare_pdf_path"] == (
        "https://public.example.com/recipe-pdfs/example_com_recipes_tacos.pdf"
    )
    assert json_data.get("generated_pdf_path", "") == ""
    assert json_data.get("generated_cloudflare_pdf_url", "") == ""


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
    assert saved["source_pdf_path"] == str(pdf_path)
    assert saved["source_cloudflare_pdf_url"] == (
        "https://public.example.com/recipe-pdfs/uploaded_sample_doc.pdf"
    )
    assert saved["source_cloudflare_pdf_path"] == (
        "https://public.example.com/recipe-pdfs/uploaded_sample_doc.pdf"
    )
    assert saved.get("generated_pdf_path", "") == ""
    assert saved.get("generated_cloudflare_pdf_url", "") == ""
    assert not pdf_path.exists()


def test_legacy_pdf_fields_load_as_source_pdf_fields(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "recipe_cookbook_assignments", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {})
    url = "https://example.com/recipes/legacy"
    legacy_pdf_path = "D:/legacy/source.pdf"
    legacy_cloudflare_url = "https://public.example.com/recipe-pdfs/legacy.pdf"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Legacy Recipe",
        "ingredients": [],
        "instructions": [],
        "pdf_path": legacy_pdf_path,
        "cloudflare_pdf_url": legacy_cloudflare_url,
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["source_pdf_path"] == legacy_pdf_path
    assert loaded["source_cloudflare_pdf_url"] == legacy_cloudflare_url
    assert loaded["source_cloudflare_pdf_path"] == legacy_cloudflare_url
    assert loaded["generated_pdf_path"] == ""
    assert loaded["generated_cloudflare_pdf_url"] == ""
    assert loaded["generated_cloudflare_pdf_path"] == ""


def test_split_pdf_payload_can_explicitly_clear_legacy_aliases():
    recipe_data = {
        "source_pdf_path": "D:/source.pdf",
        "source_cloudflare_pdf_url": "https://public.example.com/source.pdf",
        "source_cloudflare_pdf_path": "https://public.example.com/source.pdf",
        "webpage_backup_pdf_path": "D:/source.pdf",
        "webpage_backup_pdf_url": "https://public.example.com/source.pdf",
        "pdf_path": "D:/source.pdf",
        "cloudflare_pdf_url": "https://public.example.com/source.pdf",
        "generated_pdf_path": "D:/generated.pdf",
        "generated_cloudflare_pdf_url": "https://public.example.com/generated.pdf",
        "generated_cloudflare_pdf_path": "https://public.example.com/generated.pdf",
        "generated_recipe_pdf_path": "D:/generated.pdf",
        "generated_recipe_pdf_url": "https://public.example.com/generated.pdf",
    }

    recipe_edit_service.apply_recipe_pdf_asset_payload(recipe_data, {
        "source_pdf_path": "",
        "source_cloudflare_pdf_url": "",
        "generated_pdf_path": "",
        "generated_cloudflare_pdf_url": "",
    })

    assert recipe_data["source_pdf_path"] == ""
    assert recipe_data["source_cloudflare_pdf_url"] == ""
    assert recipe_data["source_cloudflare_pdf_path"] == ""
    assert recipe_data["pdf_path"] == ""
    assert recipe_data["cloudflare_pdf_url"] == ""
    assert recipe_data["generated_pdf_path"] == ""
    assert recipe_data["generated_cloudflare_pdf_url"] == ""
    assert recipe_data["generated_cloudflare_pdf_path"] == ""
    assert recipe_data["generated_recipe_pdf_path"] == ""
    assert recipe_data["generated_recipe_pdf_url"] == ""
