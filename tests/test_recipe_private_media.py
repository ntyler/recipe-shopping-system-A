from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import parse_qsl
from urllib.parse import urlsplit

from flask import session

from PushShoppingList.app import create_app
from PushShoppingList.routes import recipe_routes
from PushShoppingList.routes import main_routes
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service
from PushShoppingList.services.recipe_url_service import recipe_archive_pdf_url
from PushShoppingList.services.recipe_url_service import canonicalize_private_recipe_url
from PushShoppingList.services.recipe_url_service import recipe_cover_image_url
from PushShoppingList.services.recipe_url_service import recipe_edit_page_url
from PushShoppingList.services.recipe_url_service import restaurant_source_logo_url


SOURCE_URL = "https://example.test/recipe/soup?size=2&next=/menu?q=hot#card"


def configured_app(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [
            {
                "user_id": "user-a",
                "username": "user-a",
                "email": "user-a@example.test",
                "account_status": "active",
            },
            {
                "user_id": "user-b",
                "username": "user-b",
                "email": "user-b@example.test",
                "account_status": "active",
            },
        ],
    })
    app = create_app()
    app.config.update(TESTING=True)
    return app


def sign_in(client, user_id):
    with client.session_transaction() as flask_session:
        flask_session.clear()
        flask_session["user_id"] = user_id


def assert_private_no_store(response):
    assert response.headers.get("Cache-Control") == "private, no-store"
    assert response.headers.get("Pragma") == "no-cache"


def test_recipe_cover_image_uses_session_workspace_and_canonical_viewer(
    monkeypatch,
    tmp_path,
):
    app = configured_app(monkeypatch, tmp_path)
    image_a = tmp_path / "user-a.png"
    image_b = tmp_path / "user-b.png"
    variant_a = tmp_path / "user-a__thumb.webp"
    image_a.write_bytes(b"image-for-user-a")
    image_b.write_bytes(b"image-for-user-b")
    variant_a.write_bytes(b"variant-for-user-a")
    resolution_calls = []

    def find_cover_image(_recipe_url):
        resolution_calls.append(session.get("user_id"))
        return {"path": str(image_a if session.get("user_id") == "user-a" else image_b)}

    monkeypatch.setattr(recipe_routes, "find_recipe_cover_image", find_cover_image)
    monkeypatch.setattr(
        recipe_routes,
        "recipe_cover_image_file_path",
        lambda value: Path(value["path"]),
    )
    monkeypatch.setattr(recipe_routes, "ensure_webp_variant", lambda _path, _variant: variant_a)

    with app.test_client() as client:
        sign_in(client, "user-a")
        missing = client.get(
            "/recipe_cover_image",
            query_string={"url": SOURCE_URL, "v": "rev 1&next=%2F"},
        )
        assert missing.status_code == 302
        assert parse_qsl(urlsplit(missing.headers["Location"]).query) == [
            ("viewer_user_id", "user-a"),
            ("url", SOURCE_URL),
            ("v", "rev 1&next=%2F"),
        ]
        assert resolution_calls == []
        assert_private_no_store(missing)

        matching = client.get(missing.headers["Location"])
        assert matching.status_code == 200
        assert matching.data == b"image-for-user-a"
        assert resolution_calls == ["user-a"]
        assert_private_no_store(matching)

        blank = client.get(
            "/recipe_cover_image",
            query_string={"viewer_user_id": "   ", "url": SOURCE_URL},
        )
        mismatch = client.get(
            "/recipe_cover_image",
            query_string={"viewer_user_id": "user-b", "url": SOURCE_URL},
        )
        duplicate_viewer = client.get(
            "/recipe_cover_image",
            query_string=[
                ("viewer_user_id", "user-a"),
                ("viewer_user_id", "user-a"),
                ("url", SOURCE_URL),
            ],
        )
        duplicate_url = client.get(
            "/recipe_cover_image",
            query_string=[
                ("viewer_user_id", "user-a"),
                ("url", SOURCE_URL),
                ("url", SOURCE_URL),
            ],
        )
        variant = client.get(
            "/recipe_cover_image",
            query_string={
                "viewer_user_id": "user-a",
                "url": SOURCE_URL,
                "variant": "thumb",
                "v": "123",
            },
        )
        if variant.status_code == 302:
            assert_private_no_store(variant)
            variant = client.get(variant.headers["Location"])

        assert blank.status_code == 302
        assert parse_qs(urlsplit(blank.headers["Location"]).query)["viewer_user_id"] == ["user-a"]
        assert mismatch.status_code == 403
        assert duplicate_viewer.status_code == 400
        assert duplicate_url.status_code == 400
        assert variant.status_code == 200
        assert variant.data == b"variant-for-user-a"
        for response in (blank, mismatch, duplicate_viewer, duplicate_url, variant):
            assert_private_no_store(response)
        assert "public" not in variant.headers["Cache-Control"]
        assert "max-age" not in variant.headers["Cache-Control"]

        sign_in(client, "user-b")
        other_user = client.get(
            "/recipe_cover_image",
            query_string={"viewer_user_id": "user-b", "url": SOURCE_URL},
        )
        if other_user.status_code == 302:
            assert_private_no_store(other_user)
            other_user = client.get(other_user.headers["Location"])
        assert other_user.status_code == 200
        assert other_user.data == b"image-for-user-b"
        assert resolution_calls[-1] == "user-b"
        assert_private_no_store(other_user)


