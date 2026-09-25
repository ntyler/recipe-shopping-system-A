import json
from pathlib import Path

import pytest
from flask import Flask, g, session
from jinja2 import FileSystemLoader

from PushShoppingList.routes import main_routes
from PushShoppingList.services import meal_plan_service as service
from PushShoppingList.services import storage_service


MEMBER_DETAILS = {"first_name": "", "last_name": "", "default_portion": 1, "group_ids": []}


@pytest.fixture
def isolated_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    path = tmp_path / "meal_plan.json"
    monkeypatch.setattr(service, "MEAL_PLAN_FILE", path)
    return path


def family_batch(member, other=None):
    portions = [{"member_id": member["id"], "servings": 3}]
    if other:
        portions.append({"member_id": other["id"], "servings": 0.5})
    return service.add_meal_prep_batch({
        "recipe_url": "recipe://soup", "recipe_name": "Soup", "portion_mode": "family",
        "prep_notes": "Portion the batch", "prep_steps": [{"date": "2026-09-27", "instruction": "Cook"}],
    }, [
        {"date": "2026-09-28", "meal_type": "breakfast", "member_portions": portions},
        {"date": "2026-09-28", "meal_type": "dinner", "member_portions": portions[:1]},
        {"date": "2026-09-29", "meal_type": "lunch", "member_portions": portions[:1]},
    ])


def test_legacy_members_are_active_and_archive_status_survives_save(isolated_plan):
    isolated_plan.write_text(json.dumps({"members": [{"id": "nate", "name": "Nate"}]}), encoding="utf-8")
    assert service.list_meal_plan_members() == [{**MEMBER_DETAILS, "id": "nate", "name": "Nate", "archived": False, "meal_count": 0}]
    service.save_meal_plan(service.load_meal_plan())
    assert json.loads(isolated_plan.read_text())["members"] == [{**MEMBER_DETAILS, "id": "nate", "name": "Nate", "archived": False}]
    assert json.loads(isolated_plan.read_text())["groups"] == []
    service.update_meal_plan_member("nate", archived=True)
    assert service.list_meal_plan_members() == []
    assert service.load_meal_plan()["members"][0]["archived"] is True
    assert service.list_meal_plan_members(include_archived=True)[0]["archived"] is True


def test_usage_counts_meals_instead_of_batches_or_servings(isolated_plan):
    nate = service.add_meal_plan_member("Nate")
    alex = service.add_meal_plan_member("Alex")
    batch, meals = family_batch(nate, alex)
    # Household-only meals and preparation tasks do not consume a member.
    service.add_meal({"date": "2026-09-30", "meal_type": "dinner", "recipe_url": "recipe://soup", "recipe_name": "Soup"})
    counts = {member["name"]: member["meal_count"] for member in service.list_meal_plan_members()}
    assert counts == {"Nate": 3, "Alex": 1}
    service.delete_meal(meals[0]["id"])
    counts = {member["name"]: member["meal_count"] for member in service.list_meal_plan_members()}
    assert counts == {"Nate": 2, "Alex": 0}
    service.delete_meal_prep_batch(batch["id"])
    assert all(member["meal_count"] == 0 for member in service.list_meal_plan_members())


def test_member_summary_counts_duplicate_member_occurrences_and_meal_ids_once():
    member = {"id": "nate", "name": "Nate", "archived": False}
    meal = {"id": "meal1", "member_portions": [{"member_id": "nate"}, {"member_id": "nate"}]}
    assert service.meal_plan_member_summary(member, [meal, meal])["meal_count"] == 1


def test_archive_and_restore_keep_meal_history_and_stable_identity(isolated_plan):
    nate = service.add_meal_plan_member("Nate")
    family_batch(nate)
    original = service.load_meal_plan()
    archived = service.update_meal_plan_member(nate["id"], archived=True)
    assert archived == {**nate, "archived": True, "meal_count": 3}
    after_archive = service.load_meal_plan()
    assert after_archive["meals"] == original["meals"]
    assert after_archive["batches"] == original["batches"]
    renamed = service.update_meal_plan_member(nate["id"], "Nathan")
    assert renamed["archived"] is True
    assert renamed["meal_count"] == 3
    restored = service.update_meal_plan_member(nate["id"], archived=False)
    assert restored == {**MEMBER_DETAILS, "id": nate["id"], "name": "Nathan", "archived": False, "meal_count": 3}
    history = service.load_meal_plan()
    for old, current in zip(original["meals"], history["meals"]):
        assert current["id"] == old["id"]
        assert current["planned_servings"] == old["planned_servings"]
        assert current["member_portions"][0] == {**old["member_portions"][0], "name": "Nathan"}
        assert current["member_portions"][0]["name_snapshot"] == "Nate"
    assert history["batches"] == original["batches"]


