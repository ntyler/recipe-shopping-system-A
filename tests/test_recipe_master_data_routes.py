import json
from pathlib import Path

from PushShoppingList.app import create_app
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import ingredient_duplicate_review_service as duplicate_reviews
from PushShoppingList.services import ingredient_store_section_review_service as store_section_reviews
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
            "ingredients": [{
                "ingredient": "Garlic",
                "store_section": "Spices & Seasonings",
                "store_section_source": "manual",
                "store_section_user_confirmed": True,
                "store_section_save_to_master": True,
            }],
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


def test_misc_reclassification_route_requires_previewable_unconfirmed_rows(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/ginger",
        recipe_data={"ingredients": [{"ingredient": "Ground ginger", "store_section": "MISC"}]},
        user_id="user-a",
    )
    ground = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            "UPDATE ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE id = ?",
            (ground["id"],),
        )

    with app.test_client() as client:
        sign_in(client, "user-a")
        preview_response = client.post(
            "/api/master-data/ingredients/reclassify-misc",
            json={"apply": False},
        )
        apply_response = client.post(
            "/api/master-data/ingredients/reclassify-misc",
            json={"apply": True},
        )

    preview = preview_response.get_json()
    applied = apply_response.get_json()
    assert preview_response.status_code == 200
    assert preview["applied"] is False
    assert preview["changes"][0]["proposed_store_section"] == "SPICES & SEASONINGS"
    assert apply_response.status_code == 200
    assert applied["applied"] is True
    assert master_data.master_record_for_name(
        "ingredients",
        "user-a",
        "ground ginger",
    )["store_section"] == "SPICES & SEASONINGS"


def test_misc_reclassification_ai_second_opinion_route_is_user_scoped(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    captured = {}

    def fake_review(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "scope": kwargs["scope"],
            "opinion_count": 1,
            "opinions": [{
                "ingredient_id": 12,
                "store_section": "SPICES & SEASONINGS",
                "agreement": "agree",
            }],
        }

    monkeypatch.setattr(
        store_section_reviews,
        "review_misc_ingredient_store_sections_with_ai",
        fake_review,
    )
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            "/api/master-data/ingredients/reclassify-misc/ai-second-opinion",
            json={"scope": "unresolved", "ingredient_ids": [12]},
        )

    assert response.status_code == 200
    assert response.get_json()["opinions"][0]["agreement"] == "agree"
    assert captured == {
        "user_id": "user-a",
        "scope": "unresolved",
        "ingredient_ids": [12],
    }


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
    assert all_html.index('class="master-data-thumbnail"') < all_html.index('value="Tomato"')
    assert '<th scope="rowgroup" colspan="6">PRODUCE</th>' in all_html
    assert "Backfill progress" in all_html
    assert "data-master-backfill-form" in all_html
    assert "data-master-reference-toggle" in all_html
    assert "data-master-reference-row" in all_html
    assert 'data-reference-url="/api/master-data/ingredients/0/references"' in all_html
    assert "data-master-duplicate-reference-dialog" in all_html
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
    assert "Reclassify unconfirmed Misc ingredients" in all_html
    assert "data-master-misc-reclassification" in all_html
    assert "Store-section maintenance" in all_html
    assert "data-master-misc-reclassification-preview-panel" in all_html
    assert "data-master-misc-reclassification-count" in all_html
    assert "data-master-misc-reclassification-empty" in all_html
    assert "Get AI Second Opinions" in all_html
    assert "AI second opinion" in all_html
    assert "Final decision" in all_html
    assert "data-ai-second-opinion-url" in all_html
    assert "Apply Changes" in all_html
    assert "/api/master-data/ingredients/reclassify-misc" in all_html
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
    assert "data-master-misc-reclassification" not in equipment_html
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


