"""Equipment HTTP surfaces never inherit the administrator's cross-account scope."""

import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest

from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_master_image_service as images
from test_recipe_master_data_routes import configure_master_data_app, set_master_data_admin_access, sign_in


PAGE = "/admin/master-data/equipment"
FOREIGN_MARKERS = (
    "Secret mixer", "Secret whisk", "Private alias", "Foreign attached alias",
    "private-mixer.png", "Foreign recipe title", "Foreign recipe notes",
    "user-b@example.com",
)


@pytest.fixture
def equipment_workspaces(monkeypatch, tmp_path):
    app, db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    monkeypatch.setattr(images, "MASTER_IMAGE_PROGRESS_RUNS", {})
    monkeypatch.setattr(master_data, "RECIPE_MASTER_BACKFILL_PROGRESS_RUNS", {})
    records = {}
    definitions = {
        "user-a": [
            ("Alpha skillet", "COOKWARE"),
            ("Cedar spoon", "PREP TOOLS"),
            ("Zebra tray", "BAKEWARE"),
        ],
        "user-b": [("Secret mixer", "APPLIANCES"), ("Secret whisk", "PREP TOOLS")],
    }
    for owner, equipment in definitions.items():
        master_data.sync_recipe_master_records(
            "https://example.com/shared-recipe-url",
            recipe_data={"equipment": [
                {"equipment": name, "equipment_section": section}
                for name, section in equipment
            ]},
            user_id=owner,
        )
        for name, _section in equipment:
            records[name] = master_data.master_record_for_name("equipment", owner, name.lower())
        metadata_path = master_data.recipe_reference_metadata_path(owner)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps({"https://example.com/shared-recipe-url": {
            "recipe_title": "Own recipe title" if owner == "user-a" else "Foreign recipe title",
            "url": "https://example.com/shared-recipe-url",
        }}), encoding="utf-8")

    with master_data.recipe_master_connection() as connection:
        connection.execute("DELETE FROM recipe_equipment WHERE equipment_id = ?", (records["Zebra tray"]["id"],))
        connection.execute(
            "UPDATE equipment SET image_url = '/static/generated/own-skillet.png' WHERE id = ?",
            (records["Alpha skillet"]["id"],),
        )
        connection.execute(
            "UPDATE equipment SET image_url = '/static/generated/private-mixer.png' WHERE id = ?",
            (records["Secret mixer"]["id"],),
        )
        # Legacy databases can contain a recipe link or alias with a mismatched
        # owner. Neither may contribute to the active account's page or counts.
        connection.executemany(
            "INSERT INTO recipe_equipment (user_id, recipe_id, equipment_id, original_recipe_text) VALUES (?, ?, ?, ?)",
            [
                ("user-a", "https://example.com/second-own-recipe", records["Alpha skillet"]["id"], "Own second skillet"),
                ("user-a", "https://example.com/shared-recipe-url", records["Alpha skillet"]["id"], "Own repeated skillet in the same recipe"),
                ("user-b", "https://example.com/foreign-only", records["Alpha skillet"]["id"], "Foreign recipe notes"),
            ],
        )
        connection.execute("CREATE TABLE equipment_aliases (user_id TEXT, equipment_id INTEGER, alias_name TEXT, alias_key TEXT, status TEXT)")
        connection.executemany("INSERT INTO equipment_aliases VALUES (?, ?, ?, ?, ?)", [
            ("user-a", records["Alpha skillet"]["id"], "Family skillet", "family skillet", "active"),
            ("user-b", records["Secret mixer"]["id"], "Private alias", "private alias", "active"),
            ("user-b", records["Alpha skillet"]["id"], "Foreign attached alias", "foreign attached alias", "active"),
        ])
    return app, db_path, records


def scoped_client(app, monkeypatch, *, admin=False, owner="user-a"):
    for user_id in ("user-a", "user-b"):
        set_master_data_admin_access(user_id, admin)
    client = app.test_client()
    sign_in(client, owner)
    return client


def names_in(response):
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    return [item.get_text(strip=True) for item in soup.select("[data-equipment-master-display-name]")]


def assert_private(response):
    text = response.get_data(as_text=True)
    for marker in FOREIGN_MARKERS:
        assert marker not in text