def test_archived_members_cannot_be_allocated_and_failure_is_atomic(isolated_plan):
    nate = service.add_meal_plan_member("Nate")
    alex = service.add_meal_plan_member("Alex")
    service.update_meal_plan_member(nate["id"], archived=True)
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="archived"):
        service.add_meal_prep_batch({"recipe_url": "recipe://soup", "recipe_name": "Soup", "portion_mode": "family"}, [
            {"date": "2026-09-28", "meal_type": "breakfast", "member_portions": [{"member_id": alex["id"], "servings": 1}]},
            {"date": "2026-09-28", "meal_type": "dinner", "member_portions": [{"member_id": nate["id"], "servings": 1}]},
        ])
    assert isolated_plan.read_bytes() == before
    service.update_meal_plan_member(nate["id"], archived=False)
    assert len(family_batch(nate)[1]) == 3


def test_archived_names_remain_reserved_and_rename_conflicts_are_atomic(isolated_plan):
    nate = service.add_meal_plan_member("Nate")
    alex = service.add_meal_plan_member("Alex")
    service.update_meal_plan_member(nate["id"], archived=True)
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="Restore"):
        service.add_meal_plan_member(" nate ")
    with pytest.raises(ValueError, match="Restore"):
        service.update_meal_plan_member(alex["id"], "NATE", archived=True)
    assert isolated_plan.read_bytes() == before
    service.update_meal_plan_member(nate["id"], "Nathan", archived=False)
    assert service.add_meal_plan_member("Nate")["id"] != nate["id"]


@pytest.fixture
def scoped_client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(service, "MEAL_PLAN_FILE", storage_service.scoped_package_path("meal_plan.json"))
    monkeypatch.setattr(main_routes, "current_public_user", lambda: {"user_id": g.authenticated_user_id} if g.authenticated_user_id else None)
    monkeypatch.setattr(main_routes, "is_guest_session", lambda: bool(g.authenticated_guest_session_id))
    monkeypatch.setattr(main_routes, "recipe_url_rows", lambda: [])
    monkeypatch.setattr(main_routes, "meal_plan_recipe_option_rows", lambda rows: [{"url": "recipe://soup", "name": "Soup", "default_servings": 12}])
    monkeypatch.setattr(main_routes, "load_recipe_output", lambda url: {"ingredients": [{"name": "carrot"}]})
    app = Flask(__name__)
    app.secret_key = "family-members-test-only"
    app.register_blueprint(main_routes.main_bp)

    @app.before_request
    def identity():
        g.session_identity_validated = True
        g.authenticated_user_id = session.get("user_id", "")
        g.authenticated_guest_session_id = session.get("guest_id", "")

    return app.test_client()


def sign_in(client, identity, guest=False):
    with client.session_transaction() as current:
        current.clear()
        current["guest_id" if guest else "user_id"] = identity


def test_member_management_api_shapes_archiving_and_usage(scoped_client):
    client = scoped_client
    sign_in(client, "alice")
    created = client.post("/api/meal-plan/members", json={"name": "Nate"})
    assert created.status_code == 201
    member = created.json["member"]
    assert member == {**MEMBER_DETAILS, "id": member["id"], "name": "Nate", "archived": False, "meal_count": 0}
    meal_data = {"recipe_url": "recipe://soup", "portion_mode": "family", "allocations": [
        {"date": "2026-09-28", "meal_type": "dinner", "member_portions": [{"member_id": member["id"], "servings": 2.5}]},
    ]}
    assert client.post("/api/meal-plan/batches", json=meal_data).status_code == 201
    endpoint = f"/api/meal-plan/members/{member['id']}"
    archived = client.patch(endpoint, json={"archived": True})
    assert archived.status_code == 200
    assert archived.json["member"] == {**member, "archived": True, "meal_count": 1}
    active_list = client.get("/api/meal-plan/members").json
    assert active_list["members"] == []
    assert active_list["archived_members"] == [{"id": member["id"], "name": "Nate"}]
    full_list = client.get("/api/meal-plan/members?include_archived=true").json
    assert full_list["members"] == [archived.json["member"]]
    assert full_list["archived_members"] == active_list["archived_members"]
    meal_data["allocations"][0]["date"] = "2026-09-29"
    rejected = client.post("/api/meal-plan/batches", json=meal_data)
    assert rejected.status_code == 400 and "archived" in rejected.json["error"]
    assert len(client.get("/api/meal-plan?recipe_url=recipe://soup").json["meals"]) == 1
    restored = client.patch(endpoint, json={"name": "Nathan", "archived": False})
    assert restored.json["member"] == {**member, "name": "Nathan", "meal_count": 1}
    assert client.get("/api/meal-plan/members").json["archived_members"] == []
    assert client.post("/api/meal-plan/batches", json=meal_data).status_code == 201
    assert client.get("/api/meal-plan/members").json["members"][0]["meal_count"] == 2
    assert client.delete(endpoint).status_code == 405


