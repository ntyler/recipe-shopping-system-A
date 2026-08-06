import json
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service
from PushShoppingList.services.ingredient_unit_service import unit_registry_payload


MASTER_DATA_PAGES = (
    "/admin/master-data/ingredients",
    "/admin/master-data/equipment",
    "/admin/master-data/units",
    "/admin/master-data/types",
    "/admin/master-data/store-sections",
)


@pytest.fixture
def master_data_app(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({
            "users": [
                {
                    "user_id": "user-a",
                    "username": "user-a",
                    "email": "user-a@example.com",
                    "first_name": "User",
                    "last_name": "A",
                    "account_status": "active",
                },
                {
                    "user_id": "admin-user",
                    "username": "admin",
                    "email": "admin@example.com",
                    "first_name": "Admin",
                    "last_name": "User",
                    "account_status": "active",
                    "admin_access_enabled": True,
                },
                {
                    "user_id": "user-b",
                    "username": "user-b",
                    "email": "user-b@example.com",
                    "first_name": "User",
                    "last_name": "B",
                    "account_status": "active",
                },
            ],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        master_data,
        "RECIPE_MASTER_DB_PATH",
        tmp_path / "recipe_master.sqlite3",
    )
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(user_account_service, "USERS_FILE", users_file)
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_DATA_DIR",
        tmp_path / "guests",
    )
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")

    app = create_app()
    app.config.update(TESTING=True)
    return app


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def seed_workspace_records():
    records = (
        ("user-a", "Tomato", "Large pot", "Produce"),
        ("user-a", "Apple", "Peeler", "Produce"),
        ("admin-user", "Admin salt", "Admin spoon", "Spices & Seasonings"),
        ("user-b", "Garlic", "Whisk", "Spices & Seasonings"),
    )
    for user_id, ingredient, equipment, store_section in records:
        master_data.sync_recipe_master_records(
            f"https://example.com/{user_id}/{ingredient.lower().replace(' ', '-')}",
            recipe_data={
                "ingredients": [{
                    "ingredient": ingredient,
                    "store_section": store_section,
                }],
                "equipment": [{"equipment": equipment}],
            },
            user_id=user_id,
        )


def location_parts(response):
    location = response.headers["Location"]
    split = urlsplit(location)
    return split.path, parse_qsl(split.query, keep_blank_values=True)


def query_multimap(pairs):
    result = {}
    for key, value in pairs:
        result.setdefault(key, []).append(value)
    return result


def assert_private_no_store(response):
    assert response.headers.get("Cache-Control") == "private, no-store"
    assert response.headers.get("Pragma") == "no-cache"


def assert_generic_forbidden(response, *private_values):
    assert response.status_code == 403
    body = response.get_data(as_text=True)
    for value in private_values:
        assert value not in body
    assert_private_no_store(response)


def canonical_query_from_href(href):
    split = urlsplit(href)
    return split.path, query_multimap(parse_qsl(split.query, keep_blank_values=True))


@pytest.mark.parametrize("path", MASTER_DATA_PAGES)
def test_registered_master_data_pages_derive_viewer_from_session(
    master_data_app,
    path,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(path)

    assert response.status_code == 200
    assert "Location" not in response.headers
    assert response.request.query_string == b""
    assert_private_no_store(response)


@pytest.mark.parametrize("path", MASTER_DATA_PAGES)
def test_registered_master_data_pages_remove_legacy_matching_viewer(
    master_data_app,
    path,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(path, query_string={"viewer_user_id": "user-a"})
        canonical = client.get(response.headers["Location"])

    assert response.status_code == 302
    redirect_path, pairs = location_parts(response)
    assert redirect_path == path
    assert pairs == []
    assert_private_no_store(response)
    assert canonical.status_code == 200
    assert "Location" not in canonical.headers
    assert_private_no_store(canonical)


def test_units_page_renders_the_persistent_registry_and_unit_editor(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/units")

    assert response.status_code == 200
    assert_private_no_store(response)
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.title.get_text(strip=True) == "Units"
    assert soup.select_one("[data-unit-master-page]") is not None
    assert soup.select_one("h1#unitsTitle").get_text(strip=True) == "Units"
    assert soup.select_one("[data-unit-master-add-button]") is not None
    assert soup.select_one("[data-unit-master-dialog]") is not None
    assert soup.select_one("[data-unit-master-alias-chips]") is not None
    built_in_rows = soup.select("[data-unit-master-row]")
    assert len(built_in_rows) == len(unit_registry_payload()["units"])
    assert {row.select_one("strong").get_text(strip=True) for row in built_in_rows} >= {
        "teaspoon",
        "cup",
        "gram",
        "piece",
    }
    active_tab = soup.select_one("nav.master-data-tabs a.active")
    assert active_tab.get_text(strip=True) == "Units"
    assert urlsplit(active_tab["href"]).path == "/admin/master-data/units"
    assert soup.select_one('script[src*="/static/js/units.js"]') is not None

    units_script = Path("PushShoppingList/static/js/units.js").read_text(
        encoding="utf-8",
    )
    assert 'LEGACY_CUSTOM_UNITS_KEY = "recipeIngredientCustomUnits"' in units_script
    assert "legacyUnitNames" in units_script
    assert 'fetch(root.dataset.createUrl' not in units_script
    assert "const saveUnit = async event =>" in units_script
    assert "updateRegistry(result.registry)" in units_script
    assert "data-unit-master-search" in response.get_data(as_text=True)


@pytest.mark.parametrize("supplied_viewer", ("user-b", "USER-A"))
def test_registered_master_data_page_rejects_mismatching_viewer_generically(
    master_data_app,
    supplied_viewer,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/ingredients",
            query_string={"viewer_user_id": supplied_viewer},
        )

    assert_generic_forbidden(response, "user-a", supplied_viewer)


def test_blank_viewer_redirects_and_duplicate_viewer_parameters_are_bad_request(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        blank = client.get(
            "/admin/master-data/ingredients?viewer_user_id=&search=butter",
        )
        duplicate = client.get(
            "/admin/master-data/ingredients"
            "?viewer_user_id=user-a&viewer_user_id=user-a",
        )
        duplicate_blank = client.get(
            "/admin/master-data/ingredients"
            "?viewer_user_id=&viewer_user_id=",
        )

    assert blank.status_code == 302
    blank_path, blank_pairs = location_parts(blank)
    assert blank_path == "/admin/master-data/ingredients"
    assert query_multimap(blank_pairs) == {
        "search": ["butter"],
    }
    assert_private_no_store(blank)
    for response in (duplicate, duplicate_blank):
        assert response.status_code == 400
        assert_private_no_store(response)


def test_duplicate_admin_target_user_ids_are_bad_request(master_data_app):
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/admin/master-data/ingredients"
            "?viewer_user_id=admin-user&scope=user"
            "&user_id=user-a&user_id=user-b",
        )

    assert response.status_code == 400
    assert_private_no_store(response)


def test_complex_query_values_are_preserved_and_encoded_exactly_once(master_data_app):
    search = "caf\u00e9 & honey / 50% + ?=yes"
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/ingredients",
            query_string={
                "search": search,
                "store_section": "SPICES & SEASONINGS",
                "sort": "name_asc",
                "limit": "250",
                "scope": "mine",
            },
        )

    assert response.status_code == 302
    path, pairs = location_parts(response)
    params = query_multimap(pairs)
    assert path == "/admin/master-data/ingredients"
    assert params == {
        "search": [search],
        "store_section": ["SPICES & SEASONINGS"],
        "sort": ["name_asc"],
        "limit": ["250"],
    }
    assert "%2525" not in response.headers["Location"]
    assert_private_no_store(response)


def test_canonical_cleanup_removes_blank_and_redundant_parameters(master_data_app):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/ingredients"
            "?search=butter&scope=mine&user_id=&store_section="
            "&equipment_section=&sort=updated_at_desc&limit=100&page=1",
        )

        assert response.status_code == 302
        path, pairs = location_parts(response)
        params = query_multimap(pairs)
        assert path == "/admin/master-data/ingredients"
        assert params == {
            "search": ["butter"],
            "sort": ["updated_at_desc"],
            "limit": ["100"],
        }
        assert all(value for _key, value in pairs)
        assert_private_no_store(response)

        canonical = client.get(response.headers["Location"])

    assert canonical.status_code == 200
    assert "Location" not in canonical.headers
    assert_private_no_store(canonical)


@pytest.mark.parametrize(
    "spoofed_query",
    (
        "scope=all&user_id=user-b",
        "scope=user&user_id=user-b",
        "scope=mine&user_id=user-b",
    ),
)
def test_normal_user_scope_spoof_is_canonicalized_to_own_workspace(
    master_data_app,
    spoofed_query,
):
    seed_workspace_records()
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/ingredients"
            f"?viewer_user_id=user-a&{spoofed_query}",
        )

        assert response.status_code == 302
        path, pairs = location_parts(response)
        params = query_multimap(pairs)
        assert path == "/admin/master-data/ingredients"
        assert "viewer_user_id" not in params
        assert "scope" not in params
        assert "user_id" not in params
        assert_private_no_store(response)

        rendered = client.get(response.headers["Location"])

    html = rendered.get_data(as_text=True)
    assert rendered.status_code == 200
    assert "Tomato" in html
    assert "Garlic" not in html
    assert "Admin salt" not in html


def test_admin_mine_specific_user_and_all_scopes_remain_distinct(master_data_app):
    seed_workspace_records()
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        mine = client.get("/admin/master-data/ingredients")
        user = client.get(
            "/admin/master-data/ingredients"
            "?scope=user&user_id=user-b",
        )
        all_users = client.get(
            "/admin/master-data/ingredients?scope=all",
        )

    mine_html = mine.get_data(as_text=True)
    user_html = user.get_data(as_text=True)
    all_html = all_users.get_data(as_text=True)
    assert mine.status_code == 200
    assert "Admin salt" in mine_html
    assert "Tomato" not in mine_html
    assert "Garlic" not in mine_html
    assert user.status_code == 200
    assert "Garlic" in user_html
    assert "Admin salt" not in user_html
    assert "Tomato" not in user_html
    assert all_users.status_code == 200
    assert "Admin salt" in all_html
    assert "Tomato" in all_html
    assert "Garlic" in all_html
    for response in (mine, user, all_users):
        assert_private_no_store(response)


def test_admin_legacy_target_bookmark_redirects_to_explicit_user_scope(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/admin/master-data/equipment"
            "?viewer_user_id=admin-user&user_id=user-b&search=whisk",
        )

    assert response.status_code == 302
    path, pairs = location_parts(response)
    assert path == "/admin/master-data/equipment"
    assert query_multimap(pairs) == {
        "scope": ["user"],
        "user_id": ["user-b"],
        "search": ["whisk"],
    }
    assert_private_no_store(response)


def test_store_section_page_discards_irrelevant_admin_target_scope(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/admin/master-data/store-sections"
            "?viewer_user_id=admin-user&scope=user&user_id=user-b",
        )

    assert response.status_code == 302
    path, pairs = location_parts(response)
    assert path == "/admin/master-data/store-sections"
    assert pairs == []
    assert_private_no_store(response)


def test_admin_target_must_be_a_registered_user(master_data_app):
    unknown_target = "not-a-real-user"
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/admin/master-data/ingredients",
            query_string={
                "viewer_user_id": "admin-user",
                "scope": "user",
                "user_id": unknown_target,
            },
        )

    assert response.status_code == 400
    assert "Unknown user" not in response.get_data(as_text=True)
    assert unknown_target not in response.get_data(as_text=True)
    assert_private_no_store(response)


