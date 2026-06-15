import json

from PushShoppingList.services import cloudflare_pdf_admin_service


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scan_unlinked_cloudflare_pdfs_uses_project_pdf_references(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("R2_BUCKET_NAME", "recipe-shopping-pdfs")
    recipe_path = write_json(
        tmp_path / "user-a" / "recipe-extractor" / "data" / "output" / "recipe.json",
        {
            "source_url": "manual://recipe/linked",
            "pdf": {
                "cloudflare_r2": {
                    "object_key": "recipe-pdfs/linked.pdf",
                },
            },
            "generated_cloudflare_pdf_url": "https://public.example.com/recipe-pdfs/generated.pdf",
            "source_cloudflare_pdf_url": "https://public.example.com/recipe-pdfs/source%20with%20spaces.pdf",
        },
    )
    menu_path = write_json(
        tmp_path / "user-b" / "restaurant_menus.json",
        {
            "pdf_logs": [
                {
                    "cloudflare_pdf_path": "menu-pdfs/menu-linked.pdf",
                    "cloudflare_pdf_url": "https://public.example.com/menu-pdfs/menu-linked.pdf",
                }
            ],
        },
    )
    cookbook_path = write_json(
        tmp_path / "user-c" / "cookbooks.json",
        {
            "items": [
                {
                    "pdf_generation": {
                        "generated_cloudflare_pdf_path": "recipe-shopping-pdfs/other/generated-from-cookbook.pdf",
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        cloudflare_pdf_admin_service,
        "reference_json_paths",
        lambda: [recipe_path, menu_path, cookbook_path],
    )
    monkeypatch.setattr(
        cloudflare_pdf_admin_service.cloudflare_r2_storage,
        "list_all_pdf_objects",
        lambda: {
            "ok": True,
            "success": True,
            "bucket": "recipe-shopping-pdfs",
            "objects": [
                {"object_key": "recipe-pdfs/linked.pdf", "public_url": "", "size": 100},
                {"object_key": "recipe-pdfs/generated.pdf", "public_url": "", "size": 200},
                {"object_key": "recipe-pdfs/source with spaces.pdf", "public_url": "", "size": 250},
                {"object_key": "menu-pdfs/menu-linked.pdf", "public_url": "", "size": 300},
                {"object_key": "other/generated-from-cookbook.pdf", "public_url": "", "size": 350},
                {
                    "object_key": "unclassified/orphan.pdf",
                    "public_url": "",
                    "size": 400,
                    "last_modified": "2026-06-01T12:30:00Z",
                },
            ],
        },
    )

    with caplog.at_level("INFO"):
        result = cloudflare_pdf_admin_service.scan_unlinked_cloudflare_pdfs()

    assert result["ok"] is True
    assert result["total_cloudflare_pdfs"] == 6
    assert result["referenced_pdf_count"] == 5
    assert result["reference_file_count"] == 3
    assert result["unlinked_pdf_count"] == 1
    assert result["orphaned_pdf_count"] == 1
    assert result["unlinked_pdfs"][0]["filename"] == "orphan.pdf"
    assert result["unlinked_pdfs"][0]["object_key"] == "unclassified/orphan.pdf"
    assert result["unlinked_pdfs"][0]["size_label"] == "400 B"
    assert result["unlinked_pdfs"][0]["last_modified_label"] == "2026-06-01T12:30:00Z"
    assert result["unlinked_pdfs"][0]["suspected_type"] == "unknown"
    assert "No matching normalized Cloudflare/R2 PDF reference" in result["unlinked_pdfs"][0]["reason"]
    assert "Cloudflare unlinked PDF scan" in caplog.text


def test_delete_orphaned_cloudflare_pdfs_is_disabled(monkeypatch):
    deleted_keys = []
    monkeypatch.setattr(
        cloudflare_pdf_admin_service.cloudflare_r2_storage,
        "delete_pdf",
        lambda object_key: deleted_keys.append(object_key) or {"ok": True, "object_key": object_key},
    )

    result = cloudflare_pdf_admin_service.delete_orphaned_cloudflare_pdfs()

    assert result["ok"] is False
    assert result["success"] is False
    assert result["code"] == "delete_disabled"
    assert result["deleted_count"] == 0
    assert result["failed_count"] == 0
    assert deleted_keys == []
