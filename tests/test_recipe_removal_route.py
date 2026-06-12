from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def configure_signed_in_user(monkeypatch, tmp_path, client, user_id="remove-user"):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [{
            "user_id": user_id,
            "email": "remove@example.com",
            "username": "remove",
            "notification_topic": "topic",
            "ntfy_topic": "topic",
            "account_status": "active",
        }],
    })

    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_fetch_remove_recipe_returns_json_without_redirect(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(
        recipe_routes,
        "remove_recipe_and_unused_ingredients",
        lambda url: calls.append(("ingredients", url)),
    )
    monkeypatch.setattr(
        recipe_routes,
        "remove_recipe_url",
        lambda url: calls.append(("url", url)),
    )

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/remove_recipe",
            data={"url": " https://example.com/soup "},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "redirect_url": "/"}
    assert calls == [
        ("ingredients", "https://example.com/soup"),
        ("url", "https://example.com/soup"),
    ]


def test_fetch_remove_recipe_requires_url(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/remove_recipe",
            data={"url": "   "},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "Recipe URL is required."}


def test_regular_remove_recipe_form_still_redirects(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)

    monkeypatch.setattr(recipe_routes, "remove_recipe_and_unused_ingredients", lambda url: None)
    monkeypatch.setattr(recipe_routes, "remove_recipe_url", lambda url: None)

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post("/remove_recipe", data={"url": "https://example.com/soup"})

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_fetch_purge_recipe_returns_json_without_redirect(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(
        recipe_routes,
        "purge_recipe_from_all_cookbooks",
        lambda url: calls.append(("cookbooks", url)),
    )
    monkeypatch.setattr(
        recipe_routes,
        "remove_recipe_and_unused_ingredients",
        lambda url: calls.append(("ingredients", url)),
    )
    monkeypatch.setattr(
        recipe_routes,
        "remove_recipe_url",
        lambda url: calls.append(("url", url)),
    )

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/purge_recipe",
            data={"url": "https://example.com/soup"},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "redirect_url": "/"}
    assert calls == [
        ("cookbooks", "https://example.com/soup"),
        ("ingredients", "https://example.com/soup"),
        ("url", "https://example.com/soup"),
    ]


def test_fetch_purge_cookbook_reuses_recipe_cleanup(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    def fake_delete_cookbook_and_purge_recipe_urls(cookbook_id):
        calls.append(("cookbook", cookbook_id))
        return ["https://example.com/chili", "https://example.com/soup"]

    monkeypatch.setattr(
        main_routes,
        "delete_cookbook_and_purge_recipe_urls",
        fake_delete_cookbook_and_purge_recipe_urls,
    )
    monkeypatch.setattr(
        main_routes,
        "remove_recipe_and_unused_ingredients",
        lambda url: calls.append(("ingredients", url)),
    )
    monkeypatch.setattr(
        main_routes,
        "remove_recipe_url",
        lambda url: calls.append(("url", url)),
    )

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.delete(
            "/api/cookbooks/dinner/purge",
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "purged_recipe_count": 2}
    assert calls == [
        ("cookbook", "dinner"),
        ("ingredients", "https://example.com/chili"),
        ("url", "https://example.com/chili"),
        ("ingredients", "https://example.com/soup"),
        ("url", "https://example.com/soup"),
    ]
