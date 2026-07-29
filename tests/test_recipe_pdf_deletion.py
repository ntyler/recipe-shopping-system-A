from copy import deepcopy
from pathlib import Path

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services import job_service
from PushShoppingList.services import recipe_edit_service


def generated_pdf_recipe_data(pdf_path):
    return {
        "source_url": "https://example.com/corn-spoon-bread",
        "generated_pdf_path": str(pdf_path),
        "generated_cloudflare_pdf_url": (
            "https://public.example.com/recipe-pdfs/corn-spoon-bread_generated_recipe.pdf"
        ),
        "generated_recipe_pdf_object_key": (
            "recipe-pdfs/corn-spoon-bread_generated_recipe.pdf"
        ),
        "generated_recipe_pdf_uploaded_at": "2026-07-29T18:41:00Z",
        "pdf": {
            recipe_edit_service.PDF_KIND_GENERATED_RECIPE: {
                "local_path": str(pdf_path),
                "r2_object_key": "recipe-pdfs/corn-spoon-bread_generated_recipe.pdf",
                "r2_public_url": (
                    "https://public.example.com/recipe-pdfs/"
                    "corn-spoon-bread_generated_recipe.pdf"
                ),
                "cloudflare_r2": {
                    "object_key": "recipe-pdfs/corn-spoon-bread_generated_recipe.pdf",
                },
            },
        },
    }


def test_delete_editable_recipe_pdf_deletes_local_and_cloud_copy(monkeypatch, tmp_path):
    recipe_url = "https://example.com/corn-spoon-bread"
    pdf_path = tmp_path / "corn-spoon-bread_generated_recipe.pdf"
    pdf_path.write_bytes(b"%PDF sample")
    recipe_data = generated_pdf_recipe_data(pdf_path)
    saved = []
    deleted_keys = []

    monkeypatch.setattr(
        recipe_edit_service,
        "recipe_pdf_path",
        lambda url, kind: pdf_path,
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "load_recipe_output",
        lambda url: deepcopy(recipe_data),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_output",
        lambda url, data: saved.append(deepcopy(data)),
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "delete_pdf",
        lambda object_key: (
            deleted_keys.append(object_key)
            or {
                "ok": True,
                "object_key": object_key,
                "public_url": recipe_data["generated_cloudflare_pdf_url"],
            }
        ),
    )

    result = recipe_edit_service.delete_editable_recipe_pdf(recipe_url)

    assert result["ok"] is True
    assert result["had_pdf"] is True
    assert result["cloud_pdf_deleted"] is True
    assert result["local_pdf_deleted"] is True
    assert deleted_keys == ["recipe-pdfs/corn-spoon-bread_generated_recipe.pdf"]
    assert not pdf_path.exists()
    assert saved[0]["generated_pdf_path"] == ""
    assert saved[0]["generated_cloudflare_pdf_url"] == ""
    assert saved[0]["generated_recipe_pdf_object_key"] == ""
    assert recipe_edit_service.PDF_KIND_GENERATED_RECIPE not in saved[0]["pdf"]


def test_delete_editable_recipe_pdf_preserves_local_copy_when_cloud_delete_fails(
    monkeypatch,
    tmp_path,
):
    recipe_url = "https://example.com/corn-spoon-bread"
    pdf_path = tmp_path / "corn-spoon-bread_generated_recipe.pdf"
    pdf_path.write_bytes(b"%PDF sample")
    recipe_data = generated_pdf_recipe_data(pdf_path)
    saved = []

    monkeypatch.setattr(
        recipe_edit_service,
        "recipe_pdf_path",
        lambda url, kind: pdf_path,
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "load_recipe_output",
        lambda url: deepcopy(recipe_data),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_output",
        lambda url, data: saved.append(deepcopy(data)),
    )
    monkeypatch.setattr(
        cloudflare_r2_storage,
        "delete_pdf",
        lambda object_key: {
            "ok": False,
            "code": "delete_failed",
            "error": "R2 unavailable",
        },
    )

    result = recipe_edit_service.delete_editable_recipe_pdf(recipe_url)

    assert result["ok"] is False
    assert result["error"] == "R2 unavailable"
    assert result["cloud_pdf_deleted"] is False
    assert result["local_pdf_deleted"] is False
    assert pdf_path.exists()
    assert saved == []


def test_recipe_deletion_pdf_cleanup_marks_completed_pdf_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        recipe_edit_service,
        "delete_editable_recipe_pdf",
        lambda url: {"ok": True, "had_pdf": True},
    )
    monkeypatch.setattr(
        job_service,
        "mark_recipe_pdf_result_cleanup",
        lambda url, result, user_id="", guest_session_id="": (
            calls.append((url, result, user_id, guest_session_id)) or 2
        ),
    )

    result = recipe_edit_service.delete_generated_recipe_pdf_for_recipe_deletion(
        "https://example.com/corn-spoon-bread",
        user_id="owner",
    )

    assert result["ok"] is True
    assert result["job_records_updated"] == 2
    assert calls == [(
        "https://example.com/corn-spoon-bread",
        {"ok": True, "had_pdf": True},
        "owner",
        "",
    )]


def test_editor_delete_uses_permanent_purge_and_discloses_pdf_cleanup():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("async function confirmDeleteRecipeFromEditor")
    end = script.index("function duplicateRecipeIngredientRow", start)
    delete_flow = script[start:end]

    assert "Permanently delete" in delete_flow
    assert "deletes its generated PDF locally and from Cloudflare" in delete_flow
    assert 'fetch("/purge_recipe"' in delete_flow
    assert 'fetch("/remove_recipe"' not in delete_flow