def test_members_management_is_scoped_to_authenticated_user_or_guest(scoped_client):
    client = scoped_client
    assert client.get("/api/meal-plan/members?include_archived=true").status_code == 403
    assert client.post("/api/meal-plan/members", json={"name": "Nate"}).status_code == 403
    assert client.patch("/api/meal-plan/members/missing", json={"archived": True}).status_code == 403
    sign_in(client, "alice")
    member = client.post("/api/meal-plan/members", json={"name": "Nate"}).json["member"]
    endpoint = f"/api/meal-plan/members/{member['id']}"
    client.patch(endpoint, json={"archived": True})
    for identity, guest in (("bob", False), ("guest1", True)):
        sign_in(client, identity, guest)
        assert client.get("/api/meal-plan/members?include_archived=true").json["members"] == []
        assert client.get("/api/meal-plan/members").json["archived_members"] == []
        assert client.patch(endpoint, json={"archived": False}).status_code == 404
        assert client.post("/api/meal-plan/members", json={"name": "Nate"}).status_code == 201
    sign_in(client, "alice")
    assert client.get("/api/meal-plan/members?include_archived=true").json["members"] == [{**member, "archived": True}]


@pytest.mark.parametrize("identity,guest", [("alice", False), ("guest1", True)])
def test_member_api_rejects_conflicting_or_duplicate_viewer_assertions(scoped_client, identity, guest):
    client = scoped_client
    sign_in(client, identity, guest)
    member = client.post("/api/meal-plan/members", json={"name": "Nate"}).json["member"]
    for query, status in (("?viewer_user_id=bob", 403), ("?viewer_user_id=alice&viewer_user_id=alice", 400)):
        assert client.get(f"/api/meal-plan/members{query}").status_code == status
        assert client.post(f"/api/meal-plan/members{query}", json={"name": "Alex"}).status_code == status
        assert client.patch(f"/api/meal-plan/members/{member['id']}{query}", json={"archived": True}).status_code == status
    assert client.get("/api/meal-plan/members").json["members"] == [member]


@pytest.mark.parametrize("payload", [
    None, [], "Nate", {}, {"unexpected": True}, {"name": "Nate", "extra": 1},
    {"archived": "false"}, {"archived": 0}, {"archived": 1}, {"archived": None},
    {"name": None}, {"name": " "}, {"name": []}, {"name": "x" * 101},
    {"name": "Nathan", "archived": "true"},
])
def test_invalid_partial_update_never_changes_member(scoped_client, payload):
    client = scoped_client
    sign_in(client, "alice")
    member = client.post("/api/meal-plan/members", json={"name": "Nate"}).json["member"]
    response = client.patch(f"/api/meal-plan/members/{member['id']}", json=payload)
    assert response.status_code == 400
    assert client.get("/api/meal-plan/members?include_archived=true").json["members"] == [member]


def test_family_members_page_redirects_anonymous_visitors(scoped_client):
    response = scoped_client.get("/settings/family-members")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#userAccountSection")


