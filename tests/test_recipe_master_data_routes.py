import json

from PushShoppingList.app import create_app
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def configure_master_data_app(monkeypatch, tmp_path):
    db_path = tmp_path / "recipe_master.sqlite3"
    users_file = tmp_path / "users.json"
    users_root = tmp_path / "users"

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
                },
            ]
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", users_root)
    monkeypatch.setattr(user_account_service, "USERS_FILE", users_file)
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")

    app = create_app()
    app.config.update(TESTING=True)
    return app, db_path, users_root


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def seed_master_records():
    master_data.sync_recipe_master_records(
        "https://example.com/user-a-soup",
        recipe_data={
            "ingredients": [{
                "ingredient": "Tomato",
                "ingredient_image_url": "/static/generated/tomato.png",
            }],
            "equipment": [{"equipment": "Large pot"}],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-soup",
        recipe_data={
            "ingredients": [{"ingredient": "Garlic"}],
            "equipment": [{"equipment": "Whisk"}],
        },
        user_id="user-b",
    )


def test_master_data_page_does_not_create_missing_database(monkeypatch, tmp_path):
    app, db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/ingredients")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Ingredient Master Data" in html
    assert "Normalized recipe master database has not been created yet" in html
    assert str(db_path) in html
    assert "Missing" in html
    assert not db_path.exists()


def test_master_data_pages_scope_normal_users_to_their_records(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with app.test_client() as client:
        sign_in(client, "user-a")
        ingredient_response = client.get("/admin/master-data/ingredients?scope=all&user_id=user-b")
        equipment_response = client.get("/admin/master-data/equipment")

    ingredient_html = ingredient_response.get_data(as_text=True)
    equipment_html = equipment_response.get_data(as_text=True)
    assert ingredient_response.status_code == 200
    assert "Tomato" in ingredient_html
    assert "tomato" in ingredient_html
    assert "/static/generated/tomato.png" in ingredient_html
    assert "Garlic" not in ingredient_html
    assert "user-b" not in ingredient_html
    assert equipment_response.status_code == 200
    assert "Large pot" in equipment_html
    assert "Whisk" not in equipment_html


def test_admin_master_data_page_can_filter_by_user_id(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with app.test_client() as client:
        sign_in(client, "admin-user")
        all_response = client.get("/admin/master-data/ingredients?scope=all")
        filtered_response = client.get("/admin/master-data/ingredients?user_id=user-b")

    all_html = all_response.get_data(as_text=True)
    filtered_html = filtered_response.get_data(as_text=True)
    assert all_response.status_code == 200
    assert "Tomato" in all_html
    assert "Garlic" in all_html
    assert "Run Backfill" in all_html
    assert filtered_response.status_code == 200
    assert "Garlic" in filtered_html
    assert "Tomato" not in filtered_html


def test_admin_backfill_route_uses_existing_service(monkeypatch, tmp_path):
    app, db_path, users_root = configure_master_data_app(monkeypatch, tmp_path)
    data_root = users_root / "user-a" / "recipe-extractor" / "data"
    output_root = data_root / "output"
    output_root.mkdir(parents=True)
    recipe_url = "https://example.com/backfill-master-data"
    (data_root / "recipe_ingredients.json").write_text(
        json.dumps({
            recipe_url: {
                "url": recipe_url,
                "ingredients": ["Carrot"],
            }
        }),
        encoding="utf-8",
    )
    (output_root / "backfill-master-data.json").write_text(
        json.dumps({
            "source_url": recipe_url,
            "ingredients": [{"ingredient": "Carrot"}],
            "equipment": [{"equipment": "Sheet pan"}],
        }),
        encoding="utf-8",
    )

    with app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.post(
            "/admin/master-data/backfill",
            data={"record_type": "equipment", "include_legacy": "1"},
            follow_redirects=True,
        )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Backfill finished" in html
    assert db_path.exists()
    assert master_data.list_equipment(user_id="user-a")[0]["name"] == "Sheet pan"


def test_account_menu_links_to_master_data_pages(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Ingredient Master Data" in html
    assert "Equipment Master Data" in html
    assert "/admin/master-data/ingredients" in html
    assert "/admin/master-data/equipment" in html