def test_recipe_archive_pdf_canonicalizes_redirects_errors_and_sensitive_parameters(
    monkeypatch,
    tmp_path,
):
    app = configured_app(monkeypatch, tmp_path)
    pdf_a = tmp_path / "user-a.pdf"
    missing_pdf = tmp_path / "missing.pdf"
    pdf_a.write_bytes(b"%PDF-1.4\nuser-a\n%%EOF\n")
    monkeypatch.setattr(
        recipe_routes,
        "ensure_recipe_pdf_cloudflare_link",
        lambda *_args, **_kwargs: {"success": False, "public_url": ""},
    )
    monkeypatch.setattr(recipe_routes, "recipe_pdf_path", lambda *_args: pdf_a)

    with app.test_client() as client:
        sign_in(client, "user-a")
        missing_viewer = client.get(
            "/recipe_archive_pdf",
            query_string={"url": SOURCE_URL, "pdf_kind": "generated"},
        )
        assert missing_viewer.status_code == 302
        assert parse_qsl(urlsplit(missing_viewer.headers["Location"]).query) == [
            ("viewer_user_id", "user-a"),
            ("url", SOURCE_URL),
            ("kind", "generated_recipe"),
        ]
        assert_private_no_store(missing_viewer)

        matching = client.get(missing_viewer.headers["Location"])
        assert matching.status_code == 200
        assert matching.data.startswith(b"%PDF-1.4")
        assert_private_no_store(matching)

        mismatch = client.get(
            "/recipe_archive_pdf",
            query_string={"viewer_user_id": "user-b", "url": SOURCE_URL},
        )
        duplicate_download = client.get(
            "/recipe_archive_pdf",
            query_string=[
                ("viewer_user_id", "user-a"),
                ("url", SOURCE_URL),
                ("download", "1"),
                ("download", "1"),
            ],
        )
        ambiguous_kind = client.get(
            "/recipe_archive_pdf",
            query_string={
                "viewer_user_id": "user-a",
                "url": SOURCE_URL,
                "kind": "generated_recipe",
                "pdf_kind": "generated_recipe",
            },
        )
        assert mismatch.status_code == 403
        assert duplicate_download.status_code == 400
        assert ambiguous_kind.status_code == 400
        for response in (mismatch, duplicate_download, ambiguous_kind):
            assert_private_no_store(response)

        normalized_download = client.get(
            "/recipe_archive_pdf",
            query_string={
                "viewer_user_id": "user-a",
                "url": SOURCE_URL,
                "download": "true",
            },
        )
        assert normalized_download.status_code == 302
        assert parse_qs(urlsplit(normalized_download.headers["Location"]).query)["download"] == ["1"]
        assert_private_no_store(normalized_download)

        monkeypatch.setattr(
            recipe_routes,
            "ensure_recipe_pdf_cloudflare_link",
            lambda *_args, **_kwargs: {
                "success": True,
                "public_url": "https://cdn.example.test/private-recipe.pdf",
                "timings": {},
            },
        )
        cloud_redirect = client.get(
            "/recipe_archive_pdf",
            query_string={"viewer_user_id": "user-a", "url": SOURCE_URL},
        )
        if cloud_redirect.headers["Location"].startswith("/recipe_archive_pdf"):
            assert_private_no_store(cloud_redirect)
            cloud_redirect = client.get(cloud_redirect.headers["Location"])
        assert cloud_redirect.status_code == 302
        assert cloud_redirect.headers["Location"] == "https://cdn.example.test/private-recipe.pdf"
        assert_private_no_store(cloud_redirect)

        monkeypatch.setattr(
            recipe_routes,
            "ensure_recipe_pdf_cloudflare_link",
            lambda *_args, **_kwargs: {"success": False, "public_url": ""},
        )
        monkeypatch.setattr(recipe_routes, "recipe_pdf_path", lambda *_args: missing_pdf)
        not_found = client.get(
            "/recipe_archive_pdf",
            query_string={"viewer_user_id": "user-a", "url": SOURCE_URL},
        )
        if not_found.status_code == 302:
            assert_private_no_store(not_found)
            not_found = client.get(not_found.headers["Location"])
        assert not_found.status_code == 404
        assert_private_no_store(not_found)


