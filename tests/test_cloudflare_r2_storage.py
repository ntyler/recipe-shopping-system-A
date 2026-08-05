import hashlib
import io
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
        self.objects = {}
        self.head_calls = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        pdf_bytes = Path(filename).read_bytes()
        extra_args = ExtraArgs or {}
        return self._store_object(
            pdf_bytes,
            bucket,
            key,
            extra_args.get("ContentType", ""),
            extra_args.get("Metadata", {}),
            extra_args,
        )

    def _precondition_error(self):
        error = RuntimeError("precondition failed")
        error.response = {
            "Error": {"Code": "PreconditionFailed"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        }
        return error

    def put_object(
        self,
        Body,
        Bucket,
        Key,
        ContentType="",
        ContentLength=None,
        Metadata=None,
        IfNoneMatch=None,
        IfMatch=None,
    ):
        if IfNoneMatch == "*" and Key in self.objects:
            raise self._precondition_error()
        if IfMatch is not None:
            current = str(self.objects.get(Key, {}).get("ETag") or "").strip('"')
            if not current or current != str(IfMatch).strip('"'):
                raise self._precondition_error()
        pdf_bytes = Body.read() if hasattr(Body, "read") else bytes(Body)
        return self._store_object(
            pdf_bytes,
            Bucket,
            Key,
            ContentType,
            Metadata or {},
            {
                "ContentType": ContentType,
                "ContentLength": ContentLength,
                "Metadata": Metadata or {},
                "IfNoneMatch": IfNoneMatch,
                "IfMatch": IfMatch,
            },
        )

    def _store_object(self, pdf_bytes, bucket, key, content_type, metadata, extra_args):
        self.uploads.append({
            "bucket": bucket,
            "key": key,
            "extra_args": extra_args,
        })
        self.objects[key] = {
            "BodyBytes": pdf_bytes,
            "ContentLength": len(pdf_bytes),
            "ContentType": content_type,
            "Metadata": metadata,
            "ETag": f'"{hashlib.md5(pdf_bytes).hexdigest()}"',
            "LastModified": datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
        }

    def head_object(self, Bucket, Key):
        self.head_calls.append({"bucket": Bucket, "key": Key})
        if Key in self.objects:
            return self.objects[Key]

        error = RuntimeError("not found")
        error.response = {
            "Error": {"Code": "NoSuchKey"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }
        raise error

    def get_object(self, Bucket, Key, Range=None, IfMatch=None):
        if Key not in self.objects:
            return self.head_object(Bucket=Bucket, Key=Key)
        if IfMatch is not None:
            current = str(self.objects[Key].get("ETag") or "").strip('"')
            if current != str(IfMatch).strip('"'):
                raise self._precondition_error()
        data = self.objects[Key].get("BodyBytes", b"")
        content_range = ""
        if Range:
            end = int(str(Range).split("-")[-1])
            data = data[: end + 1]
            content_range = f"bytes 0-{max(len(data) - 1, 0)}/{len(self.objects[Key].get('BodyBytes', b''))}"
        return {
            "Body": io.BytesIO(data),
            "ETag": self.objects[Key].get("ETag", ""),
            "ContentRange": content_range,
        }

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


def semantic_validation(path, *, sha256=None):
    path = Path(path)
    return {
        "ok": True,
        "semantic_validation_required": True,
        "validation_version": recipe_extract_service.PDF_VALIDATION_VERSION,
        "sha256": sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def configure_recipe_editor_pdf_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_name", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "sync_saved_recipe_with_shopping_list", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "replace_recipe_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "move_recipe_meta", lambda *args, **kwargs: None)

    return output_dir, pdf_dir


def editable_recipe_pdf_payload(source_url, **overrides):
    payload = {
        "source_url": source_url,
        "display_name": "Chili",
        "recipe_title": "Chili",
        "quantity": 1,
        "servings": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "scaling": {},
        "ingredients": [{"ingredient": "beans", "quantity": "1", "unit": "can"}],
        "equipment": [],
        "instructions": [{"instruction": "Simmer."}],
        "nutrition": [],
        "rating": 0,
        "reflection_notes": [],
    }
    payload.update(overrides)
    return payload


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
    fake_client = FakeR2Client()
    sample_pdf = write_sample_pdf(tmp_path, "dupe.pdf")
    fake_client.upload_file(
        str(sample_pdf),
        R2_ENV["R2_BUCKET_NAME"],
        "recipe-pdfs/dupe.pdf",
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.upload_pdf(sample_pdf)

    assert result["ok"] is False
    assert result["code"] == "duplicate_object"
    assert result["object_key"] == "recipe-pdfs/dupe.pdf"
    assert result["public_url"] == "https://public.example.com/recipe-pdfs/dupe.pdf"


def test_upload_pdf_explicit_validated_overwrite_keeps_key_and_verifies(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    object_key = "recipe-pdfs/stable.pdf"
    fake_client.objects[object_key] = {
        "ContentLength": 3,
        "ContentType": "application/pdf",
        "Metadata": {"sha256": "old"},
        "ETag": '"old"',
        "LastModified": datetime(2026, 5, 1, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)
    sample_pdf = write_sample_pdf(tmp_path, "new-local-name.pdf")
    sha256 = hashlib.sha256(sample_pdf.read_bytes()).hexdigest()

    result = cloudflare_r2_storage.upload_pdf(
        sample_pdf,
        object_key=object_key,
        overwrite=True,
        validated=True,
        validation=semantic_validation(sample_pdf, sha256=sha256),
    )

    assert result["ok"] is True
    assert result["verified"] is True
    assert result["overwritten"] is True
    assert result["object_key"] == object_key
    assert result["public_url"] == "https://public.example.com/recipe-pdfs/stable.pdf"
    assert fake_client.uploads[-1]["key"] == object_key
    assert fake_client.uploads[-1]["extra_args"]["Metadata"]["sha256"] == sha256


def test_upload_pdf_overwrite_requires_validation_and_matching_bytes(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)
    sample_pdf = write_sample_pdf(tmp_path, "candidate.pdf")

    unvalidated = cloudflare_r2_storage.upload_pdf(
        sample_pdf,
        object_key="recipe-pdfs/stable.pdf",
        overwrite=True,
    )
    changed_after_validation = cloudflare_r2_storage.upload_pdf(
        sample_pdf,
        object_key="recipe-pdfs/stable.pdf",
        overwrite=True,
        validated=True,
        validation=semantic_validation(sample_pdf, sha256="0" * 64),
    )

    assert unvalidated["code"] == "overwrite_requires_validation"
    assert changed_after_validation["code"] == "validation_mismatch"
    assert fake_client.uploads == []


def test_upload_pdf_overwrite_refuses_stale_expected_etag(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    sample_pdf = write_sample_pdf(tmp_path, "conditional.pdf")
    key = "recipe-pdfs/conditional.pdf"
    fake_client.upload_file(str(sample_pdf), R2_ENV["R2_BUCKET_NAME"], key)
    original_bytes = fake_client.objects[key]["BodyBytes"]
    replacement = write_sample_pdf(tmp_path, "replacement.pdf")
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.upload_pdf(
        replacement,
        object_key=key,
        overwrite=True,
        expected_etag="stale-etag",
        validated=True,
        validation=semantic_validation(replacement),
    )

    assert result["ok"] is False
    assert result["code"] == "overwrite_precondition_failed"
    assert fake_client.objects[key]["BodyBytes"] == original_bytes


def test_upload_pdf_reports_remote_mutation_when_post_write_head_fails(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    original = write_sample_pdf(tmp_path, "original.pdf")
    replacement = write_sample_pdf(tmp_path, "replacement-verified.pdf")
    key = "recipe-pdfs/post-write-head.pdf"
    fake_client.upload_file(str(original), R2_ENV["R2_BUCKET_NAME"], key)
    old_etag = str(fake_client.objects[key]["ETag"]).strip('"')
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "head_pdf_object",
        lambda _key: {"ok": False, "exists": False, "error": "temporary HEAD outage"},
    )

    result = cloudflare_r2_storage.upload_pdf(
        replacement,
        object_key=key,
        overwrite=True,
        expected_etag=old_etag,
        validated=True,
        validation=semantic_validation(replacement),
    )

    assert result["code"] == "upload_verification_failed"
    assert result["remote_write_succeeded"] is True
    assert result["remote_repaired"] is True
    assert fake_client.objects[key]["BodyBytes"] == replacement.read_bytes()


def test_upload_pdf_marks_non_precondition_put_exception_as_mutation_unknown(
    monkeypatch,
    tmp_path,
):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    original = write_sample_pdf(tmp_path, "unknown-original.pdf")
    replacement = write_sample_pdf(tmp_path, "unknown-replacement.pdf")
    key = "recipe-pdfs/unknown-put-outcome.pdf"
    fake_client.upload_file(str(original), R2_ENV["R2_BUCKET_NAME"], key)
    old_etag = str(fake_client.objects[key]["ETag"]).strip('"')

    def ambiguous_put(**_kwargs):
        raise TimeoutError("response timed out after request transmission")

    monkeypatch.setattr(fake_client, "put_object", ambiguous_put)
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.upload_pdf(
        replacement,
        object_key=key,
        overwrite=True,
        expected_etag=old_etag,
        validated=True,
        validation=semantic_validation(replacement),
    )

    assert result["ok"] is False
    assert result["code"] == "upload_outcome_unknown"
    assert result["remote_mutation_unknown"] is True
    assert result["remote_repaired"] is False
    assert result["expected_etag"] == old_etag


def test_read_pdf_object_bytes_is_explicit_and_supports_bounded_reads(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)
    sample_pdf = write_sample_pdf(tmp_path, "audit.pdf")
    fake_client.upload_file(
        str(sample_pdf),
        R2_ENV["R2_BUCKET_NAME"],
        "recipe-pdfs/audit.pdf",
        ExtraArgs={"ContentType": "application/pdf", "Metadata": {}},
    )

    result = cloudflare_r2_storage.read_pdf_object_bytes(
        "recipe-pdfs/audit.pdf",
        max_bytes=5,
    )

    assert result["ok"] is True
    assert result["bytes"] == b"%PDF-"
    assert result["size_bytes"] == 5
    assert result["content_range"].startswith("bytes 0-4/")


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


def test_delete_pdf_object_allows_bucket_listed_pdf_paths(monkeypatch):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.delete_pdf_object("archive/menu.pdf")

    assert result["ok"] is True
    assert result["public_url"] == "https://public.example.com/archive/menu.pdf"
    assert fake_client.deletes == [{
        "bucket": "recipe-shopping-pdfs",
        "key": "archive/menu.pdf",
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


def test_list_all_pdf_objects_scans_bucket_and_filters_pdfs(monkeypatch):
    set_r2_env(monkeypatch)
    fake_client = FakeR2Client()
    fake_client.list_pages = {
        "": [
            {
                "Contents": [
                    {
                        "Key": "recipe-pdfs/source.pdf",
                        "Size": 100,
                    },
                    {
                        "Key": "other/generated.PDF",
                        "Size": 200,
                    },
                    {
                        "Key": "other/not-a-pdf.txt",
                        "Size": 300,
                    },
                ],
            },
            {
                "Contents": [
                    {
                        "Key": "archive/menu.pdf",
                        "Size": 400,
                        "LastModified": datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
                    },
                ],
            },
        ],
    }
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: fake_client)

    result = cloudflare_r2_storage.list_all_pdf_objects()

    assert result["ok"] is True
    assert result["scope"] == "bucket"
    assert [row["object_key"] for row in result["objects"]] == [
        "archive/menu.pdf",
        "other/generated.PDF",
        "recipe-pdfs/source.pdf",
    ]
    assert result["objects"][1]["public_url"] == "https://public.example.com/other/generated.PDF"
    assert "Prefix" not in fake_client.list_calls[0]


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
        lambda path, **kwargs: {
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
        lambda path, **kwargs: {
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
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *args, **kwargs: {"ok": True, "sha256": "test-validation"},
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


def test_generated_pdf_validation_failure_never_reaches_r2(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/browser-error"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Browser Error",
        "ingredients": [{"ingredient": "beans"}],
        "instructions": [{"instruction": "Cook."}],
    })
    pdf_path = recipe_extract_service.generated_recipe_pdf_path(url)
    pdf_path.write_bytes(b"%PDF-1.4\nERR_FILE_NOT_FOUND\n%%EOF\n")
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *args, **kwargs: {
            "ok": False,
            "error": "PDF contains a Chrome ERR_FILE_NOT_FOUND page.",
        },
    )

    def fail_if_uploaded(*args, **kwargs):
        raise AssertionError("invalid generated PDF reached R2 upload")

    monkeypatch.setattr(recipe_edit_service.cloudflare_r2_storage, "upload_pdf", fail_if_uploaded)

    result = recipe_edit_service.upload_recipe_pdf_to_cloudflare(
        url,
        pdf_kind=recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
    )

    assert result["ok"] is False
    assert result["code"] == "invalid_pdf"
    assert "ERR_FILE_NOT_FOUND" in result["error"]


def test_duplicate_object_does_not_refresh_uploaded_at_or_delete_local(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/stable"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    old_uploaded_at = "2025-01-02T03:04:05Z"
    object_key = "recipe-pdfs/example_com_recipes_stable_generated_recipe.pdf"
    public_url = f"https://public.example.com/{object_key}"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Stable",
        "ingredients": [{"ingredient": "beans"}],
        "instructions": [{"instruction": "Cook."}],
        "pdf": {
            kind: {
                "local_path": str(recipe_extract_service.generated_recipe_pdf_path(url)),
                "r2_object_key": object_key,
                "r2_public_url": public_url,
                "uploaded_at": old_uploaded_at,
                "cloud_status": "uploaded",
                "cloudflare_r2": {
                    "object_key": object_key,
                    "public_url": public_url,
                    "uploaded_at": old_uploaded_at,
                    "cloud_status": "uploaded",
                },
            },
        },
    })
    pdf_path = recipe_extract_service.generated_recipe_pdf_path(url)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    duplicate_validation = semantic_validation(pdf_path)
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *args, **kwargs: duplicate_validation,
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda path, **kwargs: {
            "ok": False,
            "code": "duplicate_object",
            "object_key": object_key,
            "public_url": public_url,
            "error": "already exists",
        },
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "head_pdf_object",
        lambda key: {
            "ok": True,
            "exists": True,
            "object_key": key,
            "public_url": public_url,
            "uploaded_at": "2026-08-04T12:00:00Z",
            "etag": "remote-etag",
            "sha256": duplicate_validation["sha256"],
            "size_bytes": pdf_path.stat().st_size,
        },
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "delete_local_pdf_after_upload",
        lambda: True,
    )

    result = recipe_edit_service.upload_recipe_pdf_to_cloudflare(url, pdf_kind=kind)
    saved = recipe_edit_service.load_recipe_output(url)

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["fresh_upload"] is False
    assert result["uploaded_at"] == old_uploaded_at
    assert saved["pdf"][kind]["uploaded_at"] == old_uploaded_at
    assert pdf_path.exists()


def test_missing_cached_object_self_heals_from_valid_local_pdf_same_key(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/self-heal"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    object_key = "recipe-pdfs/legacy-self-heal_generated_recipe.pdf"
    public_url = f"https://public.example.com/{object_key}"
    pdf_path = recipe_extract_service.generated_recipe_pdf_path(url)
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Self Heal",
        "ingredients": [{"ingredient": "beans"}],
        "instructions": [{"instruction": "Cook."}],
        "generated_pdf_path": str(pdf_path),
        "pdf": {
            kind: {
                "local_path": str(pdf_path),
                "r2_object_key": object_key,
                "r2_public_url": public_url,
                "uploaded_at": "2025-01-02T03:04:05Z",
                "cloud_status": "uploaded",
                "cloudflare_r2": {
                    "object_key": object_key,
                    "public_url": public_url,
                    "uploaded_at": "2025-01-02T03:04:05Z",
                    "cloud_status": "uploaded",
                },
            },
        },
    })
    pdf_path.write_bytes(b"%PDF-1.4\nvalidated recipe\n%%EOF\n")
    validation = {
        "ok": True,
        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "page_count": 1,
    }
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "head_pdf_object",
        lambda key: {"ok": True, "exists": False, "code": "not_found", "object_key": key},
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *args, **kwargs: validation,
    )
    uploads = []

    def fake_upload(path, **kwargs):
        uploads.append({"path": Path(path), **kwargs})
        return {
            "ok": True,
            "verified": True,
            "object_key": kwargs["object_key"],
            "public_url": public_url,
            "bucket": "recipe-shopping-pdfs",
            "uploaded_at": "2026-08-04T12:00:00Z",
            "etag": "repaired-etag",
            "sha256": validation["sha256"],
            "size_bytes": Path(path).stat().st_size,
        }

    monkeypatch.setattr(recipe_edit_service.cloudflare_r2_storage, "upload_pdf", fake_upload)

    result = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)

    assert result["ok"] is True
    assert result["repaired"] is True
    assert result["cached"] is False
    assert result["pdf_public_url"] == public_url
    assert uploads[0]["object_key"] == object_key
    assert uploads[0]["overwrite"] is False
    assert uploads[0]["validated"] is True


def test_missing_cached_object_reports_metadata_failure_after_verified_self_heal(
    monkeypatch,
    tmp_path,
):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/self-heal-metadata-failure"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    object_key = "recipe-pdfs/self-heal-metadata-failure_generated_recipe.pdf"
    public_url = f"https://public.example.com/{object_key}"
    pdf_path = recipe_extract_service.generated_recipe_pdf_path(url)
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Self Heal Metadata Failure",
        "ingredients": [{"ingredient": "beans"}],
        "instructions": [{"instruction": "Cook."}],
        "generated_pdf_path": str(pdf_path),
        "pdf": {
            kind: {
                "local_path": str(pdf_path),
                "r2_object_key": object_key,
                "r2_public_url": public_url,
                "uploaded_at": "2025-01-02T03:04:05Z",
                "cloud_status": "uploaded",
            },
        },
    })
    pdf_path.write_bytes(b"%PDF-1.4\nvalidated recipe\n%%EOF\n")
    validation = {
        "ok": True,
        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "page_count": 1,
    }
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "head_pdf_object",
        lambda key: {"ok": True, "exists": False, "code": "not_found", "object_key": key},
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *args, **kwargs: validation,
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda path, **kwargs: {
            "ok": True,
            "verified": True,
            "object_key": kwargs["object_key"],
            "public_url": public_url,
            "etag": "repaired-etag",
            "sha256": validation["sha256"],
            "size_bytes": Path(path).stat().st_size,
        },
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_pdf_storage_metadata",
        lambda *_args, **_kwargs: {"ok": False, "error": "disk full"},
    )

    result = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)

    assert result["ok"] is False
    assert result["code"] == "metadata_save_failed"
    assert result["remote_uploaded"] is True
    assert result["remote_verified"] is True
    assert result["repaired"] is False
    assert result["pdf_local_available"] is True
    assert pdf_path.exists()


