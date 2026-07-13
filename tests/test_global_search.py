import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def seed_workspace(root, recipe_name="Tomato Soup", pantry_name="Fresh Tomato"):
    root.mkdir(parents=True, exist_ok=True)
    recipe_url = "https://example.test/recipes/tomato-soup"
    (root / "urls.txt").write_text(recipe_url + "\n", encoding="utf-8")
    (root / "shopping_list.txt").write_text("Tomatoes\nBasil\n", encoding="utf-8")
    write_json(root / "cookbooks.json", {
        "cookbooks": [{
            "id": "weeknight",
            "name": "Weeknight Favorites",
            "recipes": [{
                "url": recipe_url,
                "name": recipe_name,
                "description": "A quick garden soup",
                "ingredients": ["tomatoes", "basil"],
            }],
        }],
    })
    write_json(root / "restaurant_menus.json", {
        "restaurants": [{
            "id": "restaurant-1",
            "restaurant_name": "Garden Cafe",
            "city": "Indianapolis",
        }],
        "menus": [{
            "id": "menu-1",
            "restaurant_id": "restaurant-1",
            "menu_title": "Garden Lunch Menu",
        }],
        "sections": [{
            "id": "section-1",
            "menu_id": "menu-1",
            "section_name": "Soups",
        }],
        "items": [{
            "id": "item-1",
            "menu_id": "menu-1",
            "restaurant_id": "restaurant-1",
            "menu_section_id": "section-1",
            "item_name": "Tomato Bisque",
            "menu_description": "Creamy tomato soup",
        }],
        "pdf_logs": [],
    })
    write_json(root / "pantry_inventory.json", {
        "items": [{
            "id": "pantry-1",
            "ingredient_name": pantry_name,
            "product_name": pantry_name,
            "storage_location": "fridge",
            "status": "available",
        }],
    })
    write_json(root / "meal_plan.json", {
        "meals": [{
            "id": "meal-1",
            "date": "2026-07-12",
            "meal_type": "dinner",
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
        }],
    })
    write_json(root / "recipe-extractor" / "data" / "recipe_ingredients.json", {
        recipe_url: {
            "url": recipe_url,
            "name": recipe_name,
            "ingredients": ["tomatoes", "basil"],
        },
    })
    write_json(root / "recipe-extractor" / "data" / "store_settings.json", {
        "stores": {
            "market": {
                "label": "Neighborhood Market",
                "url": "https://market.example/search?q=",
                "urlStoreSelector": "https://market.example/stores",
            },
        },
        "enabled_stores": ["market"],
    })
    return recipe_url


