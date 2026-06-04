from urllib.parse import urlparse

from app import app
from PushShoppingList.routes import pdf_routes
from PushShoppingList.routes import recipe_routes
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


def test_pdf_cloudflare_upload_route_returns_public_url(monkeypatch, tmp_path):
    configure_pdf_share_routes(
        monkeypatch,
        tmp_path,
        current_user={
            "user_id": "user-1",
            "email": "cook@example.com",
        },
    )
    monkeypatch.setattr(pdf_routes, "recipe_url_for_pdf_filename", lambda filename: "manual://recipe/test")
    monkeypatch.setattr(
        pdf_routes,
        "upload_local_pdf_path_to_cloudflare",
        lambda pdf_path, url="": {
            "ok": True,
            "success": True,
            "url": url,
            "pdf_path": str(pdf_path),
            "pdf_public_url": f"https://public.example.com/recipe-pdfs/{pdf_path.name}",
            "pdf_object_key": f"recipe-pdfs/{pdf_path.name}",
            "pdf_available": True,
            "pdf_local_available": True,
        },
    )

    with app.test_client() as client:
        response = client.post("/pdfs/cloudflare_upload", json={"pdf_filename": "route-sample.pdf"})

    data = response.get_json()
    assert response.status_code == 200
    assert data["success"] is True
    assert data["pdf_public_url"] == "https://public.example.com/recipe-pdfs/route-sample.pdf"
    assert data["pdf_object_key"] == "recipe-pdfs/route-sample.pdf"


def test_local_recipe_pdf_download_requires_admin(monkeypatch, tmp_path):
    pdf_path = tmp_path / "local-recipe.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    monkeypatch.setattr(recipe_routes, "recipe_archive_pdf_path", lambda url: pdf_path)
    monkeypatch.setattr(recipe_routes, "current_user", lambda: {"email": "cook@example.com"})
    monkeypatch.setattr(recipe_routes, "is_admin_user", lambda user: False)

    with app.test_client() as client:
        response = client.get("/recipe_archive_pdf?url=manual%3A%2F%2Frecipe%2Ftest&download=1")

    assert response.status_code == 403


def test_admin_can_download_local_recipe_pdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "local-recipe.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    monkeypatch.setattr(recipe_routes, "recipe_archive_pdf_path", lambda url: pdf_path)
    monkeypatch.setattr(recipe_routes, "current_user", lambda: {"email": "admin@example.com"})
    monkeypatch.setattr(recipe_routes, "is_admin_user", lambda user: True)

    with app.test_client() as client:
        response = client.get("/recipe_archive_pdf?url=manual%3A%2F%2Frecipe%2Ftest&download=1")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert response.data.startswith(b"%PDF")
