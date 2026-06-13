import json

from PushShoppingList.services import cloudflare_pdf_admin_service


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scan_orphaned_cloudflare_pdfs_uses_recipe_and_menu_references(monkeypatch, tmp_path):
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
    monkeypatch.setattr(
        cloudflare_pdf_admin_service,
        "reference_json_paths",
        lambda: [recipe_path, menu_path],
    )
    monkeypatch.setattr(
        cloudflare_pdf_admin_service.cloudflare_r2_storage,
        "list_pdf_objects",
        lambda: {
            "ok": True,
            "success": True,
            "bucket": "recipe-shopping-pdfs",
            "objects": [
                {"object_key": "recipe-pdfs/linked.pdf", "public_url": "", "size": 100},
                {"object_key": "recipe-pdfs/generated.pdf", "public_url": "", "size": 200},
                {"object_key": "menu-pdfs/menu-linked.pdf", "public_url": "", "size": 300},
                {"object_key": "recipe-pdfs/orphan.pdf", "public_url": "", "size": 400},
            ],
        },
    )

    result = cloudflare_pdf_admin_service.scan_orphaned_cloudflare_pdfs()

    assert result["ok"] is True
    assert result["total_cloudflare_pdfs"] == 4
    assert result["referenced_pdf_count"] == 3
    assert result["reference_file_count"] == 2
    assert result["orphaned_pdf_count"] == 1
    assert result["orphaned_pdfs"][0]["object_key"] == "recipe-pdfs/orphan.pdf"
    assert result["orphaned_pdfs"][0]["size_label"] == "400 B"


def test_delete_orphaned_cloudflare_pdfs_deletes_current_orphans(monkeypatch):
    deleted_keys = []
    monkeypatch.setattr(
        cloudflare_pdf_admin_service,
        "scan_orphaned_cloudflare_pdfs",
        lambda: {
            "ok": True,
            "success": True,
            "bucket": "recipe-shopping-pdfs",
            "total_cloudflare_pdfs": 2,
            "referenced_pdf_count": 1,
            "reference_file_count": 1,
            "orphaned_pdf_count": 1,
            "orphaned_pdfs": [
                {
                    "object_key": "recipe-pdfs/orphan.pdf",
                    "public_url": "https://public.example.com/recipe-pdfs/orphan.pdf",
                    "size": 400,
                    "size_label": "400 B",
                }
            ],
        },
    )
    monkeypatch.setattr(
        cloudflare_pdf_admin_service.cloudflare_r2_storage,
        "delete_pdf",
        lambda object_key: deleted_keys.append(object_key) or {"ok": True, "object_key": object_key},
    )

    result = cloudflare_pdf_admin_service.delete_orphaned_cloudflare_pdfs()

    assert result["ok"] is True
    assert result["success"] is True
    assert result["deleted_count"] == 1
    assert result["failed_count"] == 0
    assert result["orphaned_pdf_count"] == 0
    assert result["orphaned_pdfs"] == []
    assert deleted_keys == ["recipe-pdfs/orphan.pdf"]
