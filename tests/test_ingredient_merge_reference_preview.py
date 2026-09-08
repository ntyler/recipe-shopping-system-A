"""The merge preview reports references without collapsing recipe occurrences."""

import pytest

from PushShoppingList.services import recipe_ingredient_requirement_service as requirements
from PushShoppingList.services import recipe_master_data_service as master_data
from test_recipe_master_data_routes import configure_master_data_app, sign_in


@pytest.mark.parametrize("viewer", ["user-a", "admin-user"])
def test_merge_preview_counts_name_and_buy_as_references_within_source_workspace(
    monkeypatch, tmp_path, viewer,
):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/butter-sauce",
        recipe_data={"ingredients": [
            {"ingredient": "Butter", "buy_as": "Butter"},
            {"ingredient": "Butter", "buy_as": "Ghee"},
            {"ingredient": "Margarine", "buy_as": "Butter"},
            {"ingredient": "Cooking oil", "buy_as": "Sweet butter"},
        ]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/ghee",
        recipe_data={"ingredients": [{"ingredient": "Ghee"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/other-workspace-butter",
        recipe_data={"ingredients": [
            {"ingredient": "Butter"},
            {"ingredient": "Margarine", "buy_as": "Butter"},
        ]},
        user_id="user-b",
    )
    source = master_data.master_record_for_name("ingredients", "user-a", "butter")
    target = master_data.master_record_for_name("ingredients", "user-a", "ghee")
    with master_data.recipe_master_connection() as connection:
        now = master_data.utc_now_iso()
        connection.execute(
            """
            INSERT INTO ingredient_aliases (
                user_id, ingredient_id, alias_name, normalized_alias, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("user-a", source["id"], "Sweet butter", "sweet butter", now, now),
        )

    listed_source = next(
        row for row in master_data.list_ingredients(user_id="user-a")
        if row["id"] == source["id"]
    )
    assert listed_source["usage_count"] == 1
    assert master_data.count_ingredient_usage(source["id"], user_id="user-a") == 2

    with app.test_client() as client:
        sign_in(client, viewer)
        response = client.get(
            f"/api/master-data/ingredients/{source['id']}/merge-options?search=ghee",
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source"]["reference_count"] == 4
    assert payload["source"]["usage_count"] == 2
    assert [row["ingredient_id"] for row in payload["ingredients"]] == [target["id"]]


def test_merge_preview_does_not_expose_other_workspaces_reference_counts(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/private-butter",
        recipe_data={"ingredients": [{"ingredient": "Butter"}]},
        user_id="user-b",
    )
    private_source = master_data.master_record_for_name("ingredients", "user-b", "butter")
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            f"/api/master-data/ingredients/{private_source['id']}/merge-options"
            "?scope=all&user_id=user-b",
        )

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert "source" not in payload
    assert "ingredients" not in payload


def test_merge_preview_includes_option_only_references_and_legacy_only_recipes(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    normalized_url = "https://example.com/normalized-options"
    requirements.save_recipe_ingredient_requirements(
        normalized_url,
        {"ingredients": [{
            "ingredient": "Butter",
            "substitutions": [{
                "alternative_id": "beans-and-oil",
                "ingredients": [
                    {"ingredient": "Beans", "buy_as": "Beans"},
                    {"ingredient": "Cooking oil", "buy_as": "Beans"},
                ],
            }],
        }]},
        user_id="user-a", sync_compatibility=False,
    )
    source = master_data.master_record_for_name("ingredients", "user-a", "beans")
    target = master_data.master_record_for_name("ingredients", "user-a", "butter")
    with master_data.recipe_master_connection() as connection:
        # A recipe predating normalized requirements must remain in the count.
        connection.execute(
            """INSERT INTO recipe_ingredients (user_id, recipe_id, ingredient_id, buy_as)
               VALUES (?, ?, ?, ?)""",
            ("user-a", "legacy-only-recipe", source["id"], "Beans"),
        )

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(f"/api/master-data/ingredients/{source['id']}/merge-options")
    assert response.status_code == 200
    assert response.get_json()["source"]["reference_count"] == 3
    assert master_data.count_ingredient_usage(source["id"], user_id="user-a") == 1
    assert master_data.count_ingredient_merge_references(source["id"], user_id="user-b") == 0

    result = master_data.merge_ingredient_master_records(source["id"], target["id"], user_id="user-a")
    assert result["ok"] is True
    assert result["moved_reference_count"] == 1
    assert result["normalized_moved_reference_count"] == 1
    assert "Beans" in result["aliases"]
    # The Buy As-only alternative resolves through the preserved alias, while
    # the selected canonical also keeps its original Butter reference.
    assert master_data.count_ingredient_merge_references(target["id"], user_id="user-a") == 4