@pytest.mark.parametrize("identity,guest", [("alice", False), ("guest1", True)])
def test_family_members_page_shares_saved_members_counts_and_workspace_scope(scoped_client, monkeypatch, identity, guest):
    client = scoped_client
    captured = []

    def capture_template(template, **context):
        captured.append((template, context))
        return "family members page"

    monkeypatch.setattr(main_routes, "render_template", capture_template)
    sign_in(client, identity, guest)
    nate = client.post("/api/meal-plan/members", json={"name": "Nate"}).json["member"]
    alex = client.post("/api/meal-plan/members", json={"name": "Alex"}).json["member"]
    response = client.post("/api/meal-plan/batches", json={
        "recipe_url": "recipe://soup", "portion_mode": "family", "allocations": [
            {"date": "2026-09-28", "meal_type": "breakfast", "member_portions": [{"member_id": nate["id"], "servings": 2.5}]},
            {"date": "2026-09-28", "meal_type": "dinner", "member_portions": [{"member_id": nate["id"], "servings": 1}]},
        ],
    })
    assert response.status_code == 201
    client.patch(f"/api/meal-plan/members/{nate['id']}", json={"archived": True})
    assert client.get("/settings/family-members").status_code == 200
    template, context = captured[-1]
    assert template == "family_members.html"
    assert context["family_members"] == {
        "members": [{**nate, "archived": True, "meal_count": 2}, alex],
        "groups": [],
        "viewer_user_id": "" if guest else identity,
        "settings_url": "/#settingsProfilePanel",
        "meal_planner_url": "/#mealPlannerPage",
        "api_url": "/api/meal-plan/members",
        "groups_api_url": "/api/meal-plan/groups",
    }
    assert context["is_guest_demo"] is guest
    assert context["current_user"] == (None if guest else {"user_id": identity})
    # The page uses the same workspace records as the scheduling APIs.
    sign_in(client, "other-user")
    assert client.get("/settings/family-members").status_code == 200
    assert captured[-1][1]["family_members"]["members"] == []
    sign_in(client, identity, guest)
    assert client.get("/settings/family-members").status_code == 200
    assert len(captured[-1][1]["family_members"]["members"]) == 2


@pytest.mark.parametrize("identity,guest", [("alice", False), ("guest1", True)])
def test_family_members_page_rejects_forged_or_duplicate_viewers(scoped_client, monkeypatch, identity, guest):
    sign_in(scoped_client, identity, guest)
    rendered = []
    monkeypatch.setattr(main_routes, "render_template", lambda *args, **kwargs: rendered.append(kwargs) or "page")
    assert scoped_client.get("/settings/family-members?viewer_user_id=other-user").status_code == 403
    assert scoped_client.get("/settings/family-members?viewer_user_id=alice&viewer_user_id=alice").status_code == 400
    assert rendered == []
    if not guest:
        assert scoped_client.get("/settings/family-members?viewer_user_id=alice").status_code == 200
        assert rendered[-1]["family_members"]["viewer_user_id"] == "alice"


def test_family_members_page_renders_shared_shell_and_safe_member_bootstrap(scoped_client, monkeypatch):
    template_dir = Path(main_routes.__file__).resolve().parents[1] / "templates"
    scoped_client.application.jinja_loader = FileSystemLoader(str(template_dir))
    # The shared shell links to these other blueprints; this isolated app only
    # exercises the main blueprint, so supply their URL building targets.
    scoped_client.application.add_url_rule("/pantry", endpoint="pantry_bp.pantry_coming_soon_route", view_func=lambda: "pantry")
    scoped_client.application.add_url_rule("/sign-out", endpoint="account_bp.sign_out_route", view_func=lambda: "sign out")
    monkeypatch.setattr(main_routes, "current_public_user", lambda: {"user_id": g.authenticated_user_id, "display_name": "Alice", "email": "alice@example.test"})
    sign_in(scoped_client, "alice")
    member = scoped_client.post("/api/meal-plan/members", json={"name": '<Nate & "family">'}).json["member"]
    scoped_client.patch(f"/api/meal-plan/members/{member['id']}", json={"archived": True})
    response = scoped_client.get("/settings/family-members")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<title>Family Members · AI Pantry</title>' in html
    assert 'data-app-layout' in html
    assert 'data-viewer-user-id="alice"' in html
    assert 'data-api-url="/api/meal-plan/members"' in html
    assert 'css/family-members.css' in html and 'js/family-members.js' in html
    assert 'Used in meal plans</th>' in html
    assert 'Archived members stay in existing meal plans.' in html
    data = html.split('<script id="familyMembersData" type="application/json">', 1)[1].split('</script>', 1)[0]
    assert '<Nate' not in data
    assert json.loads(data) == [{**member, "archived": True}]


