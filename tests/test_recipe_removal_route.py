from pathlib import Path

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import cookbook_service
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


def test_current_recipe_menu_has_clear_selected_recipes_action():
    template = Path("PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "Clear selected recipes" in template
    assert "clearSelectedCurrentRecipes(this)" in template
    assert '"Select at least one recipe to clear."' in script
    assert 'body: JSON.stringify({ recipe_urls: urls })' in script


def test_cookbook_menu_has_selected_delete_actions():
    template = Path("PushShoppingList/templates/sections/cookbooks.html").read_text(
        encoding="utf-8",
    )
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    routes = Path("PushShoppingList/routes/main_routes.py").read_text(encoding="utf-8")

    assert "Delete selected recipes" in template
    assert "Delete and purge selected recipes" in template
    assert "deleteSelectedCookbookRecipes(this)" in template
    assert "purgeSelectedCookbookRecipes(this)" in template
    assert "function selectedCookbookRecipeUrlsForCard" in script
    assert "function deleteSelectedCookbookRecipes" in script
    assert "function purgeSelectedCookbookRecipes" in script
    assert "remove_selected_recipes" in routes
    assert "purge_selected_recipes" in routes


def test_fetch_clear_current_recipes_reuses_recipe_cleanup(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(
        recipe_routes,
        "load_recipe_urls",
        lambda: ["https://example.com/chili", "https://example.com/soup"],
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
            "/api/recipe_urls/clear",
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "cleared_recipe_count": 2,
        "redirect_url": "/",
    }
    assert calls == [
        ("ingredients", "https://example.com/chili"),
        ("url", "https://example.com/chili"),
        ("ingredients", "https://example.com/soup"),
        ("url", "https://example.com/soup"),
    ]


def test_fetch_clear_selected_current_recipes_reuses_recipe_cleanup(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(
        recipe_routes,
        "load_recipe_urls",
        lambda: [
            "https://example.com/chili",
            "https://example.com/soup",
            "https://example.com/tacos",
        ],
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
            "/api/recipe_urls/clear",
            json={"recipe_urls": ["https://example.com/soup", "https://example.com/tacos"]},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "cleared_recipe_count": 2,
        "redirect_url": "/",
    }
    assert calls == [
        ("ingredients", "https://example.com/soup"),
        ("url", "https://example.com/soup"),
        ("ingredients", "https://example.com/tacos"),
        ("url", "https://example.com/tacos"),
    ]


def test_fetch_clear_selected_current_recipes_requires_selection(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(recipe_routes, "load_recipe_urls", lambda: ["https://example.com/chili"])
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
            "/api/recipe_urls/clear",
            json={"recipe_urls": []},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "Select at least one recipe to clear.",
    }
    assert calls == []


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


def test_fetch_purge_cookbook_recipes_keeps_cookbook_and_reuses_cleanup(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    def fake_purge_cookbook_recipe_urls(cookbook_id):
        calls.append(("cookbook", cookbook_id))
        return ["https://example.com/chili", "https://example.com/soup"]

    monkeypatch.setattr(
        main_routes,
        "purge_cookbook_recipe_urls",
        fake_purge_cookbook_recipe_urls,
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
        response = client.post(
            "/api/cookbooks/dinner/purge_recipes",
            json={"confirm_purge_recipes": "PURGE"},
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


def test_fetch_purge_unclassified_recipes_only_clears_unclassified(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(
        main_routes,
        "load_cookbooks",
        lambda: {"cookbooks": [{"id": "unclassified", "name": "unclassified", "recipes": []}]},
    )

    def fake_purge_unclassified_cookbook_recipe_urls(cookbook_id):
        calls.append(("unclassified", cookbook_id))
        return ["https://example.com/chili", "https://example.com/soup"]

    monkeypatch.setattr(
        main_routes,
        "purge_unclassified_cookbook_recipe_urls",
        fake_purge_unclassified_cookbook_recipe_urls,
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
        response = client.post(
            "/api/cookbooks/unclassified/purge_recipes",
            json={"confirm_purge_recipes": "PURGE"},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "purged_recipe_count": 2}
    assert calls == [
        ("unclassified", "unclassified"),
    ]


def test_fetch_purge_unclassified_recipes_requires_opt_in(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    monkeypatch.setattr(
        main_routes,
        "purge_cookbook_recipe_urls",
        lambda cookbook_id: calls.append(("cookbook", cookbook_id)),
    )

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/api/cookbooks/unclassified/purge_recipes",
            json={"confirm_purge_recipes": "nope"},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "Type PURGE to confirm purging cookbook recipes.",
    }
    assert calls == []


def test_fetch_delete_unclassified_cookbook_is_blocked(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    monkeypatch.setattr(cookbook_service, "COOKBOOKS_FILE", tmp_path / "cookbooks.json")
    cookbook_service.save_cookbooks({
        "cookbooks": [
            {
                "id": "unclassified",
                "name": "unclassified",
                "recipes": [{"url": "https://example.com/chili", "name": "Chili"}],
            },
        ],
    })

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.delete(
            "/api/cookbooks/unclassified",
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "The unclassified cookbook cannot be deleted.",
    }
    payload = cookbook_service.load_cookbooks()
    assert [cookbook["id"] for cookbook in payload["cookbooks"]] == ["unclassified"]
    assert payload["cookbooks"][0]["recipes"][0]["url"] == "https://example.com/chili"


def test_fetch_purge_unclassified_cookbook_is_blocked(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []
    monkeypatch.setattr(cookbook_service, "COOKBOOKS_FILE", tmp_path / "cookbooks.json")
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
    cookbook_service.save_cookbooks({
        "cookbooks": [
            {
                "id": "unclassified",
                "name": "unclassified",
                "recipes": [{"url": "https://example.com/chili", "name": "Chili"}],
            },
        ],
    })

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.delete(
            "/api/cookbooks/unclassified/purge",
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "The unclassified cookbook cannot be purged.",
    }
    assert calls == []
    payload = cookbook_service.load_cookbooks()
    assert [cookbook["id"] for cookbook in payload["cookbooks"]] == ["unclassified"]
    assert payload["cookbooks"][0]["recipes"][0]["url"] == "https://example.com/chili"


def test_fetch_rename_unclassified_cookbook_is_blocked(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    monkeypatch.setattr(cookbook_service, "COOKBOOKS_FILE", tmp_path / "cookbooks.json")
    cookbook_service.save_cookbooks({
        "cookbooks": [
            {
                "id": "unclassified",
                "name": "unclassified",
                "recipes": [{"url": "https://example.com/chili", "name": "Chili"}],
            },
        ],
    })

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/api/cookbooks/unclassified/rename",
            data={"name": "Loose Recipes"},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "The unclassified cookbook cannot be renamed.",
    }
    payload = cookbook_service.load_cookbooks()
    assert payload["cookbooks"][0]["name"] == "unclassified"


def test_fetch_remove_selected_cookbook_recipes_reuses_batch_removal(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    def fake_remove_recipes_from_cookbook(cookbook_id, recipe_urls):
        calls.append(("cookbook", cookbook_id, list(recipe_urls)))
        return ["https://example.com/chili", "https://example.com/soup"]

    monkeypatch.setattr(
        main_routes,
        "remove_recipes_from_cookbook",
        fake_remove_recipes_from_cookbook,
    )

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/api/cookbooks/dinner/remove_selected_recipes",
            data={
                "recipe_urls": [
                    "https://example.com/chili",
                    "https://example.com/soup",
                ],
            },
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "removed_recipe_count": 2}
    assert calls == [
        (
            "cookbook",
            "dinner",
            ["https://example.com/chili", "https://example.com/soup"],
        ),
    ]


def test_fetch_move_selected_cookbook_recipes_reuses_bulk_move_route(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    def fake_move_recipes_to_cookbook(
        cookbook_id,
        recipe_urls,
        recipe_rows,
        overwrite_existing=False,
        insert_before_recipe_url="",
        insert_after_recipe_url="",
    ):
        calls.append({
            "cookbook_id": cookbook_id,
            "recipe_urls": list(recipe_urls),
            "recipe_rows": recipe_rows,
            "overwrite_existing": overwrite_existing,
            "insert_before_recipe_url": insert_before_recipe_url,
            "insert_after_recipe_url": insert_after_recipe_url,
        })

    monkeypatch.setattr(main_routes, "recipe_url_rows", lambda: ["stub-row"])
    monkeypatch.setattr(main_routes, "recipe_view_rows", lambda rows: ["recipe-row"])
    monkeypatch.setattr(main_routes, "move_recipes_to_cookbook", fake_move_recipes_to_cookbook)

    with app.test_client() as client:
        configure_signed_in_user(monkeypatch, tmp_path, client)
        response = client.post(
            "/api/cookbooks/move_recipes",
            data={
                "cookbook_id": "dinner",
                "recipe_urls": [
                    "https://example.com/chili",
                    "https://example.com/soup",
                ],
                "overwrite_existing": "1",
            },
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert calls == [{
        "cookbook_id": "dinner",
        "recipe_urls": ["https://example.com/chili", "https://example.com/soup"],
        "recipe_rows": ["recipe-row"],
        "overwrite_existing": True,
        "insert_before_recipe_url": "",
        "insert_after_recipe_url": "",
    }]


def test_fetch_purge_selected_cookbook_recipes_reuses_recipe_cleanup(monkeypatch, tmp_path):
    app = create_app()
    app.config.update(TESTING=True)
    calls = []

    def fake_purge_selected_cookbook_recipe_urls(cookbook_id, recipe_urls):
        calls.append(("cookbook", cookbook_id, list(recipe_urls)))
        return ["https://example.com/chili", "https://example.com/soup"]

    monkeypatch.setattr(
        main_routes,
        "purge_selected_cookbook_recipe_urls",
        fake_purge_selected_cookbook_recipe_urls,
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
        response = client.post(
            "/api/cookbooks/dinner/purge_selected_recipes",
            json={"recipe_urls": ["https://example.com/chili", "https://example.com/soup"]},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "purged_recipe_count": 2}
    assert calls == [
        (
            "cookbook",
            "dinner",
            ["https://example.com/chili", "https://example.com/soup"],
        ),
        ("ingredients", "https://example.com/chili"),
        ("url", "https://example.com/chili"),
        ("ingredients", "https://example.com/soup"),
        ("url", "https://example.com/soup"),
    ]