def test_viewer_id_never_replaces_admin_target_workspace(master_data_app):
    seed_workspace_records()
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/admin/master-data/ingredients"
            "?scope=user&user_id=user-b",
        )
        mismatched_viewer = client.get(
            "/admin/master-data/ingredients"
            "?viewer_user_id=user-b&scope=user&user_id=admin-user",
        )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Garlic" in html
    assert "Admin salt" not in html
    assert_generic_forbidden(mismatched_viewer, "admin-user", "user-b")


def test_guest_master_data_pages_stay_userless_and_reject_nonblank_viewer(
    master_data_app,
):
    with master_data_app.test_client() as client:
        started = client.get("/guest/start")
        assert started.status_code == 302

        userless = client.get("/admin/master-data/ingredients")
        supplied = client.get(
            "/admin/master-data/ingredients?viewer_user_id=user-a",
        )
        with client.session_transaction() as session:
            assert "user_id" not in session

    assert userless.status_code == 200
    assert "viewer_user_id" not in userless.request.query_string.decode("utf-8")
    assert_private_no_store(userless)
    assert_generic_forbidden(supplied, "user-a")


@pytest.mark.parametrize("with_viewer", (False, True))
def test_anonymous_master_data_request_keeps_existing_auth_redirect(
    master_data_app,
    with_viewer,
):
    query = "?viewer_user_id=user-a" if with_viewer else ""
    with master_data_app.test_client() as client:
        response = client.get(f"/admin/master-data/ingredients{query}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#userAccountSection")
    assert_private_no_store(response)