def test_cached_link_uses_head_metadata_without_downloading_pdf(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/head-only"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    object_key = "recipe-pdfs/head-only_generated_recipe.pdf"
    public_url = f"https://public.example.com/{object_key}"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Head Only",
        "pdf": {
            kind: {
                "r2_object_key": object_key,
                "r2_public_url": public_url,
                "uploaded_at": "2026-08-04T12:00:00Z",
                "cloud_status": "uploaded",
                "etag": "same-etag",
                "sha256": "a" * 64,
                "size_bytes": 1234,
                "verified_at": "2026-08-04T12:01:00Z",
                "validation": {
                    "ok": True,
                    "semantic_validation_required": True,
                    "validation_version": recipe_extract_service.PDF_VALIDATION_VERSION,
                    "sha256": "a" * 64,
                    "size_bytes": 1234,
                },
                "cloudflare_r2": {
                    "object_key": object_key,
                    "public_url": public_url,
                    "uploaded_at": "2026-08-04T12:00:00Z",
                    "cloud_status": "uploaded",
                    "etag": "same-etag",
                    "sha256": "a" * 64,
                    "size_bytes": 1234,
                    "verified_at": "2026-08-04T12:01:00Z",
                },
            },
        },
    })
    head_calls = []

    def fake_head(key):
        head_calls.append(key)
        return {
            "ok": True,
            "exists": True,
            "object_key": key,
            "public_url": public_url,
            "etag": "same-etag",
            "size_bytes": 1234,
        }

    monkeypatch.setattr(recipe_edit_service.cloudflare_r2_storage, "head_pdf_object", fake_head)
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "read_pdf_object_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache opened PDF body")),
    )

    result = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)

    assert result["ok"] is True
    assert result["cached"] is True
    assert result["remote_verified"] is True
    assert head_calls == [object_key]


