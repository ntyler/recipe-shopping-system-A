import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


@pytest.fixture
def ingredient_type_app(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({
            "users": [
                {
                    "user_id": "user-a",
                    "username": "user-a",
                    "email": "user-a@example.com",
                    "account_status": "active",
                },
                {
                    "user_id": "user-b",
                    "username": "user-b",
                    "email": "user-b@example.com",
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
    with client.session_transaction() as active_session:
        active_session["user_id"] = user_id


def registry_for(client):
    response = client.get("/api/master-data/types")
    assert response.status_code == 200
    return response.get_json()["registry"]


def type_named(registry, name):
    return next(item for item in registry["types"] if item["name"] == name)


def create_type(client, name):
    response = client.post(
        "/api/master-data/types",
        json={"name": name, "active": True},
    )
    assert response.status_code == 201
    return response.get_json()


def test_types_page_matches_master_data_navigation_and_exposes_editors(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/types")

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.title.get_text(strip=True) == "Types"
    assert soup.select_one("[data-type-master-page]") is not None
    assert soup.select_one("h1#typesTitle").get_text(strip=True) == "Types"
    assert soup.select_one("[data-type-master-add-button]").get_text(strip=True) == "Add Type"
    type_category_list = soup.select_one(
        ".unit-master-catalog > .unit-master-category-list.type-master-category-list"
    )
    assert type_category_list is not None
    type_categories = type_category_list.find_all(
        "section",
        class_="type-master-category",
        recursive=False,
    )
    assert len(type_categories) == 1
    assert type_categories[0].has_attr("data-type-master-category")
    summary_labels = [
        label.get_text(strip=True)
        for label in soup.select(".unit-master-stats article > span")
    ]
    assert "Active" not in summary_labels
    assert soup.select_one("[data-type-master-active-count]") is None
    assert [
        header.get_text(strip=True)
        for header in soup.select(".type-master-table [role='columnheader']")
    ] == ["Type name", "Used in", "Source", "Action"]
    assert soup.select_one(".type-master-status-badge") is None
    assert soup.select_one("[data-type-master-active]") is None
    assert soup.select_one("[data-type-master-active-error]") is None
    assert soup.select_one(".type-master-availability") is None
    assert soup.select_one("dialog[data-type-master-dialog]") is not None
    assert soup.select_one("dialog[data-type-master-usage-dialog]") is not None
    assert len(soup.select("[data-type-master-row]")) == 6
    seeded_edit_buttons = soup.select("[data-type-master-edit-button]")
    assert len(seeded_edit_buttons) == 6
    assert {
        button["data-type-id"]
        for button in seeded_edit_buttons
    } == {"main", "optional", "garnish", "topping", "sauce", "substitute"}
    assert soup.select(".type-master-action-unavailable") == []
    assert soup.select_one("[data-type-master-delete][hidden]") is not None
    static_root = Path(__file__).resolve().parents[1] / "PushShoppingList" / "static"
    css = (static_root / "css" / "app.css").read_text(encoding="utf-8")
    assert ".unit-master-page button[hidden]," in css
    script = (static_root / "js" / "types.js").read_text(encoding="utf-8")
    assert "nameInput.disabled = Boolean(item?.seeded);" not in script
    assert "current?.seeded ? current.name : cleanText(nameInput.value)" not in script
    assert "name: cleanText(nameInput.value)" in script
    active_tab = soup.select_one("nav.master-data-tabs a.active")
    assert active_tab.get_text(strip=True) == "Types"
    assert active_tab["href"].startswith("/admin/master-data/types")
    assert soup.select_one('script[src*="/static/js/types.js"]') is not None


def test_types_table_reuses_unit_trailing_tracks_and_keeps_responsive_layout():
    css = (
        Path(__file__).resolve().parents[1]
        / "PushShoppingList"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")

    def block_from(source, marker, start=0):
        marker_start = source.index(marker, start)
        opening = source.index("{", marker_start)
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[opening + 1:index]
        raise AssertionError(f"Unclosed CSS block for {marker}")

    def grid_tracks(declarations):
        marker = "grid-template-columns:"
        start = declarations.index(marker) + len(marker)
        value = declarations[start:declarations.index(";", start)].strip()
        tracks = []
        current = []
        depth = 0
        for character in value:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            if character.isspace() and depth == 0:
                if current:
                    tracks.append("".join("".join(current).split()))
                    current = []
                continue
            current.append(character)
        if current:
            tracks.append("".join("".join(current).split()))
        return tracks

    unit_tracks = grid_tracks(block_from(
        css,
        ".unit-master-table-head,",
    ))
    type_section = css.index("/* Type master data:")
    type_desktop = block_from(
        css,
        "@media (min-width: 761px)",
        type_section,
    )
    type_desktop_rules = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", type_desktop):
        selectors = [
            selector.strip()
            for selector in match.group(1).split(",")
            if selector.strip()
        ]
        if any(".type-master-table" in selector for selector in selectors):
            type_desktop_rules.append((selectors, match.group(2)))

    assert len(type_desktop_rules) == 5
    for selectors, _declarations in type_desktop_rules:
        assert len(selectors) == 2
        assert all(
            selector.startswith("[data-type-master-page] ")
            for selector in selectors
        )
        assert all(
            not selector.startswith(".type-master-table")
            for selector in selectors
        )
        assert all(
            not selector.startswith(".type-master-page ")
            for selector in selectors
        )
    assert re.search(
        r"(?m)^\s*\.type-master-page\s+\.type-master-table",
        type_desktop,
    ) is None
    assert re.search(
        r"(?m)^\s*\.type-master-table[^\n,{]*:nth-child\(",
        css,
    ) is None

    type_grid_rules = [
        declarations
        for _selectors, declarations in type_desktop_rules
        if "grid-template-columns:" in declarations
    ]
    assert len(type_grid_rules) == 1
    type_tracks = grid_tracks(type_grid_rules[0])
    cuisine_tracks = grid_tracks(block_from(
        css,
        ".cuisine-category-master-table > .unit-master-table-head,",
    ))

    assert unit_tracks == [
        "minmax(105px,.7fr)",
        "minmax(145px,1.22fr)",
        "minmax(76px,.5fr)",
        "108px",
        "58px",
    ]
    assert type_tracks == unit_tracks
    for child, expected_column in (
        (1, "1 / span 2"),
        (2, "3"),
        (3, "4"),
        (4, "5"),
    ):
        mappings = [
            (selectors, declarations)
            for selectors, declarations in type_desktop_rules
            if all(
                f":nth-child({child})" in selector
                for selector in selectors
            )
        ]
        assert len(mappings) == 1
        assert f"grid-column: {expected_column};" in mappings[0][1]
    assert cuisine_tracks == [
        "52px",
        "96px",
        "minmax(170px,1fr)",
        "minmax(90px,.5fr)",
        "118px",
        "58px",
    ]

    type_full_width = block_from(css, "@media (max-width: 1640px)")
    assert grid_tracks(block_from(
        type_full_width,
        ".type-master-category-list",
    )) == ["minmax(0,1fr)"]

    cuisine_section = css.index("/* Cuisine Category master data:")
    mobile = block_from(css, "@media (max-width: 760px)", cuisine_section)
    assert grid_tracks(block_from(
        mobile,
        ".type-master-table .unit-master-row",
    )) == ["minmax(0,1fr)", "auto"]
    mobile_usage = block_from(
        mobile,
        ".type-master-table .unit-master-usage",
    )
    assert "grid-column: 1;" in mobile_usage
    assert "grid-row: 2;" in mobile_usage
    mobile_action = block_from(
        mobile,
        ".type-master-table .unit-master-action-cell",
    )
    assert "grid-column: 2;" in mobile_action
    assert "grid-row: 1;" in mobile_action


def test_types_used_in_and_action_match_unit_row_markup(
    ingredient_type_app,
):
    recipe_url = "https://example.test/recipes/shared-master-data-row-contract"
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        master_data.sync_recipe_master_records(
            recipe_url,
            recipe_data={
                "recipe_title": "Shared Master Data Row Contract",
                "ingredients": [{
                    "ingredient": "chicken",
                    "quantity": "1",
                    "unit": "pound",
                    "section": "main",
                }],
            },
            user_id="user-a",
        )
        types_response = client.get("/admin/master-data/types")

    assert types_response.status_code == 200
    types_soup = BeautifulSoup(types_response.get_data(as_text=True), "html.parser")
    type_row = next(
        row
        for row in types_soup.select("[data-type-master-row]")
        if row["data-type-id"] == "main"
    )
    templates_root = Path(__file__).resolve().parents[1] / "PushShoppingList" / "templates"
    units_template = (templates_root / "units.html").read_text(encoding="utf-8")

    type_usage = type_row.find(
        "div",
        class_="unit-master-usage",
        recursive=False,
    )
    assert type_usage is not None
    assert type_usage.get("class") == ["unit-master-usage"]
    assert type_usage.get("role") == "cell"
    assert 'class="unit-master-usage" role="cell"' in units_template
    type_usage_button = type_usage.find(
        "button",
        class_="unit-master-usage-button",
        recursive=False,
    )
    assert type_usage_button is not None
    assert type_usage_button.get("class") == ["unit-master-usage-button"]
    assert 'class="unit-master-usage-button"' in units_template
    assert type_usage_button.select_one("strong").get_text(strip=True) == "1"
    assert type_usage_button["title"] == "Show recipes using Main"
    assert 'title="Show recipes using {{ unit.name }}"' in units_template

    unused_type_row = next(
        row
        for row in types_soup.select("[data-type-master-row]")
        if row["data-type-id"] == "optional"
    )
    unused_type = unused_type_row.select_one(".unit-master-usage-empty")
    assert unused_type is not None
    assert unused_type["title"] == "No recipes currently use Optional"
    assert 'class="unit-master-usage-empty"' in units_template
    assert 'title="No recipes currently use {{ unit.name }}"' in units_template

    type_action_cell = type_row.find(
        "span",
        class_="unit-master-action-cell",
        recursive=False,
    )
    assert type_action_cell is not None
    assert type_action_cell.get("role") == "cell"
    type_action = type_action_cell.find(
        "button",
        class_="unit-master-edit-button",
        recursive=False,
    )
    assert type_action is not None
    assert type_action.get("class") == ["unit-master-edit-button"]
    assert 'class="unit-master-edit-button"' in units_template

    static_root = Path(__file__).resolve().parents[1] / "PushShoppingList" / "static"
    script = (
        static_root
        / "js"
        / "types.js"
    ).read_text(encoding="utf-8")
    assert 'action.className = "unit-master-action-cell";' in script
    assert 'action.setAttribute("role", "cell");' in script
    assert "row.append(name, createUsageCell(item), sourceBadge, action);" in script
    assert 'button.title = `Show recipes using ${item.name}`;' in script
    assert 'empty.title = `No recipes currently use ${item.name}`;' in script

    css = (
        Path(__file__).resolve().parents[1]
        / "PushShoppingList"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")
    type_edit_rules = [
        (match.group(1), match.group(2))
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
        if "[data-type-master-page]" in match.group(1)
        and ".unit-master-edit-button" in match.group(1)
    ]
    assert any(
        "width: 100%;" in declarations
        for _selectors, declarations in type_edit_rules
    )


def test_custom_type_persists_reaches_editor_and_is_workspace_isolated(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = create_type(client, "Protein boost")
        custom = type_named(created["registry"], "Protein boost")
        assert custom["custom"] is True
        assert custom["active"] is True

    with ingredient_type_app.test_client() as next_client:
        sign_in(next_client, "user-a")
        assert type_named(registry_for(next_client), "Protein boost")["id"] == custom["id"]
        editor = next_client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "user-a",
                "url": "https://example.test/recipes/type-registry",
            },
        )
        soup = BeautifulSoup(editor.get_data(as_text=True), "html.parser")
        editor_registry = json.loads(soup.select_one("#ingredientTypeConfig").string)
        assert type_named(editor_registry, "Protein boost")["id"] == custom["id"]

    with ingredient_type_app.test_client() as other_client:
        sign_in(other_client, "user-b")
        assert all(
            item["name"] != "Protein boost"
            for item in registry_for(other_client)["types"]
        )
        forbidden = other_client.patch(
            f'/api/master-data/types/{custom["id"]}',
            json={"name": "Taken", "active": True},
        )
        assert forbidden.status_code == 404


def test_seeded_display_name_can_change_without_changing_identity_or_usage(
    ingredient_type_app,
):
    recipe_url = "https://example.test/recipes/stable-main-type"
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        master_data.sync_recipe_master_records(
            recipe_url,
            recipe_data={
                "recipe_title": "Stable Main Type",
                "ingredients": [{
                    "ingredient": "chicken",
                    "quantity": "1",
                    "unit": "pound",
                    "section": "main",
                }],
            },
            user_id="user-a",
        )

        before = type_named(registry_for(client), "Main")
        assert before["id"] == "main"
        assert before["value"] == "main"
        assert before["recipe_count"] == 1

        response = client.patch(
            "/api/master-data/types/main",
            json={"name": "Primary", "active": False},
        )
        assert response.status_code == 200
        renamed = type_named(response.get_json()["registry"], "Primary")
        assert renamed["id"] == "main"
        assert renamed["value"] == "main"
        assert renamed["seeded"] is True
        assert renamed["active"] is True
        assert renamed["recipe_count"] == 1

        persisted = type_named(registry_for(client), "Primary")
        assert persisted["id"] == "main"
        assert persisted["value"] == "main"
        assert persisted["active"] is True
        assert persisted["recipe_count"] == 1

        reserved_create = client.post(
            "/api/master-data/types",
            json={"name": "Main", "active": True},
        )
        assert reserved_create.status_code == 422
        assert reserved_create.get_json()["errors"]["name"]

        custom = create_type(client, "Finisher")
        reserved_rename = client.patch(
            f'/api/master-data/types/{custom["type_id"]}',
            json={"name": "Main", "active": True},
        )
        assert reserved_rename.status_code == 422
        assert reserved_rename.get_json()["errors"]["name"]

        collision_safe_registry = registry_for(client)
        seeded_main = type_named(collision_safe_registry, "Primary")
        assert seeded_main["id"] == "main"
        assert seeded_main["value"] == "main"
        assert seeded_main["recipe_count"] == 1
        assert type_named(collision_safe_registry, "Finisher")["id"] == custom["type_id"]
        assert all(item["name"] != "Main" for item in collision_safe_registry["types"])

        references = client.get("/api/master-data/types/main/references")
        assert references.status_code == 200
        reference_payload = references.get_json()
        assert reference_payload["type"]["name"] == "Primary"
        assert reference_payload["type"]["id"] == "main"
        assert reference_payload["total"] == 1
        assert reference_payload["total_reference_count"] == 1
        assert reference_payload["references"][0]["matches"][0]["ingredient_name"] == (
            "chicken"
        )

        with master_data.existing_recipe_master_read_connection() as connection:
            stored = connection.execute(
                """
                SELECT ingredient_type
                  FROM recipe_ingredients
                 WHERE user_id = ?
                """,
                ("user-a",),
            ).fetchone()
        assert stored["ingredient_type"] == "main"

        editor = client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "user-a",
                "url": recipe_url,
            },
        )
        assert editor.status_code == 200
        soup = BeautifulSoup(editor.get_data(as_text=True), "html.parser")
        editor_registry = json.loads(soup.select_one("#ingredientTypeConfig").string)
        editor_type = type_named(editor_registry, "Primary")
        assert editor_type["id"] == "main"
        assert editor_type["value"] == "main"
        assert editor_type["active"] is True


def test_second_seeded_rename_migrates_previous_display_labels_to_stable_id(
    ingredient_type_app,
):
    recipe_url = "https://example.test/recipes/previous-main-display-label"
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        first_rename = client.patch(
            "/api/master-data/types/main",
            json={"name": "Primary", "active": False},
        )
        assert first_rename.status_code == 200
        assert type_named(first_rename.get_json()["registry"], "Primary")["id"] == "main"

        master_data.sync_recipe_master_records(
            recipe_url,
            recipe_data={
                "recipe_title": "Previous Main Display Label",
                "ingredients": [{
                    "ingredient": "tofu",
                    "quantity": "8",
                    "unit": "ounces",
                    "section": "Primary",
                }],
            },
            user_id="user-a",
        )
        with master_data.recipe_master_connection(user_id="user-a") as connection:
            connection.execute(
                """
                UPDATE recipe_ingredient_option_items
                   SET metadata_json = ?
                 WHERE option_id IN (
                       SELECT option.id
                         FROM recipe_ingredient_options option
                         JOIN recipe_ingredient_requirements requirement
                           ON requirement.id = option.requirement_id
                        WHERE requirement.user_id = ?
                 )
                """,
                (json.dumps({"section": "Primary"}), "user-a"),
            )

        with master_data.existing_recipe_master_read_connection() as connection:
            direct_before = connection.execute(
                """
                SELECT ingredient_type
                  FROM recipe_ingredients
                 WHERE user_id = ?
                """,
                ("user-a",),
            ).fetchone()
            option_before = connection.execute(
                """
                SELECT item.ingredient_type, item.metadata_json
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement
                    ON requirement.id = option.requirement_id
                 WHERE requirement.user_id = ?
                """,
                ("user-a",),
            ).fetchone()
        assert direct_before["ingredient_type"] == "Primary"
        assert option_before["ingredient_type"] == "Primary"
        assert json.loads(option_before["metadata_json"])["section"] == "Primary"

        second_rename = client.patch(
            "/api/master-data/types/main",
            json={"name": "Core", "active": False},
        )
        assert second_rename.status_code == 200
        renamed = type_named(second_rename.get_json()["registry"], "Core")
        assert renamed["id"] == "main"
        assert renamed["value"] == "main"
        assert renamed["active"] is True
        assert renamed["recipe_count"] == 1

        with master_data.existing_recipe_master_read_connection() as connection:
            direct_after = connection.execute(
                """
                SELECT ingredient_type
                  FROM recipe_ingredients
                 WHERE user_id = ?
                """,
                ("user-a",),
            ).fetchone()
            option_after = connection.execute(
                """
                SELECT item.ingredient_type, item.metadata_json
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement
                    ON requirement.id = option.requirement_id
                 WHERE requirement.user_id = ?
                """,
                ("user-a",),
            ).fetchone()
        assert direct_after["ingredient_type"] == "main"
        assert option_after["ingredient_type"] == "main"
        assert json.loads(option_after["metadata_json"])["section"] == "main"

        persisted = type_named(registry_for(client), "Core")
        assert persisted["id"] == "main"
        assert persisted["value"] == "main"
        assert persisted["recipe_count"] == 1
        references = client.get("/api/master-data/types/main/references")
        assert references.status_code == 200
        reference_payload = references.get_json()
        assert reference_payload["type"]["name"] == "Core"
        assert reference_payload["type"]["id"] == "main"
        assert reference_payload["total"] == 1
        assert reference_payload["total_reference_count"] == 1


def test_rename_migrates_usage_and_safe_delete_requires_reassignment(
    ingredient_type_app,
):
    recipe_url = "https://example.test/recipes/protein-shake"
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = create_type(client, "Protein boost")
        type_id = created["type_id"]
        master_data.sync_recipe_master_records(
            recipe_url,
            recipe_data={
                "recipe_title": "Protein Shake",
                "ingredients": [{
                    "ingredient": "protein powder",
                    "quantity": "1",
                    "unit": "scoop",
                    "section": "Protein boost",
                }],
            },
            user_id="user-a",
        )

        registry = registry_for(client)
        assert type_named(registry, "Protein boost")["recipe_count"] == 1
        references = client.get(f"/api/master-data/types/{type_id}/references")
        assert references.status_code == 200
        reference_payload = references.get_json()
        assert reference_payload["total"] == 1
        assert reference_payload["total_reference_count"] == 1
        assert reference_payload["references"][0]["matches"][0]["ingredient_name"] == (
            "protein powder"
        )

        renamed = client.patch(
            f"/api/master-data/types/{type_id}",
            json={"name": "Protein", "active": True},
        )
        assert renamed.status_code == 200
        assert type_named(renamed.get_json()["registry"], "Protein")["recipe_count"] == 1
        with master_data.recipe_master_connection() as connection:
            stored = connection.execute(
                "SELECT ingredient_type FROM recipe_ingredients WHERE user_id = ?",
                ("user-a",),
            ).fetchone()
            normalized_option = connection.execute(
                """
                SELECT item.ingredient_type
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement
                    ON requirement.id = option.requirement_id
                 WHERE requirement.user_id = ?
                """,
                ("user-a",),
            ).fetchone()
        assert stored["ingredient_type"] == "Protein"
        assert normalized_option["ingredient_type"] == "Protein"

        blocked = client.delete(f"/api/master-data/types/{type_id}")
        assert blocked.status_code == 409
        blocked_error = blocked.get_json()["error"]
        assert "Reassign or remove" in blocked_error
        assert "deactivat" not in blocked_error.lower()

        remains_active = client.patch(
            f"/api/master-data/types/{type_id}",
            json={"name": "Protein", "active": False},
        )
        assert remains_active.status_code == 200
        assert type_named(
            remains_active.get_json()["registry"],
            "Protein",
        )["active"] is True


def test_type_api_forces_active_and_normalizes_legacy_inactive_rows(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/types",
            json={"name": "Always available", "active": False},
        )
        assert created.status_code == 201
        created_type = type_named(created.get_json()["registry"], "Always available")
        assert created_type["active"] is True

        custom_id = created_type["id"]
        patched = client.patch(
            f"/api/master-data/types/{custom_id}",
            json={"name": "Still available", "active": False},
        )
        assert patched.status_code == 200
        assert type_named(
            patched.get_json()["registry"],
            "Still available",
        )["active"] is True

        built_in = client.patch(
            "/api/master-data/types/main",
            json={"name": "Main", "active": False},
        )
        assert built_in.status_code == 200
        assert type_named(built_in.get_json()["registry"], "Main")["active"] is True

        with master_data.recipe_master_connection(user_id="user-a") as connection:
            connection.execute(
                """
                UPDATE workspace_ingredient_types
                   SET is_active = 0
                 WHERE user_id = ? AND id = ?
                """,
                ("user-a", custom_id),
            )

        with master_data.existing_recipe_master_read_connection() as connection:
            legacy_stored = connection.execute(
                """
                SELECT is_active
                  FROM workspace_ingredient_types
                 WHERE user_id = ? AND id = ?
                """,
                ("user-a", custom_id),
            ).fetchone()
        assert legacy_stored["is_active"] == 0

        normalized_registry = registry_for(client)
        assert type_named(normalized_registry, "Still available")["active"] is True
        with master_data.existing_recipe_master_read_connection() as connection:
            stored = connection.execute(
                """
                SELECT is_active
                  FROM workspace_ingredient_types
                 WHERE user_id = ? AND id = ?
                """,
                ("user-a", custom_id),
            ).fetchone()
        assert stored["is_active"] == 1


def test_unused_custom_type_can_be_deleted_and_built_ins_are_protected(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = create_type(client, "Finisher")
        deleted = client.delete(f'/api/master-data/types/{created["type_id"]}')
        assert deleted.status_code == 200
        assert deleted.get_json()["deleted"] is True
        assert all(
            item["name"] != "Finisher"
            for item in deleted.get_json()["registry"]["types"]
        )

        main_remains_active = client.patch(
            "/api/master-data/types/main",
            json={"name": "Main", "active": False},
        )
        assert main_remains_active.status_code == 200
        assert type_named(
            main_remains_active.get_json()["registry"],
            "Main",
        )["active"] is True
        built_in_delete = client.delete("/api/master-data/types/garnish")
        assert built_in_delete.status_code == 422
        assert "not deleted" in built_in_delete.get_json()["error"].lower()
        assert "deactivat" not in built_in_delete.get_json()["error"].lower()


def test_legacy_import_is_persistent_and_duplicate_safe(ingredient_type_app):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        imported = client.post(
            "/api/master-data/types/import-local",
            json={"types": ["Protein", "protein", "Finisher", ""]},
        )
        assert imported.status_code == 200
        payload = imported.get_json()
        assert payload["imported"] == ["Protein", "Finisher"]
        assert payload["skipped"] == ["protein"]
        assert {item["name"] for item in payload["registry"]["types"]} >= {
            "Protein",
            "Finisher",
        }


def test_type_mutations_require_authentication_and_validate_names(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        denied = client.post(
            "/api/master-data/types",
            json={"name": "Private", "active": True},
        )
        assert denied.status_code == 401

        sign_in(client, "user-a")
        empty = client.post(
            "/api/master-data/types",
            json={"name": " ", "active": True},
        )
        assert empty.status_code == 422
        too_long = client.post(
            "/api/master-data/types",
            json={"name": "x" * 41, "active": True},
        )
        assert too_long.status_code == 422