def test_canonical_redirect_completes_once_without_a_loop(master_data_app):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/ingredients?scope=mine&page=1&search=butter",
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert len(response.history) == 1
    assert response.history[0].status_code == 302
    assert response.request.path == "/admin/master-data/ingredients"
    assert parse_qsl(response.request.query_string.decode("utf-8")) == [
        ("search", "butter"),
    ]
    assert_private_no_store(response.history[0])
    assert_private_no_store(response)


def test_filter_forms_only_submit_target_user_for_explicit_user_scope(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        mine = client.get("/admin/master-data/ingredients")
        all_users = client.get(
            "/admin/master-data/ingredients?scope=all",
        )
        specific = client.get(
            "/admin/master-data/ingredients"
            "?scope=user&user_id=user-b",
        )

    for response in (mine, all_users, specific):
        assert response.status_code == 200
        form = BeautifulSoup(
            response.get_data(as_text=True),
            "html.parser",
        ).select_one("form.master-data-filter-form")
        viewer = form.find("input", attrs={"name": "viewer_user_id"})
        assert viewer is None

        target = form.find(attrs={"name": "user_id"})
        target_field = form.select_one("[data-master-target-user-field]")
        target_note = form.select_one("[data-master-target-user-note]")
        if response is specific:
            assert target is not None
            assert target.get("value") == "user-b"
            assert not target.has_attr("disabled")
            assert not target_field.has_attr("hidden")
            assert not target_note.has_attr("hidden")
        else:
            assert target is None or target.has_attr("disabled")
            assert target_field.has_attr("hidden")
            assert target_note.has_attr("hidden")


def test_page_tabs_keep_canonical_admin_target_scope(master_data_app):
    with master_data_app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/admin/master-data/ingredients"
            "?scope=user&user_id=user-b",
        )

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    tab_links = soup.select("nav.master-data-tabs a[href]")
    assert len(tab_links) == len(MASTER_DATA_PAGES)
    assert {urlsplit(link["href"]).path for link in tab_links} == set(MASTER_DATA_PAGES)
    for link in tab_links:
        path, params = canonical_query_from_href(link["href"])
        if path in {
            "/admin/master-data/store-sections",
            "/admin/master-data/units",
            "/admin/master-data/types",
        }:
            # These definitions belong to one session/browser workspace and do
            # not have a coherent aggregate/all-users view.
            assert params == {}
        else:
            assert params == {
                "scope": ["user"],
                "user_id": ["user-b"],
            }


