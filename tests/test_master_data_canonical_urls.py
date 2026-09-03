import json
import re
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
    "/admin/master-data/cuisine-categories",
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
    assert {
        row.select_one(".unit-master-source-badge").get_text(strip=True)
        for row in built_in_rows
    } == {"Built-in"}
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
    assert 'unit.seeded ? "Built-in" : "User-created"' in units_script
    assert "data-unit-master-search" in response.get_data(as_text=True)


def test_cuisine_categories_page_renders_registry_management_ui(master_data_app):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/cuisine-categories")

    assert response.status_code == 200
    assert_private_no_store(response)
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.title.get_text(strip=True) == "Cuisine Categories"
    root = soup.select_one("[data-cuisine-category-master-page]")
    assert root is not None
    assert root["data-create-url"] == "/api/master-data/cuisine-categories"
    assert "__CATEGORY_ID__" in root["data-update-url-template"]
    assert root["data-import-url"] == "/api/master-data/cuisine-categories/import-local"
    assert soup.select_one("h1#cuisineCategoriesTitle").get_text(strip=True) == (
        "Cuisine Categories"
    )
    create_panel = root.find(
        "section",
        class_="cuisine-category-master-create",
        recursive=False,
    )
    assert create_panel is not None
    assert create_panel.get("aria-labelledby") == "addCuisineCategoryTitle"
    assert create_panel.select_one("h2#addCuisineCategoryTitle").get_text(
        " ", strip=True,
    ) == "Add a Cuisine Category"
    create_form = create_panel.find(
        "form",
        class_="cuisine-category-master-create-form",
        recursive=False,
    )
    assert create_form is not None
    assert create_form.has_attr("data-cuisine-category-master-create-form")
    create_name = create_form.select_one(
        "input[data-cuisine-category-master-create-name]"
    )
    create_abbreviation = create_form.select_one(
        "input[data-cuisine-category-master-create-abbreviation]"
    )
    create_icon = create_form.select_one(
        "[data-cuisine-category-master-create-icon]"
    )
    create_icon_trigger = create_form.select_one(
        "button[data-cuisine-category-master-create-icon-trigger]"
    )
    create_submit = create_form.select_one(
        "button[data-cuisine-category-master-create-submit]"
    )
    create_error = create_form.select_one(
        "[data-cuisine-category-master-create-error]"
    )
    assert create_name is not None and create_name.has_attr("required")
    assert create_abbreviation is not None
    assert create_icon is not None and create_icon.get("type") == "hidden"
    assert create_submit is not None and create_submit.get("type") == "submit"
    assert create_submit.get_text(" ", strip=True) == "Add Cuisine Category"
    assert create_error is not None
    assert create_error.get("role") == "alert"
    assert create_error.has_attr("hidden")
    assert create_icon_trigger is not None
    assert create_icon_trigger.get("role") == "combobox"
    assert create_icon_trigger.get("aria-haspopup") == "listbox"
    assert create_icon_trigger.get("aria-expanded") == "false"
    assert create_icon_trigger.get("aria-controls") == "cuisineCategoryIconListbox"
    for described_control in (
        create_name,
        create_abbreviation,
        create_icon_trigger,
    ):
        assert create_error["id"] in described_control["aria-describedby"].split()

    assert not root.select("[data-cuisine-category-master-add-button]")
    assert not root.select("[data-cuisine-category-master-edit-button]")
    assert soup.select_one("[data-cuisine-category-master-dialog]") is None
    assert soup.select_one("dialog.unit-master-dialog") is None
    assert soup.select_one("[data-cuisine-category-master-usage-dialog]") is not None
    assert [
        article.find("span").get_text(" ", strip=True)
        for article in soup.select(".unit-master-stats > article")
    ] == ["System-seeded", "User-created", "In use"]
    assert soup.select_one(
        "[data-cuisine-category-master-active-count]"
    ) is None
    registry_panel = root.find(
        "section",
        class_="cuisine-category-master-list-section",
        recursive=False,
    )
    assert registry_panel is not None
    registry_toolbar = registry_panel.find(
        "header",
        class_="cuisine-category-master-table-toolbar",
        recursive=False,
    )
    assert registry_toolbar is not None
    registry_actions = registry_toolbar.find(
        "div",
        class_="cuisine-category-master-table-actions",
        recursive=False,
    )
    assert registry_actions is not None
    assert registry_actions.select_one(
        "[data-cuisine-category-master-search]"
    ) is not None
    visible_count = registry_actions.select_one(
        "[data-cuisine-category-master-count-label]"
    )
    assert visible_count is not None
    assert not registry_toolbar.select("[data-cuisine-category-master-add-button]")

    cuisine_category_list = registry_panel.find(
        "div",
        class_="cuisine-category-master-category-list",
        recursive=False,
    )
    assert cuisine_category_list is not None
    assert "unit-master-category-list" in cuisine_category_list.get("class", [])
    cuisine_category_children = cuisine_category_list.find_all(recursive=False)
    assert len(cuisine_category_children) == 1
    cuisine_category = cuisine_category_children[0]
    assert cuisine_category.name == "section"
    assert "unit-master-category" in cuisine_category.get("class", [])
    assert cuisine_category.has_attr(
        "data-cuisine-category-master-category"
    )
    column_headers = [
        cell.get_text(" ", strip=True)
        for cell in soup.select(
            ".cuisine-category-master-table [role='columnheader']"
        )
    ]
    assert column_headers == [
        "Icon",
        "Abbreviation",
        "Cuisine Category Name",
        "Used in",
        "Source",
        "Action",
    ]
    rows = soup.select("[data-cuisine-category-master-row]")
    assert rows
    assert visible_count.get_text(" ", strip=True) == (
        f"{len(rows)} of {len(rows)} shown"
    )
    for preserved_hook in (
        "data-cuisine-category-master-rows",
        "data-cuisine-category-master-search-empty",
        "data-cuisine-category-master-status",
    ):
        assert root.select_one(f"[{preserved_hook}]") is not None
    for row in rows:
        assert row.get("role") == "row"
        assert row.get("data-category-id")
        row_error = row.select_one("[data-cuisine-category-master-row-error]")
        row_icon = row.select_one(
            "button[data-cuisine-category-master-row-icon-trigger]"
        )
        row_abbreviation = row.select_one(
            "input[data-cuisine-category-master-row-abbreviation]"
        )
        row_name = row.select_one("input[data-cuisine-category-master-row-name]")
        row_save = row.select_one("button[data-cuisine-category-master-row-save]")
        assert row_error is not None and row_error.get("role") == "alert"
        assert row_error.has_attr("hidden")
        assert row_icon is not None
        assert row_icon.get("role") == "combobox"
        assert row_icon.get("aria-haspopup") == "listbox"
        assert row_icon.get("aria-expanded") == "false"
        assert row_icon.get("aria-controls") == "cuisineCategoryIconListbox"
        assert row_abbreviation is not None
        assert row_name is not None and row_name.has_attr("required")
        assert row_save is not None
        assert row_save.get_text(" ", strip=True) == "Save"
        assert row_save.has_attr("disabled")
        for described_control in (row_icon, row_abbreviation, row_name):
            assert row_error["id"] in described_control[
                "aria-describedby"
            ].split()

        source_badge = row.select_one(".unit-master-source-badge")
        assert source_badge is not None and source_badge.get("role") == "cell"
        if source_badge.get_text(strip=True) == "Built-in":
            assert row_name.has_attr("readonly")
            assert row_name.get("aria-readonly") == "true"
            assert row.select_one(
                "[data-cuisine-category-master-row-delete]"
            ) is None
    header_identity = soup.select_one(
        ".cuisine-category-master-table > .unit-master-table-head > "
        ".cuisine-category-master-identity"
    )
    assert header_identity is not None
    assert header_identity.get("role") == "presentation"
    assert [
        child.get("role")
        for child in header_identity.find_all(recursive=False)
    ] == ["columnheader", "columnheader", "columnheader"]
    assert {
        row.select_one(".unit-master-source-badge").get_text(strip=True)
        for row in rows
        if "user-created" not in row.select_one(
            ".unit-master-source-badge"
        ).get("class", [])
    } == {"Built-in"}
    assert not soup.select(".cuisine-category-master-table .type-master-status-badge")
    assert soup.select_one("[data-cuisine-category-master-active]") is None
    assert soup.select_one("[data-cuisine-category-master-active-error]") is None
    picker = soup.select("[data-cuisine-category-master-icon-picker]")
    assert len(picker) == 1
    assert picker[0].select_one("[data-cuisine-category-master-icon]") is not None
    assert picker[0].select_one(
        "[data-cuisine-category-master-icon-search]"
    ) is not None
    assert picker[0].select_one(
        "[data-cuisine-category-master-icon-listbox][role='listbox']"
    ) is not None
    assert not root.select("[draggable]")
    assert not any(
        attribute.startswith("data-store-section")
        for element in root.find_all(True)
        for attribute in element.attrs
    )
    active_tab = soup.select_one("nav.master-data-tabs a.active")
    assert active_tab.get_text(strip=True) == "Cuisine Categories"
    assert urlsplit(active_tab["href"]).path == (
        "/admin/master-data/cuisine-categories"
    )
    assert soup.select_one(
        'script[src*="/static/js/cuisine_categories.js"]'
    ) is not None

    script = Path(
        "PushShoppingList/static/js/cuisine_categories.js"
    ).read_text(encoding="utf-8")
    assert "const saveNewCategory = async event =>" in script
    assert "const saveCategoryRow = async row =>" in script
    assert "const deleteCategoryRow = async row =>" in script
    assert "const openUsage = async (item, trigger) =>" in script
    assert 'body: JSON.stringify({ categories: importableNames })' in script
    assert '"__CATEGORY_ID__"' in script
    assert "const rowDrafts = new Map();" in script
    assert "const draftIsDirty = draft => !valuesMatch(" in script
    assert 'row.classList.toggle("is-dirty", dirty);' in script
    assert 'row.dataset.dirty = String(dirty);' in script
    assert "const reconcileRowDrafts = (nextCategories, resetCategoryIds = []) =>" in script
    assert "existing.baseline = categorySnapshot(item);" in script
    reconcile_drafts = script.split(
        "const reconcileRowDrafts = (nextCategories, resetCategoryIds = []) => {",
        1,
    )[1].split("\n        };", 1)[0]
    assert "if (!existing || resetIds.has(categoryId))" in reconcile_drafts
    assert "existing.icon =" not in reconcile_drafts
    assert "existing.abbreviation =" not in reconcile_drafts
    assert "existing.name =" not in reconcile_drafts
    assert "const draft = ensureRowDraft(item);" in script
    assert (
        "updateRegistry(data.registry, { resetCategoryIds: [item.id] });"
        in script
    )
    apply_search = script.split("const applySearch = () => {", 1)[1].split(
        "\n        };", 1,
    )[0]
    assert "row.hidden = !matches;" in apply_search
    assert "replaceChildren" not in apply_search
    assert "renderRegistry" not in apply_search
    assert 'method: "PATCH"' in script
    assert 'if (!item?.custom) return;' in script
    assert "if (Number(item.recipe_count) > 0)" in script
    assert "window.confirm(`Delete custom cuisine category" in script
    assert 'method: "DELETE"' in script
    assert "trigger.focus({ preventScroll: true });" in script
    assert "window.requestAnimationFrame(() => createNameInput.focus" in script
    assert "const saveCategory = async event =>" not in script
    assert "const deleteCategory = async () =>" not in script
    assert "openEditor(" not in script
    assert "[data-cuisine-category-master-add-button]" not in script
    assert "[data-cuisine-category-master-edit-button]" not in script
    assert "[data-cuisine-category-master-dialog]" not in script
    assert "activeInput" not in script
    assert "[data-cuisine-category-master-active]" not in script
    assert "type-master-status-badge" not in script
    assert "data-store-section" not in script
    assert 'item.custom ? "User-created" : "Built-in"' in script
    assert (
        "countLabel.textContent = "
        "`${visible} of ${registry.categories.length} shown`;"
    ) in script

    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    cuisine_heading_rules = [
        (match.group(1), match.group(2))
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
        if ".cuisine-category-master-page" in match.group(1)
        and any(
            heading in match.group(1)
            for heading in (
                ".master-data-header h1",
                ".cuisine-category-master-create h2",
                ".cuisine-category-master-list-section h2",
            )
        )
    ]
    assert cuisine_heading_rules
    for heading in (
        ".master-data-header h1",
        ".cuisine-category-master-create h2",
        ".cuisine-category-master-list-section h2",
    ):
        assert any(
            heading in selectors and "text-align: left;" in declarations
            for selectors, declarations in cuisine_heading_rules
        )