def test_member_details_and_explicit_groups_persist_without_name_inference(isolated_plan):
    household = service.add_meal_plan_group("  Tyler Family  ")
    friends = service.add_meal_plan_group("Friends")
    nate = service.add_meal_plan_member("Nate", first_name=" Nathaniel ", last_name=" Tyler ",
        default_portion=0.5, group_ids=[household["id"], household["id"], friends["id"]])
    alex = service.add_meal_plan_member("Alex", last_name="Tyler")
    assert nate == {"id": nate["id"], "name": "Nate", "first_name": "Nathaniel", "last_name": "Tyler",
        "default_portion": 0.5, "group_ids": [household["id"], friends["id"]], "archived": False, "meal_count": 0}
    assert alex["group_ids"] == []  # Shared surnames never imply membership.
    assert household["name"] == "Tyler Family"
    assert service.list_meal_plan_members() == [nate, alex]
    assert service.list_meal_plan_groups() == [household, friends]
    stored = json.loads(isolated_plan.read_text())
    assert stored["members"][0] == {key: value for key, value in nate.items() if key != "meal_count"}
    assert stored["groups"] == [household, friends]


def test_member_metadata_changes_leave_historical_meals_and_portions_unchanged(isolated_plan):
    member = service.add_meal_plan_member("Nate", default_portion=0.5)
    family_batch(member)
    group = service.add_meal_plan_group("Family")
    before = service.load_meal_plan()
    changed = service.update_meal_plan_member(member["id"], first_name="Nathaniel", last_name="Tyler",
        default_portion=2.5, group_ids=[group["id"]])
    assert changed["meal_count"] == 3
    assert changed["name"] == "Nate"
    assert changed["default_portion"] == 2.5
    after = service.load_meal_plan()
    assert before["meals"] == after["meals"]
    assert before["batches"] == after["batches"]


def test_archived_groups_keep_associations_but_reject_new_assignments(isolated_plan):
    group = service.add_meal_plan_group("Family")
    member = service.add_meal_plan_member("Nate", group_ids=[group["id"]])
    other = service.add_meal_plan_member("Alex")
    family_batch(member)
    before = service.load_meal_plan()
    archived = service.update_meal_plan_group(group["id"], archived=True)
    assert service.list_meal_plan_groups() == []
    assert service.list_meal_plan_groups(include_archived=True) == [archived]
    assert service.load_meal_plan()["meals"] == before["meals"]
    assert service.load_meal_plan()["batches"] == before["batches"]
    assert service.list_meal_plan_members()[0]["group_ids"] == [group["id"]]
    # Existing associations can be retained while changing independent details.
    assert service.update_meal_plan_member(member["id"], first_name="Nathaniel", group_ids=[group["id"]])["group_ids"] == [group["id"]]
    assert service.update_meal_plan_member(member["id"], default_portion=0.5)["group_ids"] == [group["id"]]
    current_bytes = isolated_plan.read_bytes()
    for operation in (
        lambda: service.add_meal_plan_member("New", group_ids=[group["id"]]),
        lambda: service.update_meal_plan_member(other["id"], group_ids=[group["id"]]),
        lambda: service.add_meal_plan_members_bulk([{"name": "Bulk"}], group_ids=[group["id"]]),
    ):
        with pytest.raises(ValueError, match="archived"):
            operation()
        assert isolated_plan.read_bytes() == current_bytes
    assert service.update_meal_plan_member(member["id"], group_ids=[])["group_ids"] == []
    with pytest.raises(ValueError, match="archived"):
        service.update_meal_plan_member(member["id"], group_ids=[group["id"]])
    service.update_meal_plan_group(group["id"], "Relatives", archived=False)
    assert service.update_meal_plan_member(other["id"], group_ids=[group["id"]])["group_ids"] == [group["id"]]
    assert service.list_meal_plan_groups()[0]["name"] == "Relatives"


def test_group_names_are_unique_across_active_and_archived_records(isolated_plan):
    group = service.add_meal_plan_group("Family")
    other = service.add_meal_plan_group("Friends")
    with pytest.raises(ValueError, match="already exists"):
        service.add_meal_plan_group(" family ")
    service.update_meal_plan_group(group["id"], archived=True)
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="Restore"):
        service.add_meal_plan_group("FAMILY")
    with pytest.raises(ValueError, match="Restore"):
        service.update_meal_plan_group(other["id"], "Family", archived=True)
    assert isolated_plan.read_bytes() == before
    assert service.update_meal_plan_group("unknown", archived=True) is None


