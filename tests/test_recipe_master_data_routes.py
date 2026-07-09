import json
from pathlib import Path

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
                {
                    "user_id": "user-b",
                    "username": "user-b",
                    "email": "user-b@example.com",
                    "first_name": "User",
                    "last_name": "B",
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
                "store_section": "Produce",
            }],
            "equipment": [{"equipment": "Large pot"}],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-soup",
        recipe_data={
            "ingredients": [{"ingredient": "Garlic", "store_section": "Spices & Seasonings"}],
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
        equipment_response = client.get("/admin/master-data/equipment?scope=all")

    all_html = all_response.get_data(as_text=True)
    filtered_html = filtered_response.get_data(as_text=True)
    equipment_html = equipment_response.get_data(as_text=True)
    assert all_response.status_code == 200
    assert "Tomato" in all_html
    assert "Garlic" in all_html
    assert "Run Backfill" in all_html
    assert '<th scope="col">Item</th>' in all_html
    assert '<th scope="col">Normalized Name</th>' not in all_html
    assert '<th scope="col">Image</th>' not in all_html
    assert 'class="master-data-item-cell"' in all_html
    assert 'class="master-data-item-copy"' in all_html
    assert 'data-full-src="/static/generated/tomato.png"' in all_html
    assert all_html.index('class="master-data-thumbnail"') < all_html.index("<strong>Tomato</strong>")
    assert '<th scope="rowgroup" colspan="6">PRODUCE</th>' in all_html
    assert "Backfill progress" in all_html
    assert "data-master-backfill-form" in all_html
    assert "data-master-reference-toggle" in all_html
    assert "data-master-reference-row" in all_html
    assert "Show 1 recipe referencing Tomato" in all_html
    assert "View recipes" not in all_html
    assert "master-data-usage-chevron" not in all_html
    assert "/api/master-data/ingredients/" in all_html
    assert "Generate Missing Images" in all_html
    assert "Store Section" in all_html
    assert 'name="store_section"' in all_html
    assert "data-master-store-section-panel" in all_html
    assert "data-master-store-section-save" in all_html
    assert "data-master-store-section-form" in all_html
    assert 'data-original-store-section="PRODUCE"' in all_html
    assert '<button type="submit">Save</button>' not in all_html
    assert "All sections" in all_html
    assert "PRODUCE" in all_html
    assert "SPICES &amp; SEASONINGS" in all_html
    assert "data-master-image-form" in all_html
    assert "/api/master-data/generate-missing-images" in all_html
    assert "/api/master-data/image-generation-status" in all_html
    assert "/api/master-data/backfill-status" in all_html
    assert "js/master-data.js" in all_html
    assert "User A" in all_html
    assert "user-a@example.com" in all_html
    assert filtered_response.status_code == 200
    assert "Garlic" in filtered_html
    assert "Tomato" not in filtered_html
    assert "User B" in filtered_html
    assert "user-b@example.com" in filtered_html
    assert equipment_response.status_code == 200
    assert '<th scope="col">Item</th>' in equipment_html
    assert '<th scope="col">Equipment Type</th>' in equipment_html
    assert '<th scope="col">Normalized Name</th>' not in equipment_html
    assert '<th scope="col">Image</th>' not in equipment_html
    assert '<th scope="rowgroup" colspan="6">COOKWARE</th>' in equipment_html
    assert '<th scope="rowgroup" colspan="6">PREP TOOLS</th>' in equipment_html
    assert "Generate Missing Images" in equipment_html
    assert "Store Section" not in equipment_html
    assert 'name="store_section"' not in equipment_html
    assert 'name="equipment_section"' in equipment_html
    assert "All types" in equipment_html
    assert "COOKWARE" in equipment_html
    assert "PREP TOOLS" in equipment_html
    assert "data-master-store-section-panel" not in equipment_html
    assert "data-master-image-form" in equipment_html
    assert "Creates equipment thumbnails" in equipment_html
    assert 'name="record_type" value="equipment"' in equipment_html


def test_master_data_reference_api_returns_scoped_recipe_links(monkeypatch, tmp_path):
    app, _db_path, users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    user_a_tomato = master_data.master_record_for_name("ingredients", "user-a", "tomato")
    user_b_garlic = master_data.master_record_for_name("ingredients", "user-b", "garlic")
    metadata_path = users_root / "user-a" / "recipe-extractor" / "data" / "recipe_ingredients.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({
            master_data.recipe_id_for_url("https://example.com/user-a-soup"): {
                "url": "https://example.com/user-a-soup",
                "name": "User A Soup",
                "cover_image": {
                    "path": "data/uploads/recipe_covers/user-a-soup.png",
                    "alt": "User A Soup title image",
                },
            },
        }),
        encoding="utf-8",
    )

    with app.test_client() as client:
        sign_in(client, "admin-user")
        admin_response = client.get(
            f"/api/master-data/ingredients/{user_a_tomato['id']}/references?scope=all",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        sign_in(client, "user-a")
        own_response = client.get(
            f"/api/master-data/ingredients/{user_a_tomato['id']}/references",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        blocked_response = client.get(
            f"/api/master-data/ingredients/{user_b_garlic['id']}/references",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    admin_payload = admin_response.get_json()
    own_payload = own_response.get_json()
    blocked_payload = blocked_response.get_json()

    assert admin_response.status_code == 200
    assert admin_payload["record"]["name"] == "Tomato"
    assert admin_payload["total"] == 1
    assert admin_payload["references"][0]["recipe_title"] == "User A Soup"
    assert admin_payload["references"][0]["recipe_url"] == "https://example.com/user-a-soup"
    assert "/recipe/edit?url=https://example.com/user-a-soup" in admin_payload["references"][0]["edit_url"]
    assert "/recipe_cover_image?url=https://example.com/user-a-soup" in admin_payload["references"][0]["recipe_image_url"]
    assert "/recipe_cover_image?url=https://example.com/user-a-soup" in admin_payload["references"][0]["recipe_image_full_url"]
    assert admin_payload["references"][0]["recipe_image_alt"] == "User A Soup title image"
    assert own_response.status_code == 200
    assert own_payload["record"]["name"] == "Tomato"
    assert blocked_response.status_code == 404
    assert blocked_payload["ok"] is False


def test_ingredient_master_data_filters_and_groups_by_store_section(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with app.test_client() as client:
        sign_in(client, "admin-user")
        all_response = client.get("/admin/master-data/ingredients?scope=all")
        produce_response = client.get("/admin/master-data/ingredients?scope=all&store_section=PRODUCE")

    all_html = all_response.get_data(as_text=True)
    produce_html = produce_response.get_data(as_text=True)

    assert all_response.status_code == 200
    assert '<tr class="master-data-section-row">' in all_html
    assert "PRODUCE" in all_html
    assert "SPICES &amp; SEASONINGS" in all_html
    assert produce_response.status_code == 200
    assert 'value="PRODUCE" selected' in produce_html
    assert "Tomato" in produce_html
    assert "Garlic" not in produce_html
    assert '<tr class="master-data-section-row">' not in produce_html


def test_equipment_master_data_filters_and_groups_by_equipment_type(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with app.test_client() as client:
        sign_in(client, "admin-user")
        all_response = client.get("/admin/master-data/equipment?scope=all")
        cookware_response = client.get("/admin/master-data/equipment?scope=all&equipment_section=COOKWARE")

    all_html = all_response.get_data(as_text=True)
    cookware_html = cookware_response.get_data(as_text=True)

    assert all_response.status_code == 200
    assert '<tr class="master-data-section-row">' in all_html
    assert "COOKWARE" in all_html
    assert "PREP TOOLS" in all_html
    assert cookware_response.status_code == 200
    assert 'value="COOKWARE" selected' in cookware_html
    assert "Large pot" in cookware_html
    assert "Whisk" not in cookware_html
    assert '<tr class="master-data-section-row">' not in cookware_html


def test_ingredient_master_store_section_update_is_user_scoped(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/user-a-tomato",
        recipe_data={"ingredients": [{"ingredient": "Tomato", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-tomato",
        recipe_data={"ingredients": [{"ingredient": "Tomato", "store_section": "Dairy & Eggs"}]},
        user_id="user-b",
    )
    user_a_tomato = master_data.master_record_for_name("ingredients", "user-a", "tomato")
    user_b_tomato = master_data.master_record_for_name("ingredients", "user-b", "tomato")

    with app.test_client() as client:
        sign_in(client, "user-a")
        blocked_response = client.post(
            f"/admin/master-data/ingredients/{user_b_tomato['id']}/store-section",
            data={"store_section": "BAKING"},
        )
        own_response = client.post(
            f"/admin/master-data/ingredients/{user_a_tomato['id']}/store-section",
            data={"store_section": "BAKING"},
        )

    user_a_tomato = master_data.master_record_for_name("ingredients", "user-a", "tomato")
    user_b_tomato = master_data.master_record_for_name("ingredients", "user-b", "tomato")

    assert blocked_response.status_code == 302
    assert own_response.status_code == 302
    assert user_a_tomato["store_section"] == "BAKING"
    assert user_b_tomato["store_section"] == "DAIRY & EGGS"


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


def test_admin_backfill_fetch_response_exposes_progress(monkeypatch, tmp_path):
    app, _db_path, users_root = configure_master_data_app(monkeypatch, tmp_path)
    data_root = users_root / "user-a" / "recipe-extractor" / "data"
    output_root = data_root / "output"
    output_root.mkdir(parents=True)
    recipe_url = "https://example.com/fetch-master-data"
    (data_root / "recipe_ingredients.json").write_text(
        json.dumps({
            recipe_url: {
                "url": recipe_url,
                "name": "Fetch Soup",
                "ingredients": ["Carrot"],
            }
        }),
        encoding="utf-8",
    )
    (output_root / "fetch-master-data.json").write_text(
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
            data={"record_type": "ingredients", "job_id": "test-master-progress"},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        status_response = client.get(
            "/api/master-data/backfill-status?job_id=test-master-progress",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    payload = response.get_json()
    status_payload = status_response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["job_id"] == "test-master-progress"
    assert payload["progress"]["status"] == "complete"
    assert payload["progress"]["recipes_completed"] == 1
    assert payload["progress"]["items"][0]["label"] == "Fetch Soup"
    assert payload["progress"]["items"][0]["state"] == "done"
    assert status_response.status_code == 200
    assert status_payload["progress"]["job_id"] == "test-master-progress"
    assert status_payload["progress"]["ingredient_rows"] == 1


def test_admin_generate_missing_images_route_starts_scoped_job(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    captured = {}

    def fake_start_job(job_id, record_type, user_id, include_all_users=False, search=None):
        captured.update({
            "job_id": job_id,
            "record_type": record_type,
            "user_id": user_id,
            "include_all_users": include_all_users,
            "search": search,
        })
        return {
            "job_id": job_id,
            "status": "running",
            "total": 2,
            "completed": 0,
        }

    monkeypatch.setattr(
        "PushShoppingList.routes.main_routes.recipe_master_images.start_master_image_generation_job",
        fake_start_job,
    )

    with app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.post(
            "/api/master-data/generate-missing-images",
            data={
                "record_type": "ingredients",
                "scope": "user",
                "user_id": "user-a",
                "search": "tom",
                "job_id": "image-job-1",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["progress"]["status"] == "running"
    assert captured == {
        "job_id": "image-job-1",
        "record_type": "ingredients",
        "user_id": "user-a",
        "include_all_users": False,
        "search": "tom",
    }


def test_admin_generate_missing_images_route_respects_selected_scope(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    calls = []

    def fake_start_job(job_id, record_type, user_id, include_all_users=False, search=None):
        calls.append({
            "job_id": job_id,
            "record_type": record_type,
            "user_id": user_id,
            "include_all_users": include_all_users,
            "search": search,
        })
        return {
            "job_id": job_id,
            "status": "running",
            "total": 0,
            "completed": 0,
        }

    monkeypatch.setattr(
        "PushShoppingList.routes.main_routes.recipe_master_images.start_master_image_generation_job",
        fake_start_job,
    )

    with app.test_client() as client:
        sign_in(client, "admin-user")
        mine_response = client.post(
            "/api/master-data/generate-missing-images",
            data={
                "record_type": "ingredients",
                "scope": "mine",
                "user_id": "user-b",
                "search": "mine-search",
                "job_id": "image-job-mine",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        all_response = client.post(
            "/api/master-data/generate-missing-images",
            data={
                "record_type": "ingredients",
                "scope": "all",
                "user_id": "user-b",
                "search": "all-search",
                "job_id": "image-job-all",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        user_response = client.post(
            "/api/master-data/generate-missing-images",
            data={
                "record_type": "ingredients",
                "scope": "user",
                "user_id": "user-b",
                "search": "user-search",
                "job_id": "image-job-user",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    assert mine_response.status_code == 200
    assert all_response.status_code == 200
    assert user_response.status_code == 200
    assert [response.get_json()["scope"] for response in (mine_response, all_response, user_response)] == [
        "mine",
        "all",
        "user",
    ]
    assert calls == [
        {
            "job_id": "image-job-mine",
            "record_type": "ingredients",
            "user_id": "admin-user",
            "include_all_users": False,
            "search": "mine-search",
        },
        {
            "job_id": "image-job-all",
            "record_type": "ingredients",
            "user_id": "",
            "include_all_users": True,
            "search": "all-search",
        },
        {
            "job_id": "image-job-user",
            "record_type": "ingredients",
            "user_id": "user-b",
            "include_all_users": False,
            "search": "user-search",
        },
    ]


def test_admin_generate_missing_images_route_starts_equipment_job(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    captured = {}

    def fake_start_job(job_id, record_type, user_id, include_all_users=False, search=None):
        captured.update({
            "job_id": job_id,
            "record_type": record_type,
            "user_id": user_id,
            "include_all_users": include_all_users,
            "search": search,
        })
        return {
            "job_id": job_id,
            "status": "running",
            "total": 1,
            "completed": 0,
        }

    monkeypatch.setattr(
        "PushShoppingList.routes.main_routes.recipe_master_images.start_master_image_generation_job",
        fake_start_job,
    )

    with app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.post(
            "/api/master-data/generate-missing-images",
            data={
                "record_type": "equipment",
                "scope": "user",
                "user_id": "user-b",
                "search": "pin",
                "job_id": "equipment-image-job-1",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["scope"] == "user"
    assert captured == {
        "job_id": "equipment-image-job-1",
        "record_type": "equipment",
        "user_id": "user-b",
        "include_all_users": False,
        "search": "pin",
    }


def test_master_data_image_generation_syncs_visible_filter_scope():
    script = Path("PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")

    assert "function syncImageFormFromFilters(form)" in script
    assert 'const scope = text(formData.get("scope") || "mine").trim() || "mine";' in script
    assert 'const userId = scope === "user" ? text(formData.get("user_id")).trim() : "";' in script
    assert 'setNamedFormValue(form, "scope", scope);' in script
    assert 'setNamedFormValue(form, "user_id", userId);' in script
    assert 'setNamedFormValue(form, "redirect_url", redirectUrl);' in script
    assert "syncImageFormFromFilters(form);" in script


def test_master_data_user_filter_aligns_with_filter_row():
    template = Path("PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    user_field_start = template.index('class="master-data-user-filter-field"')
    user_field_end = template.index("</label>", user_field_start)
    user_note_start = template.index('class="master-data-user-field-note master-data-user-filter-note"')

    assert user_field_end < user_note_start
    assert 'aria-describedby="masterDataUserHint"' in template[user_field_start:user_field_end]
    assert ".master-data-filter-form .master-data-user-filter-note" in css
    assert "grid-column: 3 / 4;" in css
    assert "grid-row: 2;" in css
    assert "grid-column: auto;" in css
    assert "grid-row: auto;" in css


def test_master_data_store_section_batch_save_is_wired():
    template = Path("PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "data-master-store-section-panel" in template
    assert "data-master-store-section-summary" in template
    assert "data-master-store-section-detail" in template
    assert "data-master-store-section-save" in template
    assert "data-master-store-section-form" in template
    assert "data-original-store-section" in template
    assert '<button type="submit">Save</button>' not in template

    assert "function initMasterDataStoreSectionBatchSave" in script
    assert "function changedStoreSectionForms" in script
    assert "function saveChangedStoreSections" in script
    assert "function submitStoreSectionForm" in script
    assert "initMasterDataStoreSectionBatchSave();" in script
    assert '"X-Requested-With": "fetch"' in script
    assert "window.location.assign(window.location.href)" in script

    assert ".master-data-store-section-save-panel" in css
    assert ".master-data-store-section-save-panel.has-changes" in css
    assert ".master-data-record-row-dirty td" in css
    assert ".master-data-store-section-form {\n            display: block;" in css


def test_master_data_reference_expander_is_wired():
    template = Path("PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert '<th scope="col">Item</th>' in template
    assert '<th scope="col">Normalized Name</th>' not in template
    assert '<th scope="col">Image</th>' not in template
    assert "master-data-item-cell" in template
    assert "master-data-item-copy" in template
    assert "data-master-reference-toggle" in template
    assert "data-master-reference-row" in template
    assert "master_data_record_references_route" in template
    assert "aria-expanded=\"false\"" in template
    assert "aria-label=\"Show {{ row.usage_count }} recipe" in template
    assert "View recipes" not in template
    assert "master-data-usage-chevron" not in template
    assert "data-reference-url" in template
    assert "js/master-data.js" in template
    assert "data-master-thumbnail-size-controls" in template
    assert "data-master-thumbnail-size-decrease" in template
    assert "data-master-thumbnail-size-increase" in template
    assert "data-master-thumbnail-size-value>64px" in template
    assert "data-full-src=\"{{ row.image_url }}\"" in template

    assert "function toggleReferenceRow" in script
    assert "function renderReferences" in script
    assert "[data-master-reference-toggle]" in script
    assert "data-master-reference-panel" in script
    assert "recipe_image_url" in script
    assert "recipe_image_full_url" in script
    assert "recipe_image_srcset" in script
    assert "master-data-reference-title-image" in script
    assert "master-data-reference-copy" in script
    assert "has-title-image" in script
    assert "Open Recipe" in script
    assert "function ensureMasterDataImageLightbox" in script
    assert "function openMasterDataImageLightbox" in script
    assert "function closeMasterDataImageLightbox" in script
    assert "masterDataLightboxImageSelector" in script
    assert "image-lightbox-open" in script
    assert 'MASTER_DATA_THUMBNAIL_SIZE_STORAGE_KEY = "master-data-thumbnail-size"' in script
    assert "function applyMasterDataThumbnailSize" in script
    assert 'document.documentElement.style.setProperty("--master-data-thumbnail-size"' in script
    assert "updateReferenceImageSizes" in script

    assert ".master-data-usage-button" in css
    assert ".master-data-usage-button span:nth-child" not in css
    assert ".master-data-usage-chevron" not in css
    assert ".master-data-reference-row[hidden]" in css
    assert ".master-data-reference-panel" in css
    assert ".master-data-reference-title-row" in css
    assert ".master-data-reference-title-row.has-title-image" in css
    assert ".master-data-reference-title-image" in css
    assert ".master-data-reference-copy" in css
    assert ".master-data-reference-item" in css
    assert ".master-data-item" in css
    assert ".master-data-item-copy" in css
    assert "grid-template-columns: var(--master-data-thumbnail-slot, 66px) minmax(0, 1fr);" in css
    assert ".master-data-thumbnail[src]" in css
    assert "--master-data-thumbnail-size: 64px;" in css
    assert "width: var(--master-data-thumbnail-size, 64px);" in css
    assert "height: var(--master-data-thumbnail-size, 64px);" in css


def test_admin_image_generation_status_route_returns_progress(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)

    monkeypatch.setattr(
        "PushShoppingList.routes.main_routes.recipe_master_images.master_image_progress",
        lambda job_id: {"job_id": job_id, "status": "complete", "generated": 3},
    )

    with app.test_client() as client:
        sign_in(client, "admin-user")
        response = client.get(
            "/api/master-data/image-generation-status?job_id=image-job-1",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["progress"] == {
        "job_id": "image-job-1",
        "status": "complete",
        "generated": 3,
    }


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