def configured_app(monkeypatch, tmp_path):
    from PushShoppingList.app import create_app
    from PushShoppingList.services import global_search_service
    from PushShoppingList.services import recipe_master_data_service
    from PushShoppingList.services import storage_service
    from PushShoppingList.services import user_account_service

    user_data = tmp_path / "users"
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", user_data)
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(recipe_master_data_service, "RECIPE_MASTER_DB_PATH", tmp_path / "recipe_master.sqlite3")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "accounts.json")
    user_account_service.save_users({
        "users": [
            {
                "user_id": "user-one",
                "email": "one@example.test",
                "first_name": "User",
                "last_name": "One",
                "account_status": "active",
            },
            {
                "user_id": "user-two",
                "email": "two@example.test",
                "first_name": "User",
                "last_name": "Two",
                "account_status": "active",
            },
        ],
    })
    seed_workspace(user_data / "user-one")
    seed_workspace(
        user_data / "user-two",
        recipe_name="Foreign Secret Recipe",
        pantry_name="Foreign Secret Pantry Item",
    )

    with recipe_master_data_service.recipe_master_connection() as connection:
        connection.execute(
            """
            INSERT INTO ingredients
                (user_id, name, normalized_name, store_section, image_url, image_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, '', '', ?, ?)
            """,
            ("user-one", "Tomato", "tomato", "PRODUCE", "2026-07-12T00:00:00Z", "2026-07-12T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO ingredients
                (user_id, name, normalized_name, store_section, image_url, image_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, '', '', ?, ?)
            """,
            ("user-two", "Foreign Secret Spice", "foreign secret spice", "SPICES & SEASONINGS", "2026-07-12T00:00:00Z", "2026-07-12T00:00:00Z"),
        )

    global_search_service.clear_global_search_cache()
    app = create_app()
    app.config.update(TESTING=True)
    return app, user_data


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def flattened_results(payload):
    return [result for group in payload.get("groups", []) for result in group.get("results", [])]


def test_global_search_is_authenticated_grouped_limited_and_user_scoped(monkeypatch, tmp_path):
    app, _user_data = configured_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        unauthorized = client.get("/api/global-search?q=tomato")
        assert unauthorized.status_code == 401

        sign_in(client, "user-one")
        response = client.get("/api/global-search?q=tom&limit=8&user_id=user-two")
        infix_response = client.get("/api/global-search?q=mato&limit=8")

    assert response.status_code == 200
    payload = response.get_json()
    results = flattened_results(payload)
    groups = {group["key"] for group in payload["groups"]}

    assert payload["ok"] is True
    assert payload["query"] == "tom"
    assert len(results) <= 8
    assert {"recipes", "ingredients", "menus", "shopping-lists", "pantry"}.intersection(groups)
    assert any(result["title"] == "Tomato Soup" for result in results)
    assert all("Foreign Secret" not in result["title"] for result in results)
    assert all(set(result) == {"id", "title", "type", "secondary", "url", "thumbnail_url", "icon"} for result in results)
    assert any(result["title"] == "Tomato Soup" for result in flattened_results(infix_response.get_json()))


def test_global_search_does_not_build_record_projection_below_two_characters(monkeypatch, tmp_path):
    app, _user_data = configured_app(monkeypatch, tmp_path)
    from PushShoppingList.services import global_search_service

    monkeypatch.setattr(
        global_search_service,
        "cached_projection",
        lambda: (_ for _ in ()).throw(AssertionError("record projection should not be loaded")),
    )
    with app.test_client() as client:
        sign_in(client, "user-one")
        response = client.get("/api/global-search?q=r")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["query_too_short"] is True
    assert payload["groups"] == []


def test_global_search_typed_group_order_and_header_caps():
    from PushShoppingList.services import global_search_service

    assert [key for key, _label in global_search_service.GROUPS] == [
        "recipes",
        "ingredients",
        "menus",
        "restaurants",
        "cookbooks",
        "shopping-lists",
        "pantry",
        "meal-planner",
        "stores",
        "equipment",
        "pages",
    ]
    assert dict(global_search_service.GROUPS)["meal-planner"] == "MEAL PLAN"

    ranked = [
        (1000 - index, {"group": group, "title": f"{group}-{index}"})
        for group in global_search_service.HEADER_GROUP_LIMITS
        for index in range(6)
    ]
    visible = global_search_service.limited_header_results(ranked, 12)
    counts = {}
    for _score, item in visible:
        counts[item["group"]] = counts.get(item["group"], 0) + 1

    assert len(visible) == 12
    assert all(
        count <= global_search_service.HEADER_GROUP_LIMITS[group]
        for group, count in counts.items()
    )
    assert global_search_service.HEADER_GROUP_LIMITS["recipes"] == 4
    assert global_search_service.HEADER_GROUP_LIMITS["ingredients"] == 3
    assert global_search_service.HEADER_GROUP_LIMITS["menus"] == 3
    assert global_search_service.HEADER_GROUP_LIMITS["restaurants"] == 3
    assert global_search_service.HEADER_GROUP_LIMITS["pages"] == 2

    page_urls = {title: url for title, _secondary, url in global_search_service.PAGE_SHORTCUTS}
    assert page_urls["Shopping Lists"] == "/#shoppingViewsSection"
    assert page_urls["Pantry"] == "/#aiPantrySection"
    assert page_urls["Import Recipes"] == "/#recipeUrlsPage"
    assert page_urls["Import Menus"] == "/#menuUrlPage"


def test_recent_global_search_records_are_actual_sanitized_and_workspace_scoped(monkeypatch, tmp_path):
    app, _user_data = configured_app(monkeypatch, tmp_path)
    from flask import session
    from PushShoppingList.services import global_search_service

    with app.test_client() as client:
        sign_in(client, "user-one")
        typed = client.get("/api/global-search?q=tomato&limit=12").get_json()
        recipe = next(
            result
            for group in typed["groups"]
            if group["key"] == "recipes"
            for result in group["results"]
        )

        recorded = client.post("/api/global-search/recent", json={
            "group": "recipes",
            "id": recipe["id"],
            "title": "Spoofed title",
            "url": "https://evil.example/steal",
        })
        client.post("/api/global-search/recent", json={"group": "pantry", "id": "pantry-1"})
        client.post("/api/global-search/recent", json={"group": "recipes", "id": recipe["id"]})
        user_one_recent = client.get("/api/global-search?q=&limit=99")

        with client.session_transaction() as user_two_session:
            user_two_session["user_id"] = "user-two"
        user_two_recent = client.get("/api/global-search?q=&limit=4")

    assert recorded.status_code == 200
    recorded_result = recorded.get_json()["result"]
    assert recorded_result["title"] == "Tomato Soup"
    assert recorded_result["url"].startswith("/")
    assert "evil.example" not in recorded_result["url"]

    user_one_payload = user_one_recent.get_json()
    assert user_one_payload["total_count"] == 2
    assert user_one_payload["groups"][0]["key"] == "recent"
    assert len(user_one_payload["groups"][0]["results"]) <= 4
    assert user_one_payload["groups"][0]["results"][0]["title"] == "Tomato Soup"
    assert user_one_payload["groups"][0]["results"][0]["tracking_group"] == "recipes"
    assert user_one_payload["groups"][0]["results"][1]["tracking_group"] == "pantry"
    assert user_two_recent.get_json()["groups"] == []

    with app.test_request_context("/"):
        session["is_guest"] = True
        session["guest_session_id"] = "guest-one"
        assert global_search_service.recent_global_search()["groups"] == []


def test_recent_global_search_empty_read_never_builds_broad_projection(monkeypatch, tmp_path):
    app, _user_data = configured_app(monkeypatch, tmp_path)
    from PushShoppingList.services import global_search_service

    monkeypatch.setattr(
        global_search_service,
        "cached_projection",
        lambda: (_ for _ in ()).throw(AssertionError("empty recent lookup must stay lightweight")),
    )
    with app.test_client() as client:
        sign_in(client, "user-one")
        response = client.get("/api/global-search?q=&limit=4")

    assert response.status_code == 200
    assert response.get_json()["groups"] == []


def test_recent_global_search_rejects_non_record_and_stale_ids(monkeypatch, tmp_path):
    app, _user_data = configured_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-one")
        malformed_result = client.post("/api/global-search/recent", json=["recipes", "anything"])
        page_result = client.post("/api/global-search/recent", json={"group": "pages", "id": "page:1"})
        stale_result = client.post("/api/global-search/recent", json={"group": "recipes", "id": "missing"})

    assert malformed_result.status_code == 400
    assert page_result.status_code == 400
    assert stale_result.status_code == 404


def test_recent_global_search_discards_unsafe_stored_urls(monkeypatch, tmp_path):
    app, user_data = configured_app(monkeypatch, tmp_path)
    write_json(user_data / "user-one" / "global_search_recent.json", {
        "records": [{
            "group": "recipes",
            "viewed_at": "2026-07-12T00:00:00Z",
            "result": {
                "id": "unsafe",
                "title": "Unsafe",
                "type": "Recipe",
                "secondary": "",
                "url": "https://evil.example/steal",
                "thumbnail_url": "javascript:alert(1)",
                "icon": "recipes",
            },
        }],
    })

    with app.test_client() as client:
        sign_in(client, "user-one")
        payload = client.get("/api/global-search?q=&limit=4").get_json()

    assert payload["groups"] == []


def test_global_search_projection_rebuilds_after_scoped_source_changes(monkeypatch, tmp_path):
    app, user_data = configured_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-one")
        before = client.get("/api/global-search?q=dragonfruit").get_json()
        assert before["total_count"] == 0

        pantry_path = user_data / "user-one" / "pantry_inventory.json"
        write_json(pantry_path, {
            "items": [{
                "id": "pantry-new",
                "ingredient_name": "Dragonfruit",
                "product_name": "Dragonfruit",
                "status": "available",
            }],
        })
        stat = pantry_path.stat()
        os.utime(pantry_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        after = client.get("/api/global-search?q=dragon").get_json()

    assert any(result["title"] == "Dragonfruit" for result in flattened_results(after))


def test_full_search_results_route_renders_group_counts_and_filters(monkeypatch, tmp_path):
    app, _user_data = configured_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-one")
        response = client.get("/search?q=tomato&type=recipes")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Search results" in html
    assert "Tomato Soup" in html
    assert "RECIPES" in html
    assert "Fresh Tomato" not in html
    assert html.count('data-app-header') == 1


def test_shared_header_global_search_is_one_accessible_combobox():
    header = (ROOT / "PushShoppingList/templates/includes/app_header.html").read_text(encoding="utf-8")
    authenticated_pages = list((ROOT / "PushShoppingList/templates").glob("*.html"))

    assert header.count("data-global-search-form") == 1
    assert 'onsubmit="return submitGlobalAppSearch(this)"' in header
    assert 'data-global-search-endpoint="/api/global-search"' in header
    assert 'data-global-search-recent-url="/api/global-search/recent"' in header
    assert 'data-global-search-results-url="/search"' in header
    assert 'role="combobox"' in header
    assert 'aria-autocomplete="list"' in header
    assert 'aria-expanded="false"' in header
    assert 'role="listbox"' in header
    assert 'data-global-search-visible-status' in header
    assert 'class="app-search-submit" tabindex="-1"' in header
    assert "<datalist" not in header
    assert all("submitRecipeEditGlobalSearch" not in page.read_text(encoding="utf-8") for page in authenticated_pages)


def test_global_search_client_debounces_groups_and_supports_keyboard_navigation():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("const GLOBAL_APP_SEARCH_DEBOUNCE_MS")
    end = script.index("function recipeBrowseCards", start)
    search_script = script[start:end]

    assert "GLOBAL_APP_SEARCH_DEBOUNCE_MS = 250" in search_script
    assert "GLOBAL_APP_SEARCH_MIN_QUERY_LENGTH = 2" in search_script
    assert "GLOBAL_APP_SEARCH_OPTION_LIMIT = 12" in search_script
    assert "GLOBAL_APP_SEARCH_RECENT_LIMIT = 4" in search_script
    assert "GLOBAL_APP_SEARCH_QUICK_ACTION_LIMIT = 3" in search_script
    assert "GLOBAL_APP_SEARCH_PAGE_LIMIT = 3" in search_script
    assert "GLOBAL_APP_SEARCH_TYPED_PAGE_LIMIT = 2" in search_script
    assert "new AbortController()" in search_script
    assert 'endpoint.searchParams.set("limit", String(GLOBAL_APP_SEARCH_RESULT_LIMIT))' in search_script
    assert '.filter(group => group.key !== "pages" && group.key !== "recent")' in search_script
    assert 'data-global-search-page-shortcut' in search_script
    assert 'data-global-search-quick-action' in search_script
    assert 'label: "RECENT"' in search_script
    assert 'trackingGroup: result.tracking_group || ""' in search_script
    assert 'label: "QUICK ACTIONS"' in search_script
    assert 'label: "PAGES"' in search_script
    assert 'event.key === "ArrowDown" || event.key === "ArrowUp"' in search_script
    assert 'event.key === "Enter"' in search_script
    assert 'event.key === "Escape"' in search_script
    assert 'document.createElement("mark")' in search_script
    assert 'context.append(globalAppSearchHighlightedTitle(result.secondary, query))' in search_script
    assert 'option.tabIndex = -1' in search_script
    assert 'section.setAttribute("role", "group")' in search_script
    assert 'section.setAttribute("aria-labelledby", heading.id)' in search_script
    assert 'event.key === "ArrowDown" ? 0 : options.length - 1' in search_script
    assert "Searching…" in search_script
    assert 'No results for “${query}”' in search_script
    assert "Search could not be completed." in search_script
    assert "Try again." in search_script
    assert "View all results for" in search_script
    assert 'body: JSON.stringify({ group: result.trackingGroup, id: result.id })' in search_script
    assert 'credentials: "same-origin"' in search_script
    assert "keepalive: true" in search_script
    assert 'event.ctrlKey || event.metaKey || event.shiftKey || event.altKey' in search_script
    assert "innerHTML" not in search_script


def test_global_search_empty_shortcuts_are_explicit_compact_and_reuse_sidebar_links():
    sidebar = (ROOT / "PushShoppingList/templates/includes/app_sidebar.html").read_text(encoding="utf-8")

    assert sidebar.count("data-global-search-page-shortcut") == 3
    assert sidebar.count("data-global-search-quick-action") == 3
    assert 'data-global-search-title="Import Recipe URL"' in sidebar
    assert 'data-global-search-secondary="Import a recipe from a URL"' in sidebar
    assert 'data-global-search-title="Import Menu URL"' in sidebar
    assert 'data-global-search-secondary="Import a restaurant menu from a URL"' in sidebar
    assert 'data-global-search-title="Scan Barcode"' in sidebar
    assert 'data-global-search-secondary="Scan a pantry barcode"' in sidebar


def test_global_search_dropdown_and_full_results_are_responsive_dark_theme_surfaces():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert ".app-global-search-dropdown {" in css
    assert "width: 100%;" in css
    assert "max-height: min(70vh, 440px);" in css
    assert "min-height: 48px;" in css
    assert ".app-global-search-result.is-active" in css
    assert ".app-global-search-result-copy mark" in css
    assert ".app-global-search-state.is-loading::before" in css
    assert ".global-search-results-page {" in css
    assert ".global-search-result-filters a[aria-current=\"page\"]" in css
    assert "max-height: min(60vh, 440px);" in css