def test_pagination_links_preserve_state_and_remove_page_one(master_data_app):
    seed_workspace_records()
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        first = client.get(
            "/admin/master-data/ingredients",
            query_string={
                "search": "a",
                "sort": "name_asc",
                "limit": "1",
            },
        )
        first_soup = BeautifulSoup(first.get_data(as_text=True), "html.parser")
        next_link = next(
            link
            for link in first_soup.select(".master-data-pagination a[href]")
            if link.get_text(strip=True) == "Next"
        )
        next_path, next_params = canonical_query_from_href(next_link["href"])

        second = client.get(next_link["href"])
        second_soup = BeautifulSoup(second.get_data(as_text=True), "html.parser")
        previous_link = next(
            link
            for link in second_soup.select(".master-data-pagination a[href]")
            if link.get_text(strip=True) == "Previous"
        )
        previous_path, previous_params = canonical_query_from_href(
            previous_link["href"],
        )

    assert first.status_code == 200
    assert next_path == "/admin/master-data/ingredients"
    assert next_params == {
        "search": ["a"],
        "sort": ["name_asc"],
        "limit": ["1"],
        "page": ["2"],
    }
    assert second.status_code == 200
    assert "Location" not in second.headers
    assert previous_path == "/admin/master-data/ingredients"
    assert previous_params == {
        "search": ["a"],
        "sort": ["name_asc"],
        "limit": ["1"],
    }