def test_bulk_member_creation_is_one_write_with_shared_explicit_groups(isolated_plan, monkeypatch):
    group = service.add_meal_plan_group("Lunch Crew")
    saves = []
    original_save = service.save_meal_plan

    def count_save(payload):
        saves.append(payload)
        return original_save(payload)

    monkeypatch.setattr(service, "save_meal_plan", count_save)
    result = service.add_meal_plan_members_bulk([
        {"name": "Nate", "first_name": "Nathaniel", "last_name": "Tyler", "default_portion": 1.5},
        {"name": "Alex", "default_portion": 0.5},
    ], group_ids=[group["id"], group["id"]])
    assert len(saves) == 1
    assert len({member["id"] for member in result}) == 2
    assert [member["name"] for member in result] == ["Nate", "Alex"]
    assert [member["default_portion"] for member in result] == [1.5, 0.5]
    assert all(member["group_ids"] == [group["id"]] for member in result)
    assert service.list_meal_plan_members() == result


@pytest.mark.parametrize("rows", [
    [], None, "Nate", [{"name": "Same"}, {"name": " same "}],
    [{"name": "Good"}, {"name": "Existing"}], [{"name": "Good"}, {"name": "Archived"}],
    [{"name": "Good"}, {"name": ""}], [{"name": "Good"}, {"name": "Bad", "default_portion": 0}],
    [{"name": "Good"}, {"name": "Bad", "unknown": "x"}], [{"name": "Good"}, {"name": "Bad", "group_ids": []}],
    [{"name": "Good"}, {"first_name": "No display name"}], [{"name": "Good"}, None],
    [{"name": "Good"}, {"name": "Bad", "first_name": None}], [{"name": str(i)} for i in range(101)],
])
def test_invalid_bulk_member_batch_never_partially_writes(isolated_plan, rows):
    service.add_meal_plan_member("Existing")
    archived = service.add_meal_plan_member("Archived")
    service.update_meal_plan_member(archived["id"], archived=True)
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError):
        service.add_meal_plan_members_bulk(rows)
    assert isolated_plan.read_bytes() == before


@pytest.mark.parametrize("details", [
    {"first_name": None}, {"last_name": []}, {"first_name": "x" * 101}, {"last_name": "x" * 101},
    {"default_portion": 0}, {"default_portion": -1}, {"default_portion": True}, {"default_portion": None},
    {"default_portion": float("inf")}, {"default_portion": float("nan")}, {"default_portion": "many"},
    {"group_ids": "group"}, {"group_ids": None}, {"group_ids": [""]}, {"group_ids": [1]}, {"group_ids": ["not-in-workspace"]},
])
def test_invalid_member_details_rejected_on_create_and_patch(scoped_client, details):
    client = scoped_client
    sign_in(client, "alice")
    member = client.post("/api/meal-plan/members", json={"name": "Nate"}).json["member"]
    assert client.post("/api/meal-plan/members", json={"name": "New", **details}).status_code == 400
    assert client.patch(f"/api/meal-plan/members/{member['id']}", json=details).status_code == 400
    assert client.get("/api/meal-plan/members").json["members"] == [member]