@pytest.mark.parametrize("admin", [False, True])
def test_equipment_page_is_permanently_bound_to_authenticated_workspace(equipment_workspaces, monkeypatch, admin):
    app, _db_path, records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=admin)
    for query in ("", "?scope=all", "?scope=user&user_id=user-b", "?user_id=user-b", "?workspace_id=user-b&account_id=user-b"):
        response = client.get(PAGE + query)
        assert response.status_code == 200
        assert set(names_in(response)) == {"Alpha skillet", "Cedar spoon", "Zebra tray"}
        assert_private(response)
        html = response.get_data(as_text=True)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.select_one('[name="scope"], [name="user_id"], [data-equipment-master-admin-view]') is None
        assert "Admin view" not in html
        assert "Viewing my data" not in html
        assert "Viewing all users" not in html
        assert "Family skillet" in html
        assert "/static/generated/own-skillet.png" in html
        assert len(soup.select("[data-equipment-master-row]")) == 3
        assert master_data.equipment_summary_counts(user_id="user-a") == {
            "total_count": 3, "type_count": 3, "in_use_count": 2, "unused_count": 1,
        }
        skillet = soup.select_one(f'[data-equipment-master-row][data-master-record-id="{records["Alpha skillet"]["id"]}"]')
        assert skillet.select_one("[data-equipment-master-usage-button] strong").get_text(strip=True) == "2"
        assert "Showing 1-3 of 3 equipment." in html
        parameters = parse_qs(urlsplit(response.request.url).query)
        assert "user_id" not in parameters
        assert parameters.get("scope", ["mine"]) == ["mine"]

    # Switching the authenticated session really does switch the workspace.
    sign_in(client, "user-b")
    response = client.get(PAGE)
    assert set(names_in(response)) == {"Secret mixer", "Secret whisk"}
    assert "Alpha skillet" not in response.get_data(as_text=True)
    assert "own-skillet.png" not in response.get_data(as_text=True)


@pytest.mark.parametrize("admin", [False, True])
def test_search_filters_sorts_and_pagination_only_count_active_equipment(equipment_workspaces, monkeypatch, admin):
    app, _db_path, _records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=admin)
    cases = [
        ("search=Secret&scope=all", []),
        ("search=Private&scope=user&user_id=user-b", []),
        ("equipment_section=APPLIANCES&scope=all", []),
        ("equipment_section=COOKWARE&scope=all", ["Alpha skillet"]),
        ("search=skillet&equipment_section=COOKWARE&sort=name_asc", ["Alpha skillet"]),
        ("sort=name_asc&limit=1&page=1&scope=all", ["Alpha skillet"]),
        ("sort=name_asc&limit=1&page=2&scope=all", ["Cedar spoon"]),
        ("sort=name_asc&limit=1&page=3&scope=all", ["Zebra tray"]),
        ("sort=name_asc&limit=1&page=999&scope=user&user_id=user-b", ["Zebra tray"]),
        ("sort=usage_count_desc&limit=1&scope=all", ["Alpha skillet"]),
    ]
    for query, expected in cases:
        response = client.get(PAGE + "?" + query)
        assert response.status_code == 200
        assert names_in(response) == expected
        assert_private(response)
        soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
        assert master_data.count_equipment(user_id="user-a") == 3
        for anchor in soup.select('a[href*="/admin/master-data/equipment"]'):
            parameters = parse_qs(urlsplit(anchor["href"]).query)
            assert parameters.get("scope", ["mine"]) == ["mine"]
            assert "user_id" not in parameters
        if not expected:
            assert not soup.select("[data-equipment-master-row]")
        elif "limit=1" in query:
            assert "of 3 equipment." in response.get_data(as_text=True)