def test_restaurant_logo_is_private_and_rejects_duplicate_resource_ids(
    monkeypatch,
    tmp_path,
):
    app = configured_app(monkeypatch, tmp_path)
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"private-logo")
    monkeypatch.setattr(recipe_routes, "editable_restaurant_logo_file_path", lambda _restaurant_id: logo)

    with app.test_client() as client:
        sign_in(client, "user-a")
        missing = client.get(
            "/restaurant_source_logo",
            query_string={"restaurant_id": "restaurant/a&b", "v": "1 2"},
        )
        assert missing.status_code == 302
        assert parse_qsl(urlsplit(missing.headers["Location"]).query) == [
            ("viewer_user_id", "user-a"),
            ("restaurant_id", "restaurant/a&b"),
            ("v", "1 2"),
        ]
        assert_private_no_store(missing)
        matching = client.get(missing.headers["Location"])
        assert matching.status_code == 200
        assert matching.data == b"private-logo"
        assert_private_no_store(matching)

        mismatch = client.get(
            "/restaurant_source_logo",
            query_string={"viewer_user_id": "user-b", "restaurant_id": "restaurant/a&b"},
        )
        duplicate = client.get(
            "/restaurant_source_logo",
            query_string=[
                ("viewer_user_id", "user-a"),
                ("restaurant_id", "restaurant-a"),
                ("restaurant_id", "restaurant-b"),
            ],
        )
        assert mismatch.status_code == 403
        assert duplicate.status_code == 400
        assert_private_no_store(mismatch)
        assert_private_no_store(duplicate)


def test_guest_private_recipe_media_urls_remain_userless(monkeypatch, tmp_path):
    app = configured_app(monkeypatch, tmp_path)
    image = tmp_path / "guest.png"
    image.write_bytes(b"guest-image")
    monkeypatch.setattr(recipe_routes, "find_recipe_cover_image", lambda _url: {"path": str(image)})
    monkeypatch.setattr(recipe_routes, "recipe_cover_image_file_path", lambda value: Path(value["path"]))

    with app.test_client() as client:
        assert client.get("/guest/start").status_code == 302
        userless = client.get("/recipe_cover_image", query_string={"url": SOURCE_URL})
        if userless.status_code == 302:
            assert "viewer_user_id" not in userless.headers["Location"]
            assert_private_no_store(userless)
            userless = client.get(userless.headers["Location"])
        supplied_viewer = client.get(
            "/recipe_cover_image",
            query_string={"viewer_user_id": "user-a", "url": SOURCE_URL},
        )
        blank_viewer = client.get(
            "/recipe_cover_image",
            query_string={"viewer_user_id": "", "url": SOURCE_URL},
        )

    assert userless.status_code == 200
    assert userless.data == b"guest-image"
    assert supplied_viewer.status_code == 403
    assert blank_viewer.status_code == 302
    assert "viewer_user_id" not in blank_viewer.headers["Location"]
    for response in (userless, supplied_viewer, blank_viewer):
        assert_private_no_store(response)