def test_misc_reclassification_preview_uses_dedicated_responsive_ui():
    root = Path(__file__).resolve().parents[1]
    script = (root / "PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = (root / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "function friendlyIngredientStoreSection(value)" in script
    assert '"SPICES & SEASONINGS": "Spices"' in script
    assert '"CANNED": "Canned Goods"' in script
    assert "Classification details" in script
    assert "MISC_REVIEW_STORE_SECTIONS" in script
    assert "requestMiscAiSecondOpinions" in script
    assert "miscReviewDecisionPayload" in script
    assert "AI review is optional and never changes the final decision automatically." in script
    assert ".master-data-misc-reclassification-header" in css
    assert ".master-data-misc-reclassification-list" in css
    assert ".master-data-section-pill.is-proposed" in css
    assert ".master-data-misc-reclassification-actions" in css
    assert ".master-data-misc-ai-status" in css
    assert ".master-data-misc-decision" in css


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


def test_ingredient_master_options_are_scoped_for_recipe_editor(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/api/master-data/ingredients/options?search=tom&limit=10",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["manage_url"] == "/admin/master-data/ingredients"
    assert payload["ingredients"] == [{
        "ingredient_id": payload["ingredients"][0]["ingredient_id"],
        "name": "Tomato",
        "normalized_name": "tomato",
        "store_section": "PRODUCE",
        "image_url": "/static/generated/tomato.png",
        "usage_count": 1,
        "aliases": [],
    }]


def test_ingredient_master_merge_routes_scope_candidates_and_resolve_aliases(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/potato-soup",
        recipe_data={"ingredients": [{"ingredient": "Potato", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/roasted-potatoes",
        recipe_data={"ingredients": [{"ingredient": "Potatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-potato",
        recipe_data={"ingredients": [{"ingredient": "Potato", "store_section": "Produce"}]},
        user_id="user-b",
    )
    target = master_data.master_record_for_name("ingredients", "user-a", "potato")
    source = master_data.master_record_for_name("ingredients", "user-a", "potatoes")
    user_b_potato = master_data.master_record_for_name("ingredients", "user-b", "potato")
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        options_response = client.get(
            f"/api/master-data/ingredients/{source['id']}/merge-options?search=potato",
            headers=headers,
        )
        blocked_options_response = client.get(
            f"/api/master-data/ingredients/{user_b_potato['id']}/merge-options",
            headers=headers,
        )
        merge_response = client.post(
            f"/admin/master-data/ingredients/{source['id']}/merge",
            data={
                "target_ingredient_id": target["id"],
                "redirect_url": "/admin/master-data/ingredients?search=potato",
            },
            headers=headers,
        )
        picker_response = client.get(
            "/api/master-data/ingredients/options?search=potatoes&limit=10",
            headers=headers,
        )
        page_response = client.get("/admin/master-data/ingredients?search=potatoes")

    options_payload = options_response.get_json()
    merge_payload = merge_response.get_json()
    picker_payload = picker_response.get_json()
    page_html = page_response.get_data(as_text=True)

    assert options_response.status_code == 200
    assert options_payload["source"]["ingredient_id"] == source["id"]
    assert [row["ingredient_id"] for row in options_payload["ingredients"]] == [target["id"]]
    assert blocked_options_response.status_code == 404
    assert merge_response.status_code == 200
    assert merge_payload["result"]["target_ingredient_id"] == target["id"]
    assert merge_payload["result"]["moved_reference_count"] == 1
    assert merge_payload["redirect_url"] == "/admin/master-data/ingredients?search=potato"
    assert picker_response.status_code == 200
    assert [row["name"] for row in picker_payload["ingredients"]] == ["Potato"]
    assert picker_payload["ingredients"][0]["usage_count"] == 2
    assert picker_payload["ingredients"][0]["aliases"] == ["Potatoes"]
    assert page_response.status_code == 200
    assert "Potato" in page_html
    assert "Potatoes" in page_html


def test_ingredient_master_merge_undo_route_and_button_restore_last_merge(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/carrot-soup",
        recipe_data={"ingredients": [{"ingredient": "Carrot", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/roasted-carrots",
        recipe_data={"ingredients": [{"ingredient": "Carrots", "store_section": "Produce"}]},
        user_id="user-a",
    )
    target = master_data.master_record_for_name("ingredients", "user-a", "carrot")
    source = master_data.master_record_for_name("ingredients", "user-a", "carrots")
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        merge_response = client.post(
            f"/admin/master-data/ingredients/{source['id']}/merge",
            data={"target_ingredient_id": target["id"]},
            headers=headers,
        )
        merged_page = client.get("/admin/master-data/ingredients")
        preview_response = client.get(
            "/api/master-data/ingredients/merges/undo-preview?scope=mine",
            headers=headers,
        )
        preview_payload = preview_response.get_json()
        undo_response = client.post(
            "/api/master-data/ingredients/merges/undo",
            json={
                "scope": "user",
                "user_id": "user-b",
                "merge_id": preview_payload["merge"]["merge_id"],
            },
            headers=headers,
        )
        restored_page = client.get("/admin/master-data/ingredients")

    merged_html = merged_page.get_data(as_text=True)
    undo_payload = undo_response.get_json()
    restored_html = restored_page.get_data(as_text=True)

    assert merge_response.status_code == 200
    assert 'data-master-duplicate-undo-merge' in merged_html
    assert 'data-undo-available="true"' in merged_html
    assert 'data-source-name="Carrots"' in merged_html
    assert 'data-target-name="Carrot"' in merged_html
    assert "Last merge: Carrots into Carrot." in merged_html
    assert preview_response.status_code == 200
    assert preview_payload["merge"]["source_restore"]["name"] == "Carrots"
    assert preview_payload["merge"]["target_restore"]["name"] == "Carrot"
    assert preview_payload["merge"]["restored_reference_count"] == 1
    assert preview_payload["merge"]["older_undo_count"] == 0
    assert preview_payload["merge"]["can_undo_now"] is True
    assert len(preview_payload["merges"]) == 1
    assert preview_payload["merges"][0]["is_next_undo"] is True
    assert preview_payload["merges"][0]["can_undo_now"] is True
    assert undo_response.status_code == 200
    assert undo_payload["ok"] is True
    assert undo_payload["source_name"] == "Carrots"
    assert undo_payload["target_name"] == "Carrot"
    assert undo_payload["restored_reference_count"] == 1
    assert undo_payload["undo_available"] is False
    assert master_data.master_record_for_name("ingredients", "user-a", "carrot")["id"] == target["id"]
    assert master_data.master_record_for_name("ingredients", "user-a", "carrots")["id"] == source["id"]
    assert 'data-undo-available="false"' in restored_html
    assert "No merge is currently available to undo." in restored_html


def test_duplicate_review_routes_scan_scope_and_save_decisions(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for user_id in ("user-a", "user-b"):
        master_data.sync_recipe_master_records(
            f"https://example.com/{user_id}/potato",
            recipe_data={"ingredients": [{"ingredient": "Potato", "store_section": "Produce"}]},
            user_id=user_id,
        )
        master_data.sync_recipe_master_records(
            f"https://example.com/{user_id}/potatoes",
            recipe_data={"ingredients": [{"ingredient": "Potatoes", "store_section": "Produce"}]},
            user_id=user_id,
        )
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        scan_response = client.post(
            "/api/master-data/ingredients/duplicate-scan",
            json={"scope": "user", "user_id": "user-b"},
            headers=headers,
        )
        scan_payload = scan_response.get_json()
        review_id = scan_payload["reviews"][0]["review_id"]
        decision_response = client.post(
            f"/api/master-data/ingredients/duplicate-reviews/{review_id}/decision",
            json={"action": "related"},
            headers=headers,
        )
        list_response = client.get(
            "/api/master-data/ingredients/duplicate-reviews?user_id=user-b",
            headers=headers,
        )
        sign_in(client, "admin-user")
        all_scope_response = client.post(
            "/api/master-data/ingredients/duplicate-scan",
            json={"scope": "all"},
            headers=headers,
        )
        user_b_response = client.post(
            "/api/master-data/ingredients/duplicate-scan",
            json={"scope": "user", "user_id": "user-b"},
            headers=headers,
        )

    assert scan_response.status_code == 200
    assert scan_payload["user_id"] == "user-a"
    assert scan_payload["review_count"] == 1
    assert scan_payload["scan"]["review_count"] == 1
    assert scan_payload["scan"]["scanned_at"]
    assert decision_response.status_code == 200
    assert decision_response.get_json()["status"] == "related"
    assert list_response.status_code == 200
    assert list_response.get_json()["user_id"] == "user-a"
    assert list_response.get_json()["review_count"] == 0
    assert list_response.get_json()["scan"]["scanned_at"] == scan_payload["scan"]["scanned_at"]
    assert all_scope_response.status_code == 400
    assert user_b_response.status_code == 200
    assert user_b_response.get_json()["user_id"] == "user-b"
    assert user_b_response.get_json()["review_count"] == 1


def test_duplicate_review_history_route_restores_decision_to_queue(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in ("Potato", "Potatoes"):
        master_data.sync_recipe_master_records(
            f"https://example.com/{name.lower()}",
            recipe_data={"ingredients": [{"ingredient": name, "store_section": "Produce"}]},
            user_id="user-a",
        )
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        scan = client.post(
            "/api/master-data/ingredients/duplicate-scan",
            json={"scope": "mine"},
            headers=headers,
        ).get_json()
        review_id = scan["reviews"][0]["review_id"]
        decision_response = client.post(
            f"/api/master-data/ingredients/duplicate-reviews/{review_id}/decision",
            json={"action": "related"},
            headers=headers,
        )
        history_response = client.get(
            "/api/master-data/ingredients/duplicate-reviews/history?scope=mine",
            headers=headers,
        )
        restore_response = client.post(
            f"/api/master-data/ingredients/duplicate-reviews/{review_id}/restore",
            json={"scope": "mine"},
            headers=headers,
        )
        pending_response = client.get(
            "/api/master-data/ingredients/duplicate-reviews?scope=mine",
            headers=headers,
        )

    history_payload = history_response.get_json()
    restore_payload = restore_response.get_json()
    pending_payload = pending_response.get_json()
    assert decision_response.status_code == 200
    assert history_response.status_code == 200
    assert history_payload["decision_count"] == 1
    assert history_payload["decisions"][0]["decision"] == "related"
    assert history_payload["decisions"][0]["can_restore"] is True
    assert restore_response.status_code == 200
    assert restore_payload["success"] is True
    assert "duplicate review queue" in restore_payload["message"]
    assert pending_payload["review_count"] == 1
    assert pending_payload["reviews"][0]["review_id"] == review_id


def test_duplicate_review_ai_second_opinion_route_generates_independent_notes(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in ("Potato", "Potatoes"):
        master_data.sync_recipe_master_records(
            f"https://example.com/{name.lower().replace(' ', '-')}",
            recipe_data={"ingredients": [{"ingredient": name, "store_section": "Produce"}]},
            user_id="user-a",
        )
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        scan = client.post(
            "/api/master-data/ingredients/duplicate-scan",
            json={"scope": "mine"},
            headers=headers,
        ).get_json()
        review = scan["reviews"][0]
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        def fake_second_opinions(candidates, user_id=None):
            return [{
                "pair_key": candidates[0]["pair_key"],
                "verdict": "merge",
                "confidence": 0.96,
                "suggested_target_id": int(candidates[0]["left"]["id"]),
                "evidence": ["The names differ only by singular and plural form."],
                "warnings": [],
            }]

        monkeypatch.setattr(
            duplicate_reviews,
            "request_ai_second_opinions",
            fake_second_opinions,
        )
        response = client.post(
            f"/api/master-data/ingredients/duplicate-reviews/{review['review_id']}/ai-second-opinion",
            json={"force": False},
            headers=headers,
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["ai_second_opinion"]["status"] == "ready"
    assert payload["ai_second_opinion"]["verdict"] == "merge"
    assert payload["ai_second_opinion"]["agreement"] == "agree"
    assert payload["ai_second_opinion"]["evidence"] == [
        "The names differ only by singular and plural form."
    ]


def test_duplicate_review_bulk_route_applies_selected_cards(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for singular, plural in (("Potato", "Potatoes"), ("Tomato", "Tomatoes")):
        master_data.sync_recipe_master_records(
            f"https://example.com/{singular.lower()}",
            recipe_data={"ingredients": [{"ingredient": singular, "store_section": "Produce"}]},
            user_id="user-a",
        )
        master_data.sync_recipe_master_records(
            f"https://example.com/{plural.lower()}",
            recipe_data={"ingredients": [{"ingredient": plural, "store_section": "Produce"}]},
            user_id="user-a",
        )
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        scan = client.post(
            "/api/master-data/ingredients/duplicate-scan",
            json={"scope": "mine"},
            headers=headers,
        ).get_json()
        response = client.post(
            "/api/master-data/ingredients/duplicate-reviews/bulk-decision",
            json={
                "decisions": [
                    {"review_id": review["review_id"], "action": "not_duplicate"}
                    for review in scan["reviews"]
                    if review["signals"].get("singular_exact")
                ]
            },
            headers=headers,
        )
        remaining = client.get(
            "/api/master-data/ingredients/duplicate-reviews",
            headers=headers,
        ).get_json()

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["complete"] is True
    assert payload["succeeded_count"] == 2
    assert payload["failed_count"] == 0
    assert remaining["review_count"] == len(scan["reviews"]) - 2


def test_ingredient_master_record_edit_is_scoped_and_admin_can_edit_other_users(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    user_a_tomato = master_data.master_record_for_name("ingredients", "user-a", "tomato")
    user_b_garlic = master_data.master_record_for_name("ingredients", "user-b", "garlic")
    headers = {"X-Requested-With": "fetch", "Accept": "application/json"}

    with app.test_client() as client:
        sign_in(client, "user-a")
        own_response = client.post(
            f"/admin/master-data/ingredients/{user_a_tomato['id']}",
            data={
                "name": "Roma Tomato",
                "normalized_name": "roma tomato",
                "store_section": "PRODUCE",
            },
            headers=headers,
        )
        blocked_response = client.post(
            f"/admin/master-data/ingredients/{user_b_garlic['id']}",
            data={
                "name": "Fresh Garlic",
                "normalized_name": "fresh garlic",
                "store_section": "PRODUCE",
            },
            headers=headers,
        )
        sign_in(client, "admin-user")
        admin_response = client.post(
            f"/admin/master-data/ingredients/{user_b_garlic['id']}",
            data={
                "name": "Fresh Garlic",
                "normalized_name": "fresh garlic",
                "store_section": "PRODUCE",
            },
            headers=headers,
        )

    assert own_response.status_code == 200
    assert own_response.get_json()["result"]["normalized_name"] == "roma tomato"
    assert blocked_response.status_code == 404
    assert admin_response.status_code == 200
    assert master_data.master_record_for_name("ingredients", "user-a", "roma tomato")["name"] == "Roma Tomato"
    assert master_data.master_record_for_name("ingredients", "user-b", "fresh garlic")["name"] == "Fresh Garlic"


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
    assert "data-master-record-form" in template
    assert "data-master-record-field" in template
    assert 'name="name"' in template
    assert 'name="normalized_name"' in template
    assert "update_ingredient_master_record_route" in template
    assert '<button type="submit">Save</button>' not in template

    assert "function initMasterDataStoreSectionBatchSave" in script
    assert "function changedStoreSectionForms" in script
    assert "function saveChangedStoreSections" in script
    assert "function submitStoreSectionForm" in script
    assert "function masterDataRecordFields" in script
    assert "currentMasterRecordFieldValue(field) !== originalMasterRecordFieldValue(field)" in script
    assert "initMasterDataStoreSectionBatchSave();" in script
    assert '"X-Requested-With": "fetch"' in script
    assert "window.location.assign(window.location.href)" in script

    assert ".master-data-store-section-save-panel" in css
    assert ".master-data-store-section-save-panel.has-changes" in css
    assert ".master-data-record-row-dirty td" in css
    assert ".master-data-store-section-form {\n            display: block;" in css
    assert ".master-data-record-field input" in css
    assert "border: 1px solid transparent;" in css
    assert "background: transparent;" in css
    assert ".master-data-record-field input:is(:hover, :focus-visible)" in css
    assert ".master-data-record-field input:focus-visible" in css
    assert '.master-data-ingredients-table select[name="store_section"]' in css


def test_master_data_ingredient_merge_ui_is_wired():
    template = Path("PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    for marker in (
        "data-master-merge-open",
        "data-master-merge-dialog",
        "data-master-merge-form",
        "data-master-merge-search",
        "data-master-merge-results",
        "data-master-merge-target-id",
        "data-master-merge-submit",
        "ingredient_master_merge_options_route",
        "merge_ingredient_master_record_route",
    ):
        assert marker in template
    assert "The duplicate name will remain as an alias" in template
    assert "function openMasterDataMergeDialog(button)" in script
    assert "async function loadMasterDataMergeOptions(options = {})" in script
    assert "async function submitMasterDataMerge(event)" in script
    assert "initMasterDataIngredientMerge();" in script
    assert 'const INGREDIENT_MASTER_DATA_VERSION_STORAGE_KEY = "ingredient-master-data-version";' in script
    assert "window.localStorage.setItem(" in script
    assert ".master-data-merge-dialog" in css
    assert ".master-data-merge-option[aria-selected=\"true\"]" in css
    assert ".master-data-aliases" in css


def test_master_data_duplicate_review_ui_is_wired():
    template = Path("PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    for marker in (
        "data-master-duplicate-review",
        "data-master-duplicate-scan",
        "data-master-duplicate-status",
        "data-master-duplicate-list",
        "data-ai-second-opinion-url",
        "ingredient_duplicate_scan_url",
        "ingredient_duplicate_reviews_url",
        "ingredient_duplicate_review_history_url",
        "ingredient_duplicate_decision_url",
        "ingredient_duplicate_restore_decision_url",
        "ingredient_duplicate_ai_second_opinion_url",
        "ingredient_duplicate_bulk_decision_url",
        "ingredient_merge_undo_url",
        "data-master-duplicate-toolbar",
        "data-master-duplicate-select-high-confidence",
        "data-master-duplicate-select-all",
        "data-master-duplicate-select-none",
        "data-master-duplicate-bulk-action",
        "master-data-duplicate-scan-actions",
        "data-master-duplicate-reference-dialog",
        "data-master-duplicate-reference-body",
        "data-master-duplicate-reference-column",
        "data-master-duplicate-reference-pair-name",
        "ingredient_reference_url",
        "data-master-record-results",
        "data-master-results-header",
        "data-master-pagination",
        "data-master-duplicate-undo-merge",
        "data-master-duplicate-toolbar-scan",
        "data-master-duplicate-toolbar-undo-merge",
        "data-master-duplicate-review-history",
        "data-master-duplicate-toolbar-review-history",
        "data-master-duplicate-undo-summary",
        "data-master-undo-dialog",
        "data-master-undo-preview-confirm",
        "data-master-undo-preview-impact",
        "data-master-undo-preview-references",
        "data-master-undo-history-list",
        "data-master-undo-history-count",
        "data-master-undo-preview-position",
        "ingredient_merge_undo_preview_url",
        "data-master-review-history-dialog",
        "data-master-review-history-list",
        "data-master-review-history-status",
    ):
        assert marker in template
    assert "Find Potential Duplicates" in template
    assert "an independent AI second opinion explains each pair" in template
    assert "function masterDataDuplicateCard(review)" in script
    duplicate_card_block = script[
        script.index("function masterDataDuplicateCard(review)"):
        script.index("function renderMasterDataDuplicateReviews(reviews)")
    ]
    assert "actions.append(mergeSuggested, mergeAlternate, related, notDuplicate);" in duplicate_card_block
    assert 'if (review.classification === "related")' not in duplicate_card_block
    assert 'else if (review.classification === "different")' not in duplicate_card_block
    assert "function setMasterDataDuplicateSuggestedSurvivor(button)" in script
    assert "async function scanMasterDataDuplicates()" in script
    assert "function updateMasterDataDuplicateScanState(scan)" in script
    assert "Rescan Potential Duplicates" in script
    assert "Last scanned" in script
    assert "async function decideMasterDataDuplicate(button)" in script
    assert "function masterDataAiSecondOpinionPanel(review)" in script
    assert "function renderMasterDataAiSecondOpinion(panel, opinion)" in script
    assert "async function generateMasterDataAiSecondOpinion(button)" in script
    assert "data-master-duplicate-ai-second-opinion" in script
    assert "async function applyMasterDataDuplicateBulkAction(button)" in script
    assert "function updateMasterDataDuplicateSelectionState()" in script
    assert "function masterDataDuplicateReferenceUrl(ingredientId)" in script
    assert "function masterDataDuplicateReferenceRecord(button, side)" in script
    assert "function renderMasterDataDuplicateReferenceColumn(column, data)" in script
    assert "async function loadMasterDataDuplicateReferenceColumn(column, record, requestId)" in script
    assert "async function openMasterDataDuplicateReferences(button)" in script
    assert "function closeMasterDataDuplicateReferences()" in script
    assert "function refreshMasterDataRecordResults()" in script
    assert "async function refreshAfterMasterDataDuplicateMerge(message, kind = \"\", merge = null)" in script
    assert "function setMasterDataUndoMergeState(merge = null)" in script
    assert "async function undoLastMasterDataIngredientMerge()" in script
    assert "async function openMasterDataUndoPreview()" in script
    assert "async function loadMasterDataUndoPreview(mergeId = 0)" in script
    assert "function renderMasterDataUndoHistory(merges, selectedMergeId)" in script
    assert "function masterDataUndoHistoryDateInfo(value)" in script
    assert "function masterDataUndoHistoryItem(merge, selectedMergeId)" in script
    assert "function masterDataReviewHistoryElements()" in script
    assert "async function openMasterDataReviewHistory()" in script
    assert "async function restoreMasterDataDuplicateDecision(button)" in script
    assert "function setMasterDataDuplicateStatusWithUndo(message, reviewId)" in script
    assert "master-data-duplicate-status-undo" in script
    assert "masterDataUndoCollapsedDateGroups" in script
    assert 'document.createElement("details")' in script
    assert 'date.toLocaleDateString([], {' in script
    assert 'date.toLocaleTimeString([], {' in script
    assert '(newerCount ? "Safe" : "Next")' in script
    assert '"Newest merge — undo next"' in script
    assert "undoLastMasterDataIngredientMerge()" in script
    undo_start = script.index("async function undoLastMasterDataIngredientMerge()")
    undo_end = script.index("function duplicateClassificationLabel", undo_start)
    undo_block = script[undo_start:undo_end]
    assert 'await refreshAfterMasterDataDuplicateMerge(' in undo_block
    assert 'data.message || "Ingredient merge undone."' in undo_block
    assert "merge_id: Number(preview.merge_id)" in undo_block
    assert "preview.can_undo_now === false" in undo_block
    assert "window.location.reload();" not in undo_block
    assert "data-master-duplicate-references-open" in script
    assert 'url.searchParams.set("limit", "500")' in script
    assert 'card.dataset.highConfidenceDuplicate' in script
    assert 'card.dataset.mergeBlocked' in script
    assert "Needs data repair" in script
    assert 'button.closest(".master-data-duplicate-card")' in script
    assert 'ingredient.classList.toggle("is-suggested", isSuggested)' in script
    assert 'if (label) label.hidden = !isSuggested' in script
    assert 'referenceButton.dataset.suggestedTargetId = text(targetId)' in script
    assert 'mergeButton.setAttribute("aria-pressed", isSuggested ? "true" : "false")' in script
    decide_block = script[
        script.index("async function decideMasterDataDuplicate(button)"):
        script.index("function initMasterDataDuplicateReview()")
    ]
    assert "confirmMasterDataDuplicateMerge" not in decide_block
    assert decide_block.index("setMasterDataDuplicateSuggestedSurvivor(button);") < decide_block.index(
        "const response = await fetch(decisionUrl"
    )
    duplicate_review_block = script[
        script.index("function masterDataDuplicateElements()"):
        script.index("function renderProgress(")
    ]
    assert "window.confirm(" not in duplicate_review_block
    assert "window.location.assign(window.location.href)" not in duplicate_review_block
    assert "initMasterDataDuplicateReview();" in script
    assert ".master-data-duplicate-review" in css
    assert ".master-data-duplicate-comparison" in css
    assert ".master-data-ai-second-opinion" in css
    assert ".master-data-ai-second-opinion-evidence" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert ".master-data-duplicate-actions" in css
    assert ".master-data-duplicate-toolbar" in css
    assert ".master-data-duplicate-toolbar-actions" in css
    assert ".master-data-undo-dialog" in css
    assert ".master-data-undo-preview-comparison" in css
    assert ".master-data-undo-history-layout" in css
    assert ".master-data-undo-history-item" in css
    assert ".master-data-undo-history-date-group" in css
    assert ".master-data-undo-history-date-summary" in css
    assert ".master-data-undo-history-date-items" in css
    assert ".master-data-review-history-dialog" in css
    assert ".master-data-review-history-item" in css
    assert ".master-data-review-history-date-group" in css
    assert "Safe out-of-order undo" in script
    assert "Cannot safely undo yet" in script
    assert "Undo newer merges first" not in script
    assert "grid-template-columns: minmax(0, 1fr) auto;" in css
    assert '"[data-master-duplicate-scan], [data-master-duplicate-toolbar-scan]"' in script
    assert '"[data-master-duplicate-undo-merge], [data-master-duplicate-toolbar-undo-merge]"' in script
    assert ".master-data-duplicate-card.is-selected" in css
    assert ".master-data-duplicate-quality-warning" in css
    assert ".master-data-duplicate-ingredient-open" in css
    assert ".master-data-duplicate-view-references" in css
    assert ".master-data-reference-dialog" in css
    assert ".master-data-reference-dialog-comparison" in css
    assert ".master-data-reference-column.is-suggested" in css
    assert "data-master-duplicate-confirm-dialog" not in template
    assert "confirmMasterDataDuplicateMerge" not in script
    assert ".master-data-duplicate-confirm-dialog" not in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);" in css
    assert ".master-data-duplicate-scan-actions button" in css
    assert ".master-data-duplicate-scan-actions button.master-data-undo-merge" in css
    assert "Nothing is merged automatically." in template


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
