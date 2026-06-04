from pathlib import Path

from PushShoppingList.services import pdf_share_service


def configure_pdf_share_paths(monkeypatch, tmp_path):
    pdf_dir = tmp_path / "pdf"
    metadata_file = tmp_path / "pdf_share_links.json"
    monkeypatch.setattr(pdf_share_service, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(pdf_share_service, "PDF_SHARE_LINKS_FILE", metadata_file)
    return pdf_dir, metadata_file


def write_sample_pdf(pdf_dir, filename="sample-recipe.pdf"):
    pdf_dir.mkdir(parents=True, exist_ok=True)
    path = pdf_dir / filename
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    return path


def test_pdf_share_link_lifecycle(monkeypatch, tmp_path):
    pdf_dir, metadata_file = configure_pdf_share_paths(monkeypatch, tmp_path)
    sample_pdf = write_sample_pdf(pdf_dir)

    rows = pdf_share_service.list_available_pdfs()

    assert rows[0]["pdf_filename"] == sample_pdf.name
    assert rows[0]["active_share"] is None

    result = pdf_share_service.create_pdf_share_link(
        sample_pdf.name,
        current_user={
            "user_id": "user-1",
            "email": "cook@example.com",
        },
    )

    assert result["ok"] is True
    assert result["created"] is True
    record = result["record"]
    assert record["pdf_filename"] == sample_pdf.name
    assert record["created_by_user_id"] == "user-1"
    assert record["created_by_email"] == "cook@example.com"
    assert not Path(record["pdf_path"]).is_absolute()
    assert metadata_file.exists()

    second_result = pdf_share_service.create_pdf_share_link(sample_pdf.name)

    assert second_result["created"] is False
    assert second_result["record"]["token"] == record["token"]

    resolved = pdf_share_service.resolve_share_token(record["token"])

    assert resolved["ok"] is True
    assert resolved["pdf_path"] == sample_pdf.resolve()

    pdf_share_service.record_share_access(record["token"])
    accessed_record = pdf_share_service.find_share_record(record["token"])

    assert accessed_record["access_count"] == 1
    assert accessed_record["last_accessed_at"]

    revoke_result = pdf_share_service.revoke_share_token(record["token"])
    revoked_resolution = pdf_share_service.resolve_share_token(record["token"])

    assert revoke_result["ok"] is True
    assert revoked_resolution["ok"] is False
    assert revoked_resolution["status"] == 410


def test_safe_pdf_path_rejects_traversal(monkeypatch, tmp_path):
    pdf_dir, _metadata_file = configure_pdf_share_paths(monkeypatch, tmp_path)
    write_sample_pdf(pdf_dir)

    assert pdf_share_service.safe_resolve_pdf_path("sample-recipe.pdf")
    assert pdf_share_service.safe_resolve_pdf_path("../sample-recipe.pdf") is None
    assert pdf_share_service.safe_resolve_pdf_path("nested/sample-recipe.pdf") is None
    assert pdf_share_service.safe_resolve_pdf_path("sample-recipe.txt") is None


def test_corrupt_pdf_share_metadata_recovers(monkeypatch, tmp_path):
    _pdf_dir, metadata_file = configure_pdf_share_paths(monkeypatch, tmp_path)
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text("{not-json", encoding="utf-8")

    assert pdf_share_service.load_share_links() == {"links": []}


def test_share_record_without_valid_expiration_is_not_active():
    assert pdf_share_service.is_share_expired({"expires_at": ""}) is True
    assert pdf_share_service.is_share_active({"token": "abc", "expires_at": ""}) is False
