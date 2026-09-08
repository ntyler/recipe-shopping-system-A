"""Direct row merge actions require another ingredient in the same workspace."""

from flask import template_rendered
import pytest

from PushShoppingList.services import recipe_master_data_service as master_data
from test_recipe_master_data_routes import configure_master_data_app, sign_in


def ingredient_page_context(app, client, query=""):
    contexts = []

    def capture_template(sender, template, context, **extra):
        contexts.append(context["master_data"])

    with template_rendered.connected_to(capture_template, app):
        response = client.get(f"/admin/master-data/ingredients{query}")
    assert response.status_code == 200
    return contexts[-1]


def seed_ingredients(user_id, names):
    master_data.sync_recipe_master_records(
        f"https://example.com/{user_id}/ingredients",
        recipe_data={"ingredients": [{"ingredient": name} for name in names]},
        user_id=user_id,
    )


@pytest.mark.parametrize("query", [
    "?search=Butter",
    "?limit=1&sort=name_asc",
    "?store_section=DAIRY%20%26%20EGGS",
])
def test_merge_remains_available_when_target_is_outside_visible_rows(monkeypatch, tmp_path, query):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_ingredients("user-a", ["Butter", "Zucchini"])

    with app.test_client() as client:
        sign_in(client, "user-a")
        context = ingredient_page_context(app, client, query)

    assert [row["name"] for row in context["rows"]] == ["Butter"]
    source = context["rows"][0]
    assert source["can_merge"] is True
    assert source["merge_blocked_reason"] == ""
    # Recipe references protect deletion but do not prohibit merging.
    assert source["can_delete"] is False


def test_other_workspace_ingredient_is_not_a_merge_target(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_ingredients("user-a", ["Butter"])
    seed_ingredients("user-b", ["Ghee"])

    with app.test_client() as client:
        sign_in(client, "user-a")
        context = ingredient_page_context(app, client, "?scope=all&user_id=user-b")

    assert [row["user_id"] for row in context["rows"]] == ["user-a"]
    source = context["rows"][0]
    assert source["can_merge"] is False
    assert source["merge_blocked_reason"] == (
        "Add another ingredient in this workspace before merging duplicates."
    )


@pytest.mark.parametrize("query", ["?scope=all", "?scope=user&user_id=user-a"])
def test_admin_merge_eligibility_uses_each_source_workspace(monkeypatch, tmp_path, query):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_ingredients("user-a", ["Butter", "Ghee"])
    seed_ingredients("user-b", ["Milk"])

    with app.test_client() as client:
        sign_in(client, "admin-user")
        context = ingredient_page_context(app, client, query)

    rows = context["rows"]
    assert rows
    for row in rows:
        assert row["can_merge"] is (row["user_id"] == "user-a")
        assert bool(row["merge_blocked_reason"]) is (not row["can_merge"])
