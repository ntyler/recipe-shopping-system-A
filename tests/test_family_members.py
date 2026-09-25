import json
from pathlib import Path

import pytest
from flask import Flask, g, session
from jinja2 import FileSystemLoader

from PushShoppingList.routes import main_routes
from PushShoppingList.services import meal_plan_service as service
from PushShoppingList.services import storage_service


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
    assert service.list_meal_plan_members() == [{"id": "nate", "name": "Nate", "archived": False, "meal_count": 0}]
    service.save_meal_plan(service.load_meal_plan())
    assert json.loads(isolated_plan.read_text())["members"] == [{"id": "nate", "name": "Nate", "archived": False}]
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
    assert restored == {"id": nate["id"], "name": "Nathan", "archived": False, "meal_count": 3}
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
    assert member == {"id": member["id"], "name": "Nate", "archived": False, "meal_count": 0}
    meal_data = {"recipe_url": "recipe://soup", "portion_mode": "family", "allocations": [
        {"date": "2026-09-28", "meal_type": "dinner", "member_portions": [{"member_id": member["id"], "servings": 2.5}]},
    ]}
    assert client.post("/api/meal-plan/batches", json=meal_data).status_code == 201
    endpoint = f"/api/meal-plan/members/{member['id']}"
    archived = client.patch(endpoint, json={"archived": True})
    assert archived.status_code == 200
    assert archived.json["member"] == {**member, "archived": True, "meal_count": 1}
    assert client.get("/api/meal-plan/members").json["members"] == []
    assert client.get("/api/meal-plan/members?include_archived=true").json["members"] == [archived.json["member"]]
    meal_data["allocations"][0]["date"] = "2026-09-29"
    rejected = client.post("/api/meal-plan/batches", json=meal_data)
    assert rejected.status_code == 400 and "archived" in rejected.json["error"]
    assert len(client.get("/api/meal-plan?recipe_url=recipe://soup").json["meals"]) == 1
    restored = client.patch(endpoint, json={"name": "Nathan", "archived": False})
    assert restored.json["member"] == {**member, "name": "Nathan", "meal_count": 1}
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
        "viewer_user_id": "" if guest else identity,
        "settings_url": "/#settingsProfilePanel",
        "meal_planner_url": "/#mealPlannerPage",
        "api_url": "/api/meal-plan/members",
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
