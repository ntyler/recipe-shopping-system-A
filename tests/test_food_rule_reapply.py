import json
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service
from PushShoppingList.services.recipe_extract_service import safe_filename


FOOD_RULES = {
    "require": [],
    "avoid": [
        {
            "label": "no citric acid",
            "terms": ["citric acid"],
        },
    ],
}


def recipe_payload(url, ingredient):
    return {
        "source_url": url,
        "recipe_title": ingredient,
        "ingredients": [
            {
                "ingredient": ingredient,
                "original_text": ingredient,
                "preparation": "",
            },
        ],
    }


def saved_recipe_json(output_dir, url):
    return json.loads((output_dir / f"{safe_filename(url)}.json").read_text(encoding="utf-8"))


def configure_signed_in_user(monkeypatch, tmp_path, client, user_id="food-rules-user"):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [{
            "user_id": user_id,
            "email": "food-rules@example.com",
            "username": "food-rules",
            "notification_topic": "topic",
            "ntfy_topic": "topic",
            "account_status": "active",
        }],
    })

    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_reapply_food_rules_to_recipe_saves_summary(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    recipe_url = "https://example.com/spring-roll"

    with TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        with patch.object(main_routes, "OUTPUT_FOLDER", output_dir), patch.object(
            recipe_edit_service,
            "OUTPUT_FOLDER",
            output_dir,
        ), patch.object(main_routes, "load_food_rules", lambda: FOOD_RULES):
            recipe_edit_service.save_recipe_output(
                recipe_url,
                recipe_payload(recipe_url, "citric acid dipping sauce"),
            )

            with app.test_client() as client:
                configure_signed_in_user(monkeypatch, output_dir, client)
                response = client.post(
                    "/api/recipes/reapply_food_rules",
                    json={"recipe_url": recipe_url},
                )

            assert response.status_code == 200
            data = response.get_json()
            assert data["ok"] is True
            assert data["checked_ingredients"] == 1
            assert data["flagged_ingredients"] == 1
            assert data["needs_review"] is True
            assert "no citric acid" in data["marker"]

            saved = saved_recipe_json(output_dir, recipe_url)
            assert saved["food_rules_last_applied"]["flagged_ingredients"] == 1
            assert saved["food_rules_last_applied_at"].endswith("Z")


def test_reapply_food_rules_to_cookbook_summarizes_all_recipes(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    flagged_url = "https://example.com/spring-roll"
    clean_url = "https://example.com/rice"

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        output_dir = temp_path / "outputs"
        output_dir.mkdir()
        cookbook_path = temp_path / "cookbooks.json"

        with patch.object(main_routes, "OUTPUT_FOLDER", output_dir), patch.object(
            recipe_edit_service,
            "OUTPUT_FOLDER",
            output_dir,
        ), patch.object(cookbook_service, "COOKBOOKS_FILE", cookbook_path), patch.object(
            main_routes,
            "load_food_rules",
            lambda: FOOD_RULES,
        ):
            recipe_edit_service.save_recipe_output(
                flagged_url,
                recipe_payload(flagged_url, "citric acid dipping sauce"),
            )
            recipe_edit_service.save_recipe_output(
                clean_url,
                recipe_payload(clean_url, "white rice"),
            )
            cookbook_service.save_cookbooks({
                "cookbooks": [
                    {
                        "id": "dinner",
                        "name": "Dinner",
                        "recipes": [
                            {"url": flagged_url, "name": "Spring Roll"},
                            {"url": clean_url, "name": "Rice"},
                            {"url": "https://example.com/missing", "name": "Missing"},
                        ],
                    },
                ],
            })

            with app.test_client() as client:
                configure_signed_in_user(monkeypatch, temp_path, client)
                response = client.post("/api/cookbooks/dinner/reapply_food_rules")

            assert response.status_code == 200
            data = response.get_json()
            assert data["ok"] is True
            assert data["checked_recipe_count"] == 2
            assert data["skipped_recipe_count"] == 1
            assert data["flagged_recipe_count"] == 1
            assert data["checked_ingredient_count"] == 2
            assert data["flagged_ingredient_count"] == 1
            assert "Food rules reapplied to 2 recipes in Dinner." in data["summary_message"]


def test_reapply_food_rules_to_current_recipes_summarizes_all_rows(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    flagged_url = "https://example.com/spring-roll"
    clean_url = "https://example.com/rice"
    missing_url = "https://example.com/missing"

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        output_dir = temp_path / "outputs"
        output_dir.mkdir()

        with patch.object(main_routes, "OUTPUT_FOLDER", output_dir), patch.object(
            recipe_edit_service,
            "OUTPUT_FOLDER",
            output_dir,
        ), patch.object(
            main_routes,
            "load_food_rules",
            lambda: FOOD_RULES,
        ), patch.object(
            main_routes,
            "recipe_url_rows",
            lambda: [
                {"url": flagged_url, "name": "Spring Roll"},
                {"url": clean_url, "name": "Rice"},
                {"url": flagged_url, "name": "Spring Roll Duplicate"},
                {"url": missing_url, "name": "Missing"},
            ],
        ):
            recipe_edit_service.save_recipe_output(
                flagged_url,
                recipe_payload(flagged_url, "citric acid dipping sauce"),
            )
            recipe_edit_service.save_recipe_output(
                clean_url,
                recipe_payload(clean_url, "white rice"),
            )

            with app.test_client() as client:
                configure_signed_in_user(monkeypatch, temp_path, client)
                response = client.post("/api/recipes/current/reapply_food_rules")

            assert response.status_code == 200
            data = response.get_json()
            assert data["ok"] is True
            assert data["scope"] == "current_recipes"
            assert data["recipe_count"] == 3
            assert data["checked_recipe_count"] == 2
            assert data["skipped_recipe_count"] == 1
            assert data["flagged_recipe_count"] == 1
            assert data["checked_ingredient_count"] == 2
            assert data["flagged_ingredient_count"] == 1
            assert "Food rules reapplied to 2 recipes in Current Recipes." in data["summary_message"]