def test_legacy_cached_link_downloads_once_then_uses_head_only(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/legacy-valid"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    object_key = "recipe-pdfs/legacy-valid_generated_recipe.pdf"
    public_url = f"https://public.example.com/{object_key}"
    remote_bytes = b"%PDF-1.4\nsemantically validated remote recipe\n%%EOF\n"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Legacy Valid",
        "ingredients": [{"ingredient": "beans"}],
        "instructions": [{"instruction": "Cook."}],
        "generated_recipe_pdf_object_key": object_key,
        "generated_recipe_pdf_url": public_url,
        "generated_recipe_pdf_uploaded_at": "2025-01-02T03:04:05Z",
    })
    head = {
        "ok": True,
        "exists": True,
        "object_key": object_key,
        "public_url": public_url,
        "uploaded_at": "2025-01-02T03:04:05Z",
        "etag": "legacy-etag",
        "size_bytes": len(remote_bytes),
        "sha256": "",
    }
    reads = []
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "head_pdf_object",
        lambda _key: dict(head),
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "read_pdf_object_bytes",
        lambda key, **kwargs: reads.append((key, kwargs)) or {
            "ok": True,
            "object_key": key,
            "bytes": remote_bytes,
            "etag": "legacy-etag",
        },
    )

    def fake_validation(path, **_kwargs):
        return semantic_validation(path)

    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        fake_validation,
    )

    first = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)
    second = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)

    assert first["ok"] is True
    assert first["validation_promoted"] is True
    assert second["ok"] is True
    assert len(reads) == 1
    assert reads[0][1]["expected_etag"] == "legacy-etag"