def test_groups_and_bulk_routes_share_workspace_and_return_member_metadata(scoped_client, monkeypatch):
    client = scoped_client
    sign_in(client, "alice")
    group = client.post("/api/meal-plan/groups", json={"name": "Family"}).json["group"]
    assert group == {"id": group["id"], "name": "Family", "archived": False}
    response = client.post("/api/meal-plan/members/bulk", json={"members": [
        {"name": "Nate", "first_name": "Nathaniel", "last_name": "Tyler", "default_portion": 0.5},
        {"name": "Alex"},
    ], "group_ids": [group["id"]]})
    assert response.status_code == 201
    members = response.json["members"]
    assert len(members) == 2
    assert members[0]["first_name"] == "Nathaniel" and members[0]["default_portion"] == 0.5
    assert all(member["group_ids"] == [group["id"]] for member in members)
    assert client.get("/api/meal-plan/members").json == {"ok": True, "members": members, "groups": [group], "archived_members": []}
    assert client.get("/api/meal-plan/groups").json == {"ok": True, "groups": [group]}
    archived = client.patch(f"/api/meal-plan/groups/{group['id']}", json={"archived": True}).json["group"]
    assert client.get("/api/meal-plan/groups").json["groups"] == []
    assert client.get("/api/meal-plan/members").json["groups"] == []
    assert client.get("/api/meal-plan/members?include_archived=true").json["groups"] == [archived]
    assert client.get("/api/meal-plan/groups?include_archived=true").json["groups"] == [archived]
    captured = []
    monkeypatch.setattr(main_routes, "render_template", lambda *args, **kwargs: captured.append(kwargs) or "page")
    assert client.get("/settings/family-members").status_code == 200
    assert captured[0]["family_members"]["groups"] == [archived]
    assert captured[0]["family_members"]["groups_api_url"] == "/api/meal-plan/groups"
    assert client.delete(f"/api/meal-plan/groups/{group['id']}").status_code == 405
    for identity, guest in (("bob", False), ("guest1", True)):
        sign_in(client, identity, guest)
        assert client.get("/api/meal-plan/groups?include_archived=true").json["groups"] == []
        assert client.patch(f"/api/meal-plan/groups/{group['id']}", json={"archived": False}).status_code == 404
        assert client.post("/api/meal-plan/members", json={"name": "New", "group_ids": [group["id"]]}).status_code == 400
        assert client.post("/api/meal-plan/members/bulk", json={"members": [{"name": "New"}], "group_ids": [group["id"]]}).status_code == 400
        own_group = client.post("/api/meal-plan/groups", json={"name": "Family"}).json["group"]
        assert own_group["id"] != group["id"]


def test_group_and_bulk_routes_enforce_auth_and_viewer_scope(scoped_client):
    client = scoped_client
    assert client.get("/api/meal-plan/groups").status_code == 403
    assert client.post("/api/meal-plan/groups", json={"name": "Family"}).status_code == 403
    assert client.patch("/api/meal-plan/groups/missing", json={"archived": True}).status_code == 403
    assert client.post("/api/meal-plan/members/bulk", json={"members": [{"name": "Nate"}]}).status_code == 403
    for identity, guest in (("alice", False), ("guest1", True)):
        sign_in(client, identity, guest)
        for query, status in (("?viewer_user_id=other", 403), ("?viewer_user_id=alice&viewer_user_id=alice", 400)):
            assert client.get(f"/api/meal-plan/groups{query}").status_code == status
            assert client.post(f"/api/meal-plan/groups{query}", json={"name": "Family"}).status_code == status
            assert client.patch(f"/api/meal-plan/groups/missing{query}", json={"archived": True}).status_code == status
            assert client.post(f"/api/meal-plan/members/bulk{query}", json={"members": [{"name": "Nate"}]}).status_code == status


@pytest.mark.parametrize("payload", [None, [], {}, {"name": ""}, {"name": None}, {"name": "x" * 101}, {"name": "Family", "unknown": 1}])
def test_malformed_group_requests_do_not_write(scoped_client, payload):
    client = scoped_client
    sign_in(client, "alice")
    group = client.post("/api/meal-plan/groups", json={"name": "Family"}).json["group"]
    assert client.post("/api/meal-plan/groups", json=payload).status_code == 400
    assert client.patch(f"/api/meal-plan/groups/{group['id']}", json=payload).status_code == 400
    assert client.get("/api/meal-plan/groups").json["groups"] == [group]


@pytest.mark.parametrize("archived", [None, 0, 1, "false", [], {}])
def test_group_archive_state_requires_boolean(scoped_client, archived):
    sign_in(scoped_client, "alice")
    group = scoped_client.post("/api/meal-plan/groups", json={"name": "Family"}).json["group"]
    assert scoped_client.patch(f"/api/meal-plan/groups/{group['id']}", json={"archived": archived}).status_code == 400
    assert scoped_client.get("/api/meal-plan/groups").json["groups"] == [group]


@pytest.mark.parametrize("payload", [None, [], {}, {"members": []}, {"members": [{"name": "Nate"}], "unexpected": 1},
    {"members": [{"name": "Nate"}, {"name": "nate"}]}, {"members": [{"name": "Nate"}], "group_ids": ["unknown"]}])
def test_malformed_bulk_request_never_adds_members(scoped_client, payload):
    sign_in(scoped_client, "alice")
    assert scoped_client.post("/api/meal-plan/members/bulk", json=payload).status_code == 400
    assert scoped_client.get("/api/meal-plan/members").json["members"] == []