def test_anonymous_private_recipe_media_uses_normal_auth_response_and_no_store(
    monkeypatch,
    tmp_path,
):
    app = configured_app(monkeypatch, tmp_path)
    monkeypatch.setattr(
        recipe_routes,
        "find_recipe_cover_image",
        lambda _url: (_ for _ in ()).throw(AssertionError("workspace must not resolve")),
    )
    monkeypatch.setattr(
        recipe_routes,
        "editable_restaurant_logo_file_path",
        lambda _restaurant_id: (_ for _ in ()).throw(AssertionError("workspace must not resolve")),
    )
    monkeypatch.setattr(
        recipe_routes,
        "ensure_recipe_pdf_cloudflare_link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("workspace must not resolve")),
    )

    with app.test_client() as client:
        responses = (
            client.get("/recipe_cover_image", query_string={"url": SOURCE_URL}),
            client.get("/recipe_archive_pdf", query_string={"url": SOURCE_URL}),
            client.get(
                "/restaurant_source_logo",
                query_string={"restaurant_id": "restaurant-a"},
            ),
        )

    for response in responses:
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#userAccountSection")
        assert_private_no_store(response)


def test_recipe_private_url_producers_emit_one_resolved_viewer_and_encode_once(
    monkeypatch,
    tmp_path,
):
    app = configured_app(monkeypatch, tmp_path)
    with app.test_request_context("/"):
        session["user_id"] = "user-a"
        urls = (
            recipe_edit_page_url(SOURCE_URL),
            recipe_cover_image_url(SOURCE_URL, variant="THUMB", version="1 & %2F"),
            recipe_archive_pdf_url(SOURCE_URL, kind="generated_recipe", download=True),
            restaurant_source_logo_url("restaurant/a&b", version="1 & %2F"),
        )

    for value in urls:
        parameters = parse_qs(urlsplit(value).query)
        assert parameters["viewer_user_id"] == ["user-a"]
        assert value.count("viewer_user_id=") == 1
    assert parse_qs(urlsplit(urls[0]).query)["url"] == [SOURCE_URL]
    assert parse_qs(urlsplit(urls[1]).query) == {
        "viewer_user_id": ["user-a"],
        "url": [SOURCE_URL],
        "variant": ["thumb"],
        "v": ["1 & %2F"],
    }
    assert parse_qs(urlsplit(urls[2]).query)["download"] == ["1"]
    assert parse_qs(urlsplit(urls[3]).query)["restaurant_id"] == ["restaurant/a&b"]

    background_url = recipe_edit_page_url(SOURCE_URL, viewer_user_id="user-a")
    assert parse_qs(urlsplit(background_url).query)["viewer_user_id"] == ["user-a"]


def test_legacy_stored_private_links_are_refreshed_for_the_current_viewer(
    monkeypatch,
    tmp_path,
):
    app = configured_app(monkeypatch, tmp_path)
    legacy_cover = (
        "/recipe_cover_image?url="
        "https%3A%2F%2Fexample.test%2Flegacy%3Fx%3D1%26y%3D2"
    )

    with app.test_request_context("/"):
        session["user_id"] = "user-a"
        canonical = canonicalize_private_recipe_url(legacy_cover)
        rendered = main_routes.cookbook_cover_image_for_view({
            "url": "https://example.test/legacy?x=1&y=2",
            "name": "Legacy Recipe",
            "cover_image": {
                "src": legacy_cover,
                "thumb_url": f"{legacy_cover}&variant=thumb",
                "srcset": f"{legacy_cover}&variant=thumb 240w",
            },
        })

    for value in (
        canonical,
        rendered["src"],
        rendered["thumb_url"],
        rendered["srcset"].split()[0],
    ):
        query = parse_qs(urlsplit(value).query)
        assert query["viewer_user_id"] == ["user-a"]
        assert value.count("viewer_user_id=") == 1
        assert query["url"] == ["https://example.test/legacy?x=1&y=2"]