def test_invalid_legacy_cached_link_persists_negative_etag_without_redownload(
    monkeypatch,
    tmp_path,
):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/legacy-corrupt"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    object_key = "recipe-pdfs/legacy-corrupt_generated_recipe.pdf"
    public_url = f"https://public.example.com/{object_key}"
    remote_bytes = b"%PDF-1.4\nERR_FILE_NOT_FOUND\n%%EOF\n"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Legacy Corrupt",
        "ingredients": [{"ingredient": "beans"}],
        "generated_recipe_pdf_object_key": object_key,
        "generated_recipe_pdf_url": public_url,
        "generated_recipe_pdf_uploaded_at": "2025-01-02T03:04:05Z",
    })
    head = {
        "ok": True,
        "exists": True,
        "object_key": object_key,
        "public_url": public_url,
        "uploaded_at": "2025-01-02T03:04:05Z",
        "etag": "corrupt-etag",
        "size_bytes": len(remote_bytes),
        "sha256": "",
    }
    reads = []
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "head_pdf_object",
        lambda _key: dict(head),
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "read_pdf_object_bytes",
        lambda key, **_kwargs: reads.append(key) or {
            "ok": True,
            "object_key": key,
            "bytes": remote_bytes,
        },
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda path, **_kwargs: {
            **semantic_validation(path),
            "ok": False,
            "error": "PDF contains ERR_FILE_NOT_FOUND.",
            "browser_error": True,
            "browser_error_code": "ERR_FILE_NOT_FOUND",
        },
    )

    first = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)
    second = recipe_edit_service.cached_recipe_pdf_cloudflare_result(url, pdf_kind=kind)

    assert first["code"] == "remote_pdf_invalid"
    assert second["code"] == "remote_pdf_invalid"
    assert reads == [object_key]