@pytest.mark.parametrize("admin", [False, True])
def test_usage_dialog_rejects_foreign_ids_and_limits_shared_recipe_metadata(equipment_workspaces, monkeypatch, admin):
    app, _db_path, records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=admin)
    own_id = records["Alpha skillet"]["id"]
    foreign_id = records["Secret mixer"]["id"]
    for query in ("", "?scope=all", "?scope=user&user_id=user-b", "?workspace_id=user-b&account_id=user-b"):
        response = client.get(f"/api/master-data/equipment/{foreign_id}/references" + query)
        assert response.status_code in {403, 404}
        assert_private(response)
        response = client.get(f"/api/master-data/equipment/{own_id}/references" + query)
        assert response.status_code == 200
        assert_private(response)
        data = response.get_json()
        assert data["record"]["user_id"] == "user-a"
        assert data["total"] == 2
        assert data["total_reference_count"] == 3
        assert {row["user_id"] for row in data["references"]} == {"user-a"}
        assert all(parse_qs(urlsplit(row["edit_url"]).query)["viewer_user_id"] == ["user-a"] for row in data["references"])
        assert "Own recipe title" in json.dumps(data)
    first = client.get(f"/api/master-data/equipment/{own_id}/references?limit=1&offset=0&scope=all").get_json()
    second = client.get(f"/api/master-data/equipment/{own_id}/references?limit=1&offset=1&user_id=user-b").get_json()
    assert first["total"] == second["total"] == 2
    assert first["next_offset"] == 1
    assert len(first["references"]) == len(second["references"]) == 1
    assert first["references"][0]["recipe_url"] != second["references"][0]["recipe_url"]
    response = client.get(f"/api/master-data/equipment/{own_id}/references?viewer_user_id=user-b")
    assert response.status_code in {403, 404}


@pytest.mark.parametrize("admin", [False, True])
def test_inline_save_reset_and_forged_owner_fields_cannot_change_foreign_equipment(equipment_workspaces, monkeypatch, admin):
    app, _db_path, records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=admin)
    own_id, foreign_id = records["Alpha skillet"]["id"], records["Secret mixer"]["id"]
    original_foreign = master_data.master_record_for_id("equipment", foreign_id, user_id="user-b")
    for payload in (
        {"display_name": "Stolen mixer"},
        {"display_name": "Stolen mixer", "scope": "all", "user_id": "user-b", "workspace_id": "user-b", "account_id": "user-b"},
        {"reset": True, "user_id": "user-b"},
    ):
        response = client.patch(f"/api/master-data/equipment/{foreign_id}/display-name?scope=all&user_id=user-b", json=payload)
        assert response.status_code in {403, 404}
        assert_private(response)
    response = client.patch(f"/api/master-data/equipment/{own_id}/display-name?scope=all&user_id=user-b", json={
        "display_name": "Family skillet renamed", "user_id": "user-b", "equipment_id": foreign_id,
        "workspace_id": "user-b", "scope": "user",
    })
    assert response.status_code == 200
    assert "Family skillet renamed" in names_in(client.get(PAGE))
    assert master_data.master_record_for_id("equipment", foreign_id, user_id="user-b") == original_foreign
    reset = client.patch(f"/api/master-data/equipment/{own_id}/display-name", json={"reset": True})
    assert reset.status_code == 200
    assert reset.get_json()["record"]["name"] == "Alpha skillet"


@pytest.mark.parametrize("admin", [False, True])
def test_equipment_mutations_reject_foreign_sources_and_merge_targets(equipment_workspaces, monkeypatch, admin):
    app, db_path, records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=admin)
    own_id, foreign_id = records["Alpha skillet"]["id"], records["Secret mixer"]["id"]
    # Editors are now available for owned equipment. Every foreign source and
    # merge target remains inaccessible even when an admin forges scope fields.
    before = db_path.read_bytes()
    for source, destination in ((foreign_id, own_id), (foreign_id, records["Secret whisk"]["id"])):
        for method, path in (
            ("PATCH", f"/api/master-data/equipment/{source}"),
            ("GET", f"/api/master-data/equipment/{source}/editor"),
            ("GET", f"/api/master-data/equipment/{source}/merge-options"),
            ("POST", f"/admin/master-data/equipment/{source}/delete"),
            ("POST", f"/admin/master-data/equipment/{source}/merge"),
            ("PATCH", f"/api/master-data/equipment/{source}/order"),
        ):
            response = client.open(path + "?scope=all&user_id=user-b", method=method, json={
                "user_id": "user-b", "workspace_id": "user-b", "scope": "all",
                "source_id": source, "destination_id": destination, "target_id": destination,
                "target_equipment_id": destination, "before_id": destination,
                "name": "Stolen equipment", "confirm": True,
                "position": 1, "expected_ids": [source],
            })
            assert response.status_code in {403, 404}, (method, path, response.status_code)
            assert_private(response)
    response = client.post(f"/admin/master-data/equipment/{own_id}/merge?scope=all&user_id=user-b", json={
        "target_equipment_id": foreign_id, "user_id": "user-b",
    })
    assert response.status_code == 404
    assert_private(response)
    assert db_path.read_bytes() == before
    own_editor = client.get(f"/api/master-data/equipment/{own_id}/editor?scope=all&user_id=user-b")
    assert own_editor.status_code == 200
    assert own_editor.json["record"]["user_id"] == "user-a"
    assert_private(own_editor)
    candidates = client.get(f"/api/master-data/equipment/{own_id}/merge-options?scope=all&user_id=user-b")
    assert candidates.status_code == 200
    assert {row["id"] for row in candidates.json["equipment"]} == {
        records["Cedar spoon"]["id"], records["Zebra tray"]["id"],
    }
    assert_private(candidates)
    assert db_path.read_bytes() == before


