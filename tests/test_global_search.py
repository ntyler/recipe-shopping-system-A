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
    assert 'data-global-search-results-url="/search"' in header
    assert 'role="combobox"' in header
    assert 'aria-autocomplete="list"' in header
    assert 'aria-expanded="false"' in header
    assert 'role="listbox"' in header
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
    assert "new AbortController()" in search_script
    assert 'endpoint.searchParams.set("limit", String(GLOBAL_APP_SEARCH_RESULT_LIMIT))' in search_script
    assert '.filter(group => group.key !== "pages")' in search_script
    assert 'document.querySelectorAll(".app-sidebar-nav .app-nav-link")' in search_script
    assert 'event.key === "ArrowDown" || event.key === "ArrowUp"' in search_script
    assert 'event.key === "Enter"' in search_script
    assert 'event.key === "Escape"' in search_script
    assert 'document.createElement("mark")' in search_script
    assert "Searching AI Pantry…" in search_script
    assert "No matching AI Pantry records or pages found." in search_script
    assert "Search error. Please try again." in search_script
    assert "View all results for" in search_script
    assert "innerHTML" not in search_script


def test_global_search_dropdown_and_full_results_are_responsive_dark_theme_surfaces():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert ".app-global-search-dropdown {" in css
    assert "max-height: min(70vh, 560px);" in css
    assert ".app-global-search-result.is-active" in css
    assert ".app-global-search-result-copy mark" in css
    assert ".app-global-search-state.is-loading::before" in css
    assert ".global-search-results-page {" in css
    assert ".global-search-result-filters a[aria-current=\"page\"]" in css
    assert "max-height: min(60vh, 460px);" in css