def test_generated_local_fallback_is_validated_when_r2_is_unconfigured(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/local-corrupt"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Local Corrupt",
        "ingredients": [{"ingredient": "beans"}],
    })
    recipe_extract_service.generated_recipe_pdf_path(url).write_bytes(
        b"%PDF-1.4\nERR_FILE_NOT_FOUND\n%%EOF\n"
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "has_required_r2_config",
        lambda: False,
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "has_any_r2_config",
        lambda: False,
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *_args, **_kwargs: {"ok": False, "error": "Chrome error PDF"},
    )

    result = recipe_edit_service.ensure_recipe_pdf_cloudflare_link(url, pdf_kind=kind)

    assert result["ok"] is False
    assert result["code"] == "local_pdf_invalid"


def test_verified_upload_metadata_failure_keeps_local_pdf(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/metadata-failure"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Metadata Failure",
        "ingredients": [{"ingredient": "beans"}],
    })
    pdf_path = recipe_extract_service.generated_recipe_pdf_path(url)
    pdf_path.write_bytes(b"%PDF-1.4\nvalidated\n%%EOF\n")
    validation = semantic_validation(pdf_path)
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *_args, **_kwargs: validation,
    )
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda *_args, **_kwargs: {
            "ok": True,
            "verified": True,
            "object_key": "recipe-pdfs/metadata-failure.pdf",
            "public_url": "https://public.example.com/recipe-pdfs/metadata-failure.pdf",
        },
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_pdf_storage_metadata",
        lambda *_args, **_kwargs: {"ok": False, "error": "disk full"},
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "delete_uploaded_local_pdf_if_configured",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local PDF was deleted after metadata failure")
        ),
    )

    result = recipe_edit_service.upload_local_pdf_path_to_cloudflare(
        pdf_path,
        url=url,
        pdf_kind=kind,
    )

    assert result["code"] == "metadata_save_failed"
    assert result["remote_uploaded"] is True
    assert pdf_path.exists()