def test_equipment_image_jobs_ignore_forged_scope_and_deny_foreign_progress(equipment_workspaces, monkeypatch):
    app, _db_path, records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=True)
    started = []

    def start_job(job_id, **kwargs):
        started.append(kwargs)
        return images.start_master_image_progress(job_id, **kwargs)

    monkeypatch.setattr(images, "start_master_image_generation_job", start_job)
    for scope in ("all", "user"):
        response = client.post("/api/master-data/generate-missing-images", data={
            "record_type": "equipment", "scope": scope, "user_id": "user-b",
            "workspace_id": "user-b", "job_id": "own-" + scope,
            "redirect_url": PAGE + "?scope=user&user_id=user-b",
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data["scope"] == "mine" and data["user_id"] == "user-a"
        assert data["include_all_users"] is False
        assert "user-b" not in data["redirect_url"]
    assert all(run["user_id"] == "user-a" and not run["include_all_users"] for run in started)
    assert client.get("/api/master-data/image-generation-status?job_id=own-all").status_code == 200
    for job_id, owner, all_users in (("foreign-job", "user-b", False), ("global-job", "", True)):
        images.start_master_image_progress(job_id, record_type="equipment", user_id=owner, include_all_users=all_users)
        images.update_master_image_progress(job_id, "record_start", {"row": records["Secret mixer"]})
        images.update_master_image_progress(job_id, "record_done", {"row": records["Secret mixer"], "image_url": "/static/generated/private-mixer.png"})
        for query in ("?job_id=" + job_id, "?job_id=" + job_id + "&scope=all&user_id=user-b"):
            response = client.get("/api/master-data/image-generation-status" + query)
            assert response.status_code in {403, 404}
            assert_private(response)
        before = images.master_image_progress(job_id)
        response = client.post("/api/master-data/generate-missing-images", data={
            "record_type": "equipment", "job_id": job_id, "scope": "all", "user_id": "user-b",
        })
        assert response.status_code in {403, 404}
        assert_private(response)
        assert images.master_image_progress(job_id) == before


@pytest.mark.parametrize("record_type", ["equipment", "ingredients", None])
def test_backfill_cannot_bypass_equipment_scope_with_forged_record_type(equipment_workspaces, monkeypatch, record_type):
    app, db_path, _records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=True)
    for owner, name in (("user-a", "Own backfill pan"), ("user-b", "Foreign backfill appliance")):
        recipe_url = "https://example.com/backfill-" + owner
        metadata = master_data.recipe_reference_metadata_path(owner)
        metadata.write_text(json.dumps({recipe_url: {"url": recipe_url, "name": name, "ingredients": ["Carrot"]}}), encoding="utf-8")
        output_dir = metadata.parent / "output"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "backfill.json").write_text(json.dumps({
            "source_url": recipe_url, "ingredients": [{"ingredient": "Carrot"}],
            "equipment": [{"equipment": name}],
        }), encoding="utf-8")
    # Simulate a legacy value without running schema repair while seeding it.
    # An active-account backfill must not normalize this other owner's row.
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE equipment SET equipment_section = 'Legacy foreign type' WHERE user_id = 'user-b'")
    with master_data.existing_recipe_master_read_connection() as connection:
        foreign_before = [tuple(row) for row in connection.execute("SELECT * FROM equipment WHERE user_id = 'user-b' ORDER BY id")]
        references_before = [tuple(row) for row in connection.execute("SELECT * FROM recipe_equipment WHERE user_id = 'user-b' ORDER BY id")]
    foreign_metadata = master_data.recipe_reference_metadata_path("user-b")
    foreign_files_before = {file: file.read_bytes() for file in foreign_metadata.parent.rglob("*.json")}
    form = {"scope": "all", "user_id": "user-b", "force": "1", "include_legacy": "1", "job_id": "own-backfill"}
    if record_type is not None:
        form["record_type"] = record_type
    response = client.post("/admin/master-data/backfill", data=form, headers={"Accept": "application/json"})
    assert response.status_code == 200, response.get_json()
    assert_private(response)
    assert "Foreign backfill appliance" not in response.get_data(as_text=True)
    progress = response.get_json()["progress"]
    assert progress["users_total"] == progress["users_completed"] == 1
    assert progress["recipes_completed"] == 1
    assert {item["user_id"] for item in progress["items"]} == {"user-a"}
    assert master_data.master_record_for_name("equipment", "user-a", "own backfill pan") is not None
    assert master_data.master_record_for_name("equipment", "user-b", "foreign backfill appliance") is None
    with master_data.existing_recipe_master_read_connection() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM equipment WHERE user_id = 'user-b' ORDER BY id")] == foreign_before
        assert [tuple(row) for row in connection.execute("SELECT * FROM recipe_equipment WHERE user_id = 'user-b' ORDER BY id")] == references_before
    assert {file: file.read_bytes() for file in foreign_files_before} == foreign_files_before


