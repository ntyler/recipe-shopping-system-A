from urllib.parse import urlparse

from app import app
from PushShoppingList.routes import pdf_routes
from PushShoppingList.services import pdf_share_service


def configure_pdf_share_routes(monkeypatch, tmp_path, current_user=None):
    pdf_dir = tmp_path / "pdf"
    metadata_file = tmp_path / "pdf_share_links.json"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "route-sample.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    monkeypatch.setattr(pdf_share_service, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(pdf_share_service, "PDF_SHARE_LINKS_FILE", metadata_file)
    monkeypatch.setattr(
        pdf_routes,
        "current_public_user",
        lambda: current_user,
    )
    app.config["TESTING"] = True
    return pdf_dir, metadata_file


def test_pdf_share_routes_create_serve_and_revoke(monkeypatch, tmp_path):
    _pdf_dir, metadata_file = configure_pdf_share_routes(
        monkeypatch,
        tmp_path,
        current_user={
            "user_id": "user-1",
            "email": "cook@example.com",
        },
    )

    with app.test_client() as client:
        create_response = client.post("/pdfs/share", json={"pdf_filename": "route-sample.pdf"})
        create_data = create_response.get_json()

        assert create_response.status_code == 200
        assert create_data["success"] is True
        assert "/share/pdf/" in create_data["share_url"]

        share_path = urlparse(create_data["share_url"]).path
        public_response = client.get(share_path)

        assert public_response.status_code == 200
        assert public_response.mimetype == "application/pdf"
        assert public_response.data.startswith(b"%PDF")

        stored_record = pdf_share_service.find_share_record(create_data["token"])
        assert stored_record["access_count"] == 1
        assert stored_record["last_accessed_at"]

        revoke_response = client.post("/pdfs/share/revoke", json={"token": create_data["token"]})
        revoked_response = client.get(share_path)

        assert revoke_response.status_code == 200
        assert revoke_response.get_json()["success"] is True
        assert revoked_response.status_code == 410
        assert metadata_file.exists()


def test_pdf_share_create_requires_signed_in_user(monkeypatch, tmp_path):
    configure_pdf_share_routes(monkeypatch, tmp_path, current_user=None)

    with app.test_client() as client:
        response = client.post("/pdfs/share", json={"pdf_filename": "route-sample.pdf"})

    assert response.status_code == 401
    assert response.get_json()["success"] is False


def test_authenticated_pdf_view_rejects_traversal(monkeypatch, tmp_path):
    configure_pdf_share_routes(
        monkeypatch,
        tmp_path,
        current_user={
            "user_id": "user-1",
            "email": "cook@example.com",
        },
    )

    with app.test_client() as client:
        response = client.get("/pdfs/view/../route-sample.pdf")

    assert response.status_code == 404
