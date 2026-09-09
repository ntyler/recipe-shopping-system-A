"""Equipment Type totals follow scoped filters, not the visible page size."""

from collections import Counter

from bs4 import BeautifulSoup
from flask import template_rendered
import pytest

from PushShoppingList.services import equipment_registry_service as registry
from PushShoppingList.services import recipe_master_data_service as md
from test_equipment_service_scope import identity
from test_recipe_master_data_routes import configure_master_data_app, sign_in


PAGE = "/admin/master-data/equipment"


@pytest.fixture
def grouped_equipment(monkeypatch, tmp_path):
    app, database, _ = configure_master_data_app(monkeypatch, tmp_path)
    ids = {}
    with md.recipe_master_connection() as connection:
        for owner, name, section in (
            ("user-a", "Copper pan", "COOKWARE"),
            ("user-a", "Steel pan", "COOKWARE"),
            ("user-a", "Stockpot", "COOKWARE"),
            ("user-a", "Baking tray", "BAKEWARE"),
            ("user-a", "Thermometer", "MEASURING"),
            ("user-b", "Secret pan", "COOKWARE"),
            ("user-b", "Private pan", "COOKWARE"),
            ("admin-user", "Admin pan", "COOKWARE"),
        ):
            ids[name] = md.upsert_master_record(
                connection, "equipment", owner, name, equipment_section=section,
            )["id"]
    return app, database, ids


def rendered_context(app, client, query=""):
    contexts = []

    def capture(sender, template, context, **extra):
        if "master_data" in context:
            contexts.append(context["master_data"])

    with template_rendered.connected_to(capture, app):
        response = client.get(PAGE + query)
    assert response.status_code == 200
    context = contexts[-1]
    page = BeautifulSoup(response.data, "html.parser")
    groups = page.select("[data-equipment-group]")
    assert len(groups) == len(context["row_groups"])
    assert len(page.select(".master-data-equipment-table")) == len(groups)
    for rendered_group, group in zip(groups, context["row_groups"]):
        heading = rendered_group.select_one(":scope > header.equipment-group-header")
        assert heading is not None
        assert heading.select_one("[data-equipment-type-label]")["data-equipment-type-label"] == group["section"]
        assert heading.select_one("[data-equipment-group-count]").get_text(strip=True) == (
            f'{group["count"]} {"item" if group["count"] == 1 else "items"}'
        )
        table = rendered_group.select_one("table.master-data-equipment-table")
        assert table is not None and len(rendered_group.select("table")) == 1
        assert not table.select(".master-data-section-row")
        assert [column.get_text(strip=True) for column in table.select("thead th[scope='col']")] == [
            "Order", "Item", "Aliases", "Equipment Type", "Used In", "Action",
        ]
        assert len(table.select("colgroup > col")) == 6
        assert [int(row["data-master-record-id"]) for row in table.select("tbody > [data-equipment-master-row]")] == [
            row["id"] for row in group["rows"]
        ]
    if not context["rows"] and context["db_status"]["exists"]:
        assert page.select_one(".master-data-empty-state")
        assert not page.select("[data-equipment-group-count]")
    return context


def group_counts(context):
    return {group["section"]: group["count"] for group in context["row_groups"]}


@pytest.mark.parametrize("query,expected,total", [
    ("", {"COOKWARE": 3, "BAKEWARE": 1, "MEASURING": 1}, 5),
    ("?search=pan", {"COOKWARE": 2}, 2),
    ("?equipment_section=COOKWARE", {"COOKWARE": 3}, 3),
    ("?search=pan&equipment_section=COOKWARE", {"COOKWARE": 2}, 2),
    ("?search=pan&equipment_section=BAKEWARE", {}, 0),
    ("?sort=name_asc&limit=1&page=2", {"COOKWARE": 3}, 5),
    ("?search=pan&equipment_section=COOKWARE&limit=1&page=2", {"COOKWARE": 2}, 2),
    ("?equipment_section=COOKWARE&limit=1&page=999", {"COOKWARE": 3}, 3),
])
def test_group_counts_follow_complete_filtered_results(grouped_equipment, query, expected, total):
    app, database, _ = grouped_equipment
    client = app.test_client()
    sign_in(client, "user-a")
    before = database.read_bytes()
    context = rendered_context(app, client, query)
    assert group_counts(context) == expected
    assert context["total_count"] == total
    assert context["group_by_equipment_section"]
    if "limit=1" in query:
        assert len(context["rows"]) == 1
    assert database.read_bytes() == before