def test_store_section_mutation_redirect_is_canonical(master_data_app):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            "/admin/master-data/store-sections",
            data={"display_name": "International Foods", "icon": "basket"},
        )

        assert response.status_code == 302
        path, pairs = location_parts(response)
        assert path == "/admin/master-data/store-sections"
        assert pairs == []
        assert_private_no_store(response)

        rendered = client.get(response.headers["Location"])

    assert rendered.status_code == 200
    assert "International Foods" in rendered.get_data(as_text=True)


def test_ingredient_mutation_cleans_return_redirect(master_data_app):
    seed_workspace_records()
    ingredient = master_data.master_record_for_name("ingredients", "user-a", "tomato")
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            f"/admin/master-data/ingredients/{ingredient['id']}",
            data={
                "name": "Tomato",
                "normalized_name": "tomato",
                "store_section": "PRODUCE",
                "redirect_url": (
                    "/admin/master-data/ingredients?search=tomato"
                    "&scope=mine&user_id=&store_section=&page=1"
                ),
            },
        )

    assert response.status_code == 302
    path, pairs = location_parts(response)
    assert path == "/admin/master-data/ingredients"
    assert query_multimap(pairs) == {
        "search": ["tomato"],
    }
    assert_private_no_store(response)


def test_master_data_json_gets_are_no_store_and_emit_canonical_management_links(
    master_data_app,
):
    seed_workspace_records()
    produce = next(
        section
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
            create=True,
        )
        if section["section_key"] == "PRODUCE"
    )

    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        options = client.get(
            "/api/master-data/ingredients/options?search=tom&limit=10",
        )
        usage = client.get(
            f"/api/master-data/store-sections/{produce['id']}/usage",
        )

    assert options.status_code == 200
    assert_private_no_store(options)
    options_path, options_params = canonical_query_from_href(
        options.get_json()["manage_url"],
    )
    assert options_path == "/admin/master-data/ingredients"
    assert options_params == {}

    assert usage.status_code == 200
    assert_private_no_store(usage)
    ingredient_links = [
        item["manage_url"]
        for item in usage.get_json()["ingredients"]
        if item.get("manage_url")
    ]
    assert ingredient_links
    for href in ingredient_links:
        path, params = canonical_query_from_href(href)
        assert path == "/admin/master-data/ingredients"
        assert "viewer_user_id" not in params
        assert params["store_section"] == ["PRODUCE"]
        assert params["sort"] == ["name_asc"]


def test_javascript_navigation_keeps_master_data_page_urls_userless():
    app_script = Path("PushShoppingList/static/js/app.js").read_text(
        encoding="utf-8",
    )
    master_script = Path("PushShoppingList/static/js/master-data.js").read_text(
        encoding="utf-8",
    )

    assert "function masterDataViewerUrl(rawUrl, values = {})" in app_script
    assert (
        'masterDataViewerUrl("/admin/master-data/store-sections")'
        in app_script
    )
    assert 'masterDataViewerUrl("/admin/master-data/units")' in app_script
    assert 'href="/admin/master-data/store-sections"' not in app_script
    assert 'href="/admin/master-data/units"' not in app_script
    assert 'url.searchParams.set("viewer_user_id", viewerUserId)' in app_script
    assert 'url.pathname.startsWith("/admin/master-data/")' in app_script

    assert (
        "function canonicalMasterDataUrl(rawUrl, values = {})"
        in master_script
    )
    assert "function filterRedirectUrl(filterForm)" in master_script
    assert "function initMasterDataFilterForm()" in master_script
    assert 'url.searchParams.delete("viewer_user_id");' in master_script
    assert "body.dataset.viewerUserId" not in master_script
    assert "targetUser.disabled = !selectingUser;" in master_script
    assert "targetUserField.hidden = !selectingUser;" in master_script
    assert (
        "window.location.assign(filterRedirectUrl(filterForm));"
        in master_script
    )