def test_storage_metadata_write_exception_returns_actionable_failure(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/write-exception"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Write Exception",
        "ingredients": [{"ingredient": "beans"}],
    })
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("read-only disk")),
    )

    result = recipe_edit_service.save_recipe_pdf_storage_metadata(
        url,
        {
            "object_key": "recipe-pdfs/write-exception.pdf",
            "public_url": "https://public.example.com/recipe-pdfs/write-exception.pdf",
            "uploaded_at": "2026-08-04T12:00:00Z",
        },
        tmp_path / "write-exception.pdf",
        recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
    )

    assert result["ok"] is False
    assert result["code"] == "metadata_save_failed"
    assert "read-only disk" in result["error"]


def test_url_aware_upload_uses_collision_safe_public_key_for_new_long_url(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/" + ("very-long-segment-" * 12) + "finish"
    kind = recipe_extract_service.PDF_KIND_GENERATED_RECIPE
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Long Recipe",
        "ingredients": [{"ingredient": "beans"}],
        "instructions": [{"instruction": "Cook."}],
    })
    pdf_path = recipe_extract_service.recipe_pdf_path(url, kind)
    legacy_path = recipe_extract_service.legacy_recipe_pdf_path(url, kind)
    pdf_path.write_bytes(b"%PDF-1.4\nvalidated recipe\n%%EOF\n")
    assert pdf_path.name != legacy_path.name
    monkeypatch.setattr(
        recipe_edit_service,
        "validate_recipe_pdf_for_cloudflare_upload",
        lambda *args, **kwargs: {"ok": True, "sha256": "validated"},
    )
    captured = {}

    def fake_upload(path, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "verified": True,
            "object_key": kwargs["object_key"],
            "public_url": f"https://public.example.com/{kwargs['object_key']}",
            "bucket": "recipe-shopping-pdfs",
            "uploaded_at": "2026-08-04T12:00:00Z",
        }

    monkeypatch.setattr(recipe_edit_service.cloudflare_r2_storage, "upload_pdf", fake_upload)
    monkeypatch.setattr(
        recipe_edit_service.cloudflare_r2_storage,
        "delete_local_pdf_after_upload",
        lambda: False,
    )

    result = recipe_edit_service.upload_recipe_pdf_to_cloudflare(url, pdf_kind=kind)
    expected_key = f"recipe-pdfs/{pdf_path.name}"

    assert result["ok"] is True
    assert captured["object_key"] == expected_key
    assert result["pdf_public_url"] == f"https://public.example.com/{expected_key}"