@pytest.mark.parametrize("owner,expected", [
    ("user-a", {"COOKWARE": 3, "BAKEWARE": 1, "MEASURING": 1}),
    ("user-b", {"COOKWARE": 2}),
    ("admin-user", {"COOKWARE": 1}),
])
def test_group_counts_reject_scope_overrides_and_switch_with_account(grouped_equipment, owner, expected):
    app, _, _ = grouped_equipment
    client = app.test_client()
    sign_in(client, "user-b")
    assert group_counts(rendered_context(app, client)) == {"COOKWARE": 2}
    sign_in(client, owner)
    for query in ("", "?scope=all", "?scope=user&user_id=user-b", "?workspace_id=user-b&account_id=user-b"):
        assert group_counts(rendered_context(app, client, query)) == expected
    with identity(app, owner):
        assert md.equipment_type_counts(user_id="user-b", include_all_users=True) == expected


def test_search_and_aliases_use_the_same_predicates_as_equipment_rows(grouped_equipment):
    app, database, ids = grouped_equipment
    assert registry.update_equipment_master_record(ids["Stockpot"], {
        "display_name": "Family wok", "aliases": ["Sauce vessel", "Soup vessel"],
    }, user_id="user-a")["ok"]
    # Several recipe references or aliases must never inflate an item total.
    with md.recipe_master_connection() as connection:
        connection.executemany(
            "INSERT INTO recipe_equipment(user_id, recipe_id, equipment_id) VALUES (?, ?, ?)",
            [("user-a", "recipe-one", ids["Stockpot"]),
             ("user-a", "recipe-two", ids["Stockpot"]),
             ("user-b", "foreign-recipe", ids["Stockpot"])],
        )
    before = database.read_bytes()
    with identity(app, "user-a"):
        for search in ("", "pan", "Family", "Stockpot", "Sauce vessel", "Secret"):
            rows = md.list_equipment(search=search, limit=500)
            counts = md.equipment_type_counts(search=search)
            assert counts == dict(Counter(row["equipment_section"] for row in rows))
            assert sum(counts.values()) == md.count_equipment(search=search)
        assert md.equipment_type_counts(search="Family") == {"COOKWARE": 1}
        assert md.equipment_type_counts() == {"COOKWARE": 3, "BAKEWARE": 1, "MEASURING": 1}
    assert database.read_bytes() == before


def test_group_counts_normalize_legacy_types_like_rendered_rows(grouped_equipment):
    app, _, ids = grouped_equipment
    with md.recipe_master_connection() as connection:
        connection.executemany("UPDATE equipment SET equipment_section = ? WHERE id = ?", [
            ("Legacy unknown type", ids["Steel pan"]),
            (" misc ", ids["Thermometer"]),
            ("pots and pans", ids["Stockpot"]),
        ])
    with identity(app, "user-a"):
        assert md.equipment_type_counts() == dict(Counter(
            row["equipment_section"] for row in md.list_equipment(limit=500)
        )) == {"COOKWARE": 2, "BAKEWARE": 1, "MISC": 2}
        # A selected type retains the registry's exact existing filter semantics.
        assert md.equipment_type_counts(equipment_section="COOKWARE") == {"COOKWARE": 1}


def test_counts_refresh_after_type_edit_delete_merge_and_page_refresh(grouped_equipment):
    app, _, ids = grouped_equipment
    client = app.test_client()
    sign_in(client, "user-a")
    assert client.patch(f'/api/master-data/equipment/{ids["Copper pan"]}', json={
        "equipment_type": "BAKEWARE",
    }).get_json()["ok"]
    assert group_counts(rendered_context(app, client)) == {"COOKWARE": 2, "BAKEWARE": 2, "MEASURING": 1}
    assert group_counts(rendered_context(app, client, "?search=pan")) == {"COOKWARE": 1, "BAKEWARE": 1}
    assert client.post(f'/admin/master-data/equipment/{ids["Baking tray"]}/delete', json={
        "confirm": True,
    }).get_json()["ok"]
    assert group_counts(rendered_context(app, client, "?equipment_section=BAKEWARE")) == {"BAKEWARE": 1}
    assert client.post(f'/admin/master-data/equipment/{ids["Steel pan"]}/merge', json={
        "target_equipment_id": ids["Stockpot"],
    }).get_json()["ok"]
    assert group_counts(rendered_context(app, client)) == {"COOKWARE": 1, "BAKEWARE": 1, "MEASURING": 1}
    assert group_counts(rendered_context(app, client, "?search=pan")) == {"BAKEWARE": 1}
    # Repeated refreshes recompute from the current database, without stale totals.
    assert group_counts(rendered_context(app, client)) == {"COOKWARE": 1, "BAKEWARE": 1, "MEASURING": 1}


def test_empty_database_counts_do_not_create_storage(monkeypatch, tmp_path):
    app, database, _ = configure_master_data_app(monkeypatch, tmp_path)
    with identity(app, "user-a"):
        assert md.equipment_type_counts() == {}
    assert not database.exists()