def test_cuisine_category_rows_share_unit_usage_and_action_contract(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/cuisine-categories",
            json={
                "icon": "symbol:bowl",
                "abbreviation": "ITC",
                "name": "Inline Test Cuisine",
            },
        )
        assert created.status_code == 201
        category_id = created.get_json()["category_id"]
        response = client.get("/admin/master-data/cuisine-categories")

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    row = soup.select_one(
        f'[data-cuisine-category-master-row][data-category-id="{category_id}"]'
    )
    assert row is not None
    identity = row.find(
        "div",
        class_="cuisine-category-master-identity",
        recursive=False,
    )
    assert identity is not None
    assert identity.get("role") == "presentation"
    assert [
        child.get("role")
        for child in identity.find_all(recursive=False)
    ] == ["cell", "cell", "cell"]
    assert len(row.select("[role='cell']")) == 6
    category_name = row.select_one(
        "input[data-cuisine-category-master-row-name]"
    )["value"]

    templates_root = Path("PushShoppingList/templates")
    units_template = (templates_root / "units.html").read_text(encoding="utf-8")
    cuisine_template = (templates_root / "cuisine_categories.html").read_text(
        encoding="utf-8",
    )
    usage = row.find(
        "div",
        class_="unit-master-usage",
        recursive=False,
    )
    assert usage is not None
    assert usage.get("class") == ["unit-master-usage"]
    assert usage.get("role") == "cell"
    assert 'class="unit-master-usage" role="cell"' in units_template
    assert 'class="unit-master-usage-button"' in cuisine_template
    assert 'class="unit-master-usage-button"' in units_template
    assert 'title="Show recipes using {{ unit.name }}"' in units_template
    assert (
        "title=\"Show recipes using {{ category.category_name or "
        "category.canonical_name or category.name }}\""
    ) in cuisine_template

    empty_usage = usage.find(
        "span",
        class_="unit-master-usage-empty",
        recursive=False,
    )
    assert empty_usage is not None
    assert empty_usage["title"] == f"No recipes currently use {category_name}"
    assert 'class="unit-master-usage-empty"' in units_template
    assert 'title="No recipes currently use {{ unit.name }}"' in units_template

    action_cell = row.find(
        "span",
        class_="unit-master-action-cell",
        recursive=False,
    )
    assert action_cell is not None
    assert action_cell.get("role") == "cell"
    save = action_cell.find(
        "button",
        attrs={"data-cuisine-category-master-row-save": True},
        recursive=False,
    )
    assert save is not None
    assert save.get_text(" ", strip=True) == "Save"
    assert save.has_attr("disabled")
    assert action_cell.select_one(
        "[data-cuisine-category-master-edit-button]"
    ) is None
    delete = action_cell.select_one(
        "button[data-cuisine-category-master-row-delete]"
    )
    assert delete is not None
    assert delete.get_text(" ", strip=True) == "Delete"
    assert delete.get("data-category-id") == category_id
    assert row.select_one(".unit-master-source-badge").get_text(strip=True) == (
        "User-created"
    )

    script = Path(
        "PushShoppingList/static/js/cuisine_categories.js"
    ).read_text(encoding="utf-8")
    assert 'usage.className = "unit-master-usage";' in script
    assert 'usage.setAttribute("role", "cell");' in script
    assert 'button.className = "unit-master-usage-button";' in script
    assert 'empty.className = "unit-master-usage-empty";' in script
    assert (
        "button.title = `Show recipes using ${categoryDisplayLabel(item)}`;"
        in script
    )
    assert (
        "empty.title = `No recipes currently use ${categoryDisplayLabel(item)}`;"
        in script
    )
    assert (
        'actionCell.className = "unit-master-action-cell '
        'cuisine-category-master-row-actions";'
    ) in script
    assert 'actionCell.setAttribute("role", "cell");' in script
    assert "const setCreateSaving = saving => {" in script
    assert "createNameInput.disabled = saving;" in script
    assert "createIconTrigger.disabled = saving;" in script
    assert 'save.dataset.cuisineCategoryMasterRowSave = "";' in script
    assert 'save.textContent = draft.saving ? "Saving…" : "Save";' in script
    assert "const pending = Boolean(draft.saving || draft.deleting);" in script
    assert "has unsaved changes." in script
    assert "were reverted." in script
    assert 'setStatus("Adding cuisine category…", "info");' in script
    assert "draft.deleting = true;" in script
    assert "if (item.custom) {" in script
    assert 'deleteButton.dataset.cuisineCategoryMasterRowDelete = "";' in script
    assert 'rowError.setAttribute("role", "alert");' in script
    assert 'identity.className = "cuisine-category-master-identity";' in script
    assert 'identity.setAttribute("role", "presentation");' in script
    assert "identity.append(iconField, abbreviationField, nameField);" in script
    assert "identity," in script
    assert "cuisineCategoryMasterEditButton" not in script

    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
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

    unit_grid = block_from(css, ".unit-master-table-head,")
    unit_columns = re.search(
        r"grid-template-columns:\s*([^;]+);",
        unit_grid,
    ).group(1).split()
    assert unit_columns[-1] == "58px"
    assert "gap: 12px;" in unit_grid

    inline_section = css.index(
        "/* Cuisine Category manager v3: direct create and per-row editing. */"
    )
    inline_css = css[inline_section:]
    assert "[data-cuisine-category-master-create-form] {" in inline_css
    assert "[data-cuisine-category-master-row].is-dirty" in inline_css
    assert "[data-cuisine-category-master-row].is-saving" in inline_css
    assert "[data-cuisine-category-master-row].has-error" in inline_css
    assert "[data-cuisine-category-master-row-save]:disabled" in inline_css
    assert "[data-cuisine-category-master-row-delete]" in inline_css
    assert "[data-mobile-label]::before" in inline_css

    cuisine_desktop = block_from(
        css,
        "@media (min-width: 761px)",
        inline_section,
    )
    desktop_rows = block_from(
        cuisine_desktop,
        ".cuisine-category-master-table > .unit-master-table-head,",
    )
    assert "grid-template-columns:" in desktop_rows
    assert "minmax(102px, .7fr)" in desktop_rows
    assert "minmax(142px, 1.22fr)" in desktop_rows
    desktop_identity = block_from(
        cuisine_desktop,
        ".cuisine-category-master-table .cuisine-category-master-identity",
    )
    assert "grid-template-columns: 44px 96px minmax(0, 1fr);" in (
        desktop_identity
    )

    mobile = block_from(css, "@media (max-width: 760px)", inline_section)
    mobile_row = block_from(
        mobile,
        ".cuisine-category-master-table [data-cuisine-category-master-row]",
    )
    assert "grid-template-columns: minmax(0, 1fr);" in mobile_row
    mobile_identity = block_from(
        mobile,
        ".cuisine-category-master-table\n"
        "        [data-cuisine-category-master-row]\n"
        "        .cuisine-category-master-identity",
    )
    assert "grid-template-columns: 44px 96px minmax(0, 1fr);" in (
        mobile_identity
    )