def test_backfill_progress_and_job_collisions_cannot_expose_another_workspace(equipment_workspaces, monkeypatch):
    app, _db_path, _records = equipment_workspaces
    client = scoped_client(app, monkeypatch, admin=True, owner="user-b")
    response = client.post("/admin/master-data/backfill", data={
        "record_type": "equipment", "force": "1", "job_id": "foreign-backfill",
    }, headers={"Accept": "application/json"})
    assert response.status_code == 200
    foreign_progress = master_data.recipe_master_backfill_progress("foreign-backfill")
    sign_in(client, "user-a")
    response = client.get("/api/master-data/backfill-status?job_id=foreign-backfill&scope=all&user_id=user-b")
    assert response.status_code in {403, 404}
    assert_private(response)
    response = client.post("/admin/master-data/backfill", data={
        "record_type": "ingredients", "force": "1", "job_id": "foreign-backfill", "scope": "all", "user_id": "user-b",
    }, headers={"Accept": "application/json"})
    assert response.status_code in {403, 404}
    assert_private(response)
    assert master_data.recipe_master_backfill_progress("foreign-backfill") == foreign_progress
    master_data.start_recipe_master_backfill_progress("offline-global-backfill")
    response = client.get("/api/master-data/backfill-status?job_id=offline-global-backfill")
    assert response.status_code in {403, 404}


def test_structured_migration_preview_only_shows_current_workspace_decisions(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records("https://example.com/own", recipe_data={"equipment": [{"equipment": "Skillet"}]}, user_id="user-a")
    with master_data.recipe_master_connection() as connection:
        requirements.ensure_structured_equipment_schema(connection, authorized=True, migration_token=requirements.PHASE3A_MIGRATION_TOKEN)
        for owner, text in (("user-a", "Own unresolved implement"), ("user-b", "Private unresolved implement")):
            parsed = requirements.requirements_from_recipe_data({"equipment": [{"equipment": text}]})
            requirements.replace_recipe_requirements(connection, owner, "https://example.com/" + owner, parsed, authorized=True, migration_token=requirements.PHASE3A_MIGRATION_TOKEN)
        connection.execute("UPDATE recipe_equipment_requirements SET review_status = 'pending'")
        connection.execute("UPDATE recipe_equipment_options SET review_status = 'pending'")
    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED", "true")
    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_UI_TENANTS", "user-a,user-b")
    client = scoped_client(app, monkeypatch, admin=True)
    response = client.get(PAGE + "?scope=user&user_id=user-b")
    html = response.get_data(as_text=True)
    assert "data-equipment-normalization-review" in html
    assert "Own unresolved implement" in html
    assert "Private unresolved implement" not in html
    with master_data.recipe_master_connection() as connection:
        connection.execute("UPDATE recipe_equipment_requirements SET review_status = 'ready' WHERE user_id = 'user-a'")
        connection.execute("UPDATE recipe_equipment_options SET review_status = 'ready' WHERE user_id = 'user-a'")
    html = client.get(PAGE + "?scope=all").get_data(as_text=True)
    assert "data-equipment-normalization-review" not in html
    assert "Structured Migration Preview" not in html
    assert "Private unresolved implement" not in html
