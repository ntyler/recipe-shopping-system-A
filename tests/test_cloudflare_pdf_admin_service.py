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


def test_delete_unlinked_cloudflare_pdfs_deletes_only_selected_current_unlinked(monkeypatch):
    deleted_keys = []
    monkeypatch.setattr(
        cloudflare_pdf_admin_service.cloudflare_r2_storage,
        "delete_pdf_object",
        lambda object_key: deleted_keys.append(object_key) or {"ok": True, "object_key": object_key},
    )
    monkeypatch.setattr(
        cloudflare_pdf_admin_service,
        "scan_unlinked_cloudflare_pdfs",
        lambda: {
            "ok": True,
            "success": True,
            "checked_at": "2026-06-15T12:00:00Z",
            "bucket": "recipe-shopping-pdfs",
            "total_cloudflare_pdfs": 3,
            "referenced_pdf_count": 1,
            "reference_file_count": 2,
            "unlinked_pdf_count": 2,
            "unlinked_pdfs": [
                {
                    "object_key": "recipe-pdfs/unlinked.pdf",
                    "filename": "unlinked.pdf",
                    "public_url": "https://public.example.com/recipe-pdfs/unlinked.pdf",
                },
                {
                    "object_key": "archive/menu.pdf",
                    "filename": "menu.pdf",
                    "public_url": "https://public.example.com/archive/menu.pdf",
                },
            ],
        },
    )

    result = cloudflare_pdf_admin_service.delete_unlinked_cloudflare_pdfs([
        "recipe-pdfs/unlinked.pdf",
        "recipe-pdfs/linked.pdf",
        "archive/menu.pdf",
    ])

    assert result["ok"] is True
    assert result["success"] is True
    assert result["deleted_count"] == 2
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["unlinked_pdf_count"] == 0
    assert result["orphaned_pdf_count"] == 0
    assert result["skipped_pdfs"][0]["object_key"] == "recipe-pdfs/linked.pdf"
    assert deleted_keys == ["recipe-pdfs/unlinked.pdf", "archive/menu.pdf"]


def test_delete_unlinked_cloudflare_pdfs_requires_selection():
    result = cloudflare_pdf_admin_service.delete_unlinked_cloudflare_pdfs([])

    assert result["ok"] is False
    assert result["success"] is False
    assert result["code"] == "no_selection"
    assert result["deleted_count"] == 0