def test_cuisine_category_routes_support_workspace_crud_and_references(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/cuisine-categories",
            json={
                "icon": "🌊",
                "abbreviation": "GLF",
                "name": "Great Lakes Fusion",
                "active": False,
            },
        )
        assert created.status_code == 201
        created_payload = created.get_json()
        category_id = created_payload["category_id"]
        assert any(
            item["id"] == category_id
            and item["icon"] == "🌊"
            and item["abbreviation"] == "GLF"
            and item["category_name"] == "Great Lakes Fusion"
            and item["name"] == "🌊 Great Lakes Fusion"
            and item["active"] is True
            for item in created_payload["registry"]["categories"]
        )

        updated = client.patch(
            f"/api/master-data/cuisine-categories/{category_id}",
            json={
                "icon": "🌽",
                "abbreviation": "MWF",
                "name": "Midwest Fusion",
                "active": False,
            },
        )
        with master_data.recipe_master_connection(user_id="user-a") as connection:
            stored_active = connection.execute(
                """
                SELECT is_active
                  FROM workspace_cuisine_categories
                 WHERE user_id = ? AND id = ?
                """,
                ("user-a", category_id),
            ).fetchone()["is_active"]
        references = client.get(
            f"/api/master-data/cuisine-categories/{category_id}/references",
        )
        deleted = client.delete(
            f"/api/master-data/cuisine-categories/{category_id}",
        )

    assert updated.status_code == 200
    assert any(
        item["id"] == category_id
        and item["icon"] == "🌽"
        and item["abbreviation"] == "MWF"
        and item["category_name"] == "Midwest Fusion"
        and item["name"] == "🌽 Midwest Fusion"
        and item["active"] is True
        for item in updated.get_json()["registry"]["categories"]
    )
    assert stored_active == 1
    assert references.status_code == 200
    assert references.get_json()["category"]["id"] == category_id
    assert references.get_json()["references"] == []
    assert deleted.status_code == 200
    assert all(
        item["id"] != category_id
        for item in deleted.get_json()["registry"]["categories"]
    )
    for response in (created, updated, references, deleted):
        assert_private_no_store(response)


def test_cuisine_category_registry_get_normalizes_legacy_inactive_rows(
    master_data_app,
):
    with master_data_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/cuisine-categories",
            json={"name": "Legacy inactive cuisine"},
        )
        assert created.status_code == 201
        category_id = created.get_json()["category_id"]
        with master_data.recipe_master_connection(user_id="user-a") as connection:
            connection.execute(
                """
                UPDATE workspace_cuisine_categories
                   SET is_active = 0
                 WHERE user_id = ? AND id = ?
                """,
                ("user-a", category_id),
            )

        response = client.get("/api/master-data/cuisine-categories")

    assert response.status_code == 200
    item = next(
        category
        for category in response.get_json()["registry"]["categories"]
        if category["id"] == category_id
    )
    assert item["active"] is True
    with master_data.existing_recipe_master_read_connection() as connection:
        stored_active = connection.execute(
            """
            SELECT is_active
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", category_id),
        ).fetchone()["is_active"]
    assert stored_active == 1
    assert_private_no_store(response)


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
            "/admin/master-data/cuisine-categories",
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