def test_stable_r2_keys_do_not_collide_for_new_long_urls(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    prefix = "https://example.test/recipes/" + ("same-segment-" * 15)
    first_url = prefix + "first"
    second_url = prefix + "second"
    for url in (first_url, second_url):
        recipe_edit_service.save_recipe_output(url, {
            "source_url": url,
            "recipe_title": "Long Recipe",
            "ingredients": [{"ingredient": "beans"}],
        })

    first_key = recipe_edit_service.stable_recipe_pdf_r2_object_key(
        first_url,
        recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
    )
    second_key = recipe_edit_service.stable_recipe_pdf_r2_object_key(
        second_url,
        recipe_extract_service.PDF_KIND_GENERATED_RECIPE,
    )

    assert recipe_extract_service.safe_filename(first_url) == recipe_extract_service.safe_filename(second_url)
    assert first_key != second_key


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
        lambda path, **kwargs: {
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


def test_extract_duplicate_preserves_timestamp_and_local_pdf(monkeypatch, tmp_path):
    set_r2_env(monkeypatch)
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    url = "https://example.com/recipes/existing"
    object_key = "recipe-pdfs/example_com_recipes_existing.pdf"
    public_url = f"https://public.example.com/{object_key}"
    old_uploaded_at = "2025-01-02T03:04:05Z"
    pdf_path = recipe_extract_service.recipe_archive_pdf_path(url)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "upload_pdf",
        lambda path, **kwargs: {
            "ok": False,
            "code": "duplicate_object",
            "object_key": object_key,
            "public_url": public_url,
            "error": "already exists",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "head_pdf_object",
        lambda key: {
            "ok": True,
            "exists": True,
            "bucket": "recipe-shopping-pdfs",
            "object_key": key,
            "public_url": public_url,
            "uploaded_at": "2026-08-04T12:00:00Z",
            "etag": "remote-etag",
            "size_bytes": pdf_path.stat().st_size,
        },
    )
    monkeypatch.setattr(
        recipe_extract_service.cloudflare_r2_storage,
        "delete_local_pdf_after_upload",
        lambda: True,
    )
    recipe_data = {
        "source_url": url,
        "webpage_backup_pdf_uploaded_at": old_uploaded_at,
        "pdf": {
            recipe_extract_service.PDF_KIND_WEBPAGE_BACKUP: {
                "uploaded_at": old_uploaded_at,
                "cloudflare_r2": {"uploaded_at": old_uploaded_at},
            },
        },
    }

    upload_result = recipe_extract_service.maybe_upload_recipe_archive_pdf_to_cloudflare(url)
    recipe_extract_service.attach_cloudflare_pdf_metadata(url, recipe_data, upload_result)

    assert upload_result["already_exists"] is True
    assert upload_result["fresh_upload"] is False
    assert pdf_path.exists()
    assert recipe_data["webpage_backup_pdf_uploaded_at"] == old_uploaded_at
    assert recipe_data["pdf"][recipe_extract_service.PDF_KIND_WEBPAGE_BACKUP]["uploaded_at"] == old_uploaded_at


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
        lambda path, **kwargs: {
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


def test_editable_recipe_load_hydrates_source_cloudflare_pdf_path_alias(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    source_url = "https://example.com/recipes/chili"
    source_pdf_path = "D:/recipes/chili-source.pdf"
    source_cloudflare_url = "https://public.example.com/recipe-pdfs/chili-source.pdf"
    recipe_edit_service.save_recipe_output(source_url, {
        "source_url": source_url,
        "recipe_title": "Chili",
        "ingredients": [],
        "instructions": [],
        "source_pdf_path": source_pdf_path,
        "source_cloudflare_pdf_path": source_cloudflare_url,
    })

    loaded = recipe_edit_service.load_editable_recipe(source_url)["recipe"]

    assert loaded["source_url"] == source_url
    assert loaded["source_pdf_path"] == source_pdf_path
    assert loaded["source_cloudflare_pdf_url"] == source_cloudflare_url
    assert loaded["source_cloudflare_pdf_path"] == source_cloudflare_url


def test_save_editable_recipe_reuses_existing_source_pdf_when_editor_fields_are_blank(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    source_url = "https://example.com/recipes/chili"
    source_pdf_path = "D:/recipes/chili-source.pdf"
    source_cloudflare_url = "https://public.example.com/recipe-pdfs/chili-source.pdf"
    recipe_edit_service.save_recipe_output(source_url, {
        "source_url": source_url,
        "recipe_title": "Chili",
        "ingredients": [],
        "instructions": [],
        "source_pdf_path": source_pdf_path,
        "source_cloudflare_pdf_url": source_cloudflare_url,
    })

    result = recipe_edit_service.save_editable_recipe(
        source_url,
        editable_recipe_pdf_payload(
            source_url,
            source_pdf_path="",
            source_cloudflare_pdf_url="",
        ),
    )
    saved = recipe_edit_service.load_recipe_output(source_url)

    assert result["ok"] is True
    assert saved["source_pdf_path"] == source_pdf_path
    assert saved["source_cloudflare_pdf_url"] == source_cloudflare_url
    assert saved["source_cloudflare_pdf_path"] == source_cloudflare_url
    assert saved["webpage_backup_pdf_path"] == source_pdf_path
    assert saved["webpage_backup_pdf_url"] == source_cloudflare_url
    assert result["recipe"]["source_cloudflare_pdf_url"] == source_cloudflare_url


def test_save_editable_recipe_reuses_source_pdf_when_source_url_changes(monkeypatch, tmp_path):
    configure_recipe_editor_pdf_storage(monkeypatch, tmp_path)
    draft_url = "manual://recipe/draft-chili"
    source_url = "https://example.com/recipes/chili"
    source_pdf_path = "D:/recipes/chili-source.pdf"
    source_cloudflare_url = "https://public.example.com/recipe-pdfs/chili-source.pdf"
    recipe_edit_service.save_recipe_output(source_url, {
        "source_url": source_url,
        "recipe_title": "Existing Chili",
        "ingredients": [],
        "instructions": [],
        "pdf": {
            recipe_extract_service.PDF_KIND_WEBPAGE_BACKUP: {
                "local_path": source_pdf_path,
                "r2_object_key": "recipe-pdfs/chili-source.pdf",
                "r2_public_url": source_cloudflare_url,
                "uploaded_at": "2026-06-15T00:00:00Z",
                "cloud_status": "uploaded",
                "cloudflare_r2": {
                    "object_key": "recipe-pdfs/chili-source.pdf",
                    "public_url": source_cloudflare_url,
                    "uploaded_at": "2026-06-15T00:00:00Z",
                    "cloud_status": "uploaded",
                },
            },
        },
    })
    recipe_edit_service.save_recipe_output(draft_url, {
        "source_url": draft_url,
        "recipe_title": "Draft Chili",
        "ingredients": [],
        "instructions": [],
    })

    result = recipe_edit_service.save_editable_recipe(
        draft_url,
        editable_recipe_pdf_payload(
            source_url,
            recipe_title="Draft Chili",
            source_pdf_path="",
            source_cloudflare_pdf_url="",
        ),
    )
    saved = recipe_edit_service.load_recipe_output(source_url)

    assert result["ok"] is True
    assert saved["source_pdf_path"] == source_pdf_path
    assert saved["source_cloudflare_pdf_url"] == source_cloudflare_url
    assert saved["source_cloudflare_pdf_path"] == source_cloudflare_url
    assert saved["pdf"][recipe_extract_service.PDF_KIND_WEBPAGE_BACKUP]["r2_public_url"] == source_cloudflare_url
    assert result["recipe"]["source_cloudflare_pdf_url"] == source_cloudflare_url


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
