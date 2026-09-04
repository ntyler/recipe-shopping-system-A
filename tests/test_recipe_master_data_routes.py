import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
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

    # Most tests in this module exercise the rendered page rather than the
    # canonicalization hop itself. Preserve their intent by following the one
    # expected compatibility redirect for legacy master-data bookmarks. The
    # canonical URL behavior is asserted directly in
    # test_master_data_canonical_urls.py.
    if not getattr(client, "_master_data_get_follows_canonical", False):
        raw_get = client.get

        def get_with_canonical_redirect(*args, **kwargs):
            target = args[0] if args else kwargs.get("path", "")
            path = urlsplit(str(target or "")).path
            if path in {
                "/admin/master-data/ingredients",
                "/admin/master-data/equipment",
                "/admin/master-data/store-sections",
            }:
                kwargs.setdefault("follow_redirects", True)
            return raw_get(*args, **kwargs)

        client.get = get_with_canonical_redirect
        client._master_data_get_follows_canonical = True


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


def test_equipment_structured_review_ui_is_dark_launched(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    with app.app_context():
        seed_master_records()

    client = app.test_client()
    sign_in(client, "user-a")

    default_html = client.get("/admin/master-data/equipment").get_data(as_text=True)
    assert "data-equipment-normalization-review" not in default_html

    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED", "true")
    global_only_html = client.get("/admin/master-data/equipment").get_data(as_text=True)
    assert "data-equipment-normalization-review" not in global_only_html

    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_UI_TENANTS", "user-a")
    preview_html = client.get("/admin/master-data/equipment").get_data(as_text=True)
    assert "data-equipment-normalization-review" in preview_html
    assert "Decision writes are locked until the migration dry run is approved." in preview_html
    assert "Large pot" in preview_html
    assert "No structured-equipment decisions are needed on this page." in preview_html
    assert '<button type="button" disabled>Accept</button>' not in preview_html


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
    assert '<h1 id="masterDataTitle">Equipment</h1>' in equipment_html
    assert "Review equipment detected across your recipes." in equipment_html
    assert 'name="scope"' not in equipment_html
    assert "data-equipment-master-admin-view" not in equipment_html


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


def test_misc_reclassification_route_applies_only_the_selected_row(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/one-row-store-section",
        recipe_data={"ingredients": [
            {"ingredient": "Ground ginger", "store_section": "MISC"},
            {"ingredient": "Banana", "store_section": "MISC"},
        ]},
        user_id="user-a",
    )
    ground = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    banana = master_data.master_record_for_name("ingredients", "user-a", "banana")
    ingredient_ids = [ground["id"], banana["id"]]
    with master_data.recipe_master_connection() as connection:
        placeholders = ", ".join("?" for _value in ingredient_ids)
        connection.execute(
            f"UPDATE ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE id IN ({placeholders})",
            ingredient_ids,
        )
        connection.execute(
            f"UPDATE recipe_ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE ingredient_id IN ({placeholders})",
            ingredient_ids,
        )

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            "/api/master-data/ingredients/reclassify-misc",
            json={
                "apply": True,
                "decisions": [{
                    "ingredient_id": ground["id"],
                    "store_section": "Spices",
                    "decision_source": "deterministic",
                    "confidence": 1,
                }],
            },
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["changed_count"] == 1
    assert payload["undo_available"] is True
    assert payload["changes"][0]["ingredient_id"] == ground["id"]
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "ground ginger"
    )["store_section"] == "SPICES & SEASONINGS"
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "banana"
    )["store_section"] == "MISC"


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


def test_misc_reclassification_undo_route_and_button_restore_last_apply(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/undo-store-sections",
        recipe_data={"ingredients": [{"ingredient": "Ground ginger", "store_section": "MISC"}]},
        user_id="user-a",
    )
    ground = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            "UPDATE ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE id = ?",
            (ground["id"],),
        )
        connection.execute(
            "UPDATE recipe_ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE ingredient_id = ?",
            (ground["id"],),
        )

    with app.test_client() as client:
        sign_in(client, "user-a")
        apply_response = client.post(
            "/api/master-data/ingredients/reclassify-misc",
            json={
                "apply": True,
                "decisions": [{
                    "ingredient_id": ground["id"],
                    "store_section": "Spices",
                    "decision_source": "deterministic",
                    "confidence": 1,
                }],
            },
        )
        batch_id = apply_response.get_json()["batch_id"]
        applied_page = client.get("/admin/master-data/ingredients")
        preview_response = client.get(
            "/api/master-data/ingredients/reclassify-misc/undo-preview"
            f"?ingredient_id={ground['id']}"
        )
        section_after_preview = master_data.master_record_for_name(
            "ingredients", "user-a", "ground ginger"
        )["store_section"]
        undo_response = client.post(
            "/api/master-data/ingredients/reclassify-misc/undo",
            json={"batch_id": batch_id, "ingredient_id": ground["id"]},
        )
        restored_page = client.get("/admin/master-data/ingredients")

    applied_html = applied_page.get_data(as_text=True)
    restored_html = restored_page.get_data(as_text=True)
    assert apply_response.status_code == 200
    assert apply_response.get_json()["undo_available"] is True
    assert f'data-undo-batch-id="{batch_id}"' in applied_html
    assert 'data-undo-available="true"' in applied_html
    assert "Review Undo (1)" in applied_html
    assert 'id="masterDataStoreSectionUndoDialog"' in applied_html
    assert "Store-section history" in applied_html
    assert preview_response.status_code == 200
    preview_payload = preview_response.get_json()
    assert preview_payload["preview"]["batch_id"] == batch_id
    assert preview_payload["preview"]["ingredient_id"] == ground["id"]
    assert preview_payload["preview"]["change_count"] == 1
    assert len(preview_payload["items"]) == 1
    assert preview_payload["preview"]["recipe_reference_count"] == 1
    assert preview_payload["preview"]["affected_recipe_count"] == 1
    assert len(preview_payload["preview"]["recipe_references"]) == 1
    assert preview_payload["preview"]["recipe_references"][0]["ingredients"] == [
        "Ground ginger"
    ]
    assert preview_payload["preview"]["can_undo_now"] is True
    preview_change = preview_payload["preview"]["changes"][0]
    assert preview_change["ingredient"] == "Ground ginger"
    assert preview_change["ingredient_id"] == ground["id"]
    assert preview_change["applied_store_section"] == "SPICES & SEASONINGS"
    assert preview_change["restored_store_section"] == "MISC"
    assert preview_change["recipe_reference_count"] == 1
    assert section_after_preview == "SPICES & SEASONINGS"
    assert undo_response.status_code == 200
    assert undo_response.get_json()["restored_ingredient_count"] == 1
    assert undo_response.get_json()["restored_recipe_count"] == 1
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "ground ginger"
    )["store_section"] == "MISC"
    assert 'data-undo-available="false"' in restored_html


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
    assert '<th scope="rowgroup" colspan="5">PRODUCE</th>' in all_html
    assert '<th scope="col">User</th>' in all_html
    assert "master-data-table--show-user" in all_html
    assert 'class="master-data-user-data-cell"' in all_html
    assert 'data-master-auto-normalized-name' in all_html
    assert 'data-master-desktop-section-summary' in all_html
    assert '<th scope="col">Created At</th>' not in all_html
    assert 'class="master-data-created-cell"' not in all_html
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
    assert 'id="masterDataMiscReferencesDialog"' in all_html
    assert "Recipes using this ingredient" in all_html
    assert "Store-section maintenance" in all_html
    assert "data-master-misc-reclassification-preview-panel" in all_html
    assert "data-master-misc-reclassification-count" in all_html
    assert "data-master-misc-reclassification-empty" in all_html
    assert "Get AI Second Opinions" in all_html
    assert "Accept AI Suggestions" in all_html
    assert "data-master-misc-ai-accept" in all_html
    assert "AI second opinion" in all_html
    assert "Final decision" in all_html
    assert "data-ai-second-opinion-url" in all_html
    assert "data-master-misc-reclassification-undo" in all_html
    assert "Review Undo" in all_html
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
    assert '<th scope="col">User</th>' not in filtered_html
    assert "master-data-table--show-user" not in filtered_html
    assert 'class="master-data-user-data-cell"' not in filtered_html
    assert '<th scope="rowgroup" colspan="4">SPICES &amp; SEASONINGS</th>' in filtered_html
    assert equipment_response.status_code == 200
    assert 'data-equipment-master-registry' in equipment_html
    assert '<span>Workspace registry</span>' in equipment_html
    assert '<h2 id="equipmentRegistryTitle">Equipment Registry</h2>' in equipment_html
    assert "Equipment identity and recipe links remain read-only." in equipment_html
    assert "Customize display names without changing source recipes." in equipment_html
    assert 'data-equipment-master-read-only' in equipment_html
    assert "Recipe-derived" in equipment_html
    assert "Names customizable" in equipment_html
    assert "data-equipment-master-admin-view" in equipment_html
    assert "Viewing all users" in equipment_html
    assert 'name="scope"' in equipment_html
    assert 'class="master-data-results-header"' not in equipment_html
    assert "Showing 1-2 of 2 equipment." in equipment_html
    assert '<th scope="col">Item</th>' in equipment_html
    assert '<th scope="col">Equipment Type</th>' not in equipment_html
    assert '<th scope="col">Used In</th>' in equipment_html
    assert '<th scope="col">Usage</th>' not in equipment_html
    assert '<th scope="col">Updated</th>' in equipment_html
    assert '<th scope="col">Action</th>' in equipment_html
    assert '<th scope="col">Created At</th>' not in equipment_html
    assert 'class="master-data-created-cell"' not in equipment_html
    assert "<code>large pot</code>" not in equipment_html
    assert "<code>whisk</code>" not in equipment_html
    assert 'class="master-data-equipment-details"' in equipment_html
    assert ">Details</summary>" in equipment_html
    assert ">Created</span>" in equipment_html
    assert 'class="master-data-updated-cell"' in equipment_html
    assert '<th scope="col">Normalized Name</th>' not in equipment_html
    assert '<th scope="col">Image</th>' not in equipment_html
    assert '<section class="unit-master-category equipment-master-category"' in equipment_html
    assert '<h3 id="equipmentCategory-1">Cookware</h3>' in equipment_html
    assert '<h3 id="equipmentCategory-2">Prep Tools</h3>' in equipment_html
    assert 'aria-label="Cookware equipment"' in equipment_html
    assert 'aria-label="Prep Tools equipment"' in equipment_html
    assert 'unit-master-usage-button equipment-master-usage-button' in equipment_html
    assert 'data-equipment-master-usage-button' in equipment_html
    assert 'aria-controls="equipmentMasterUsageDialog"' in equipment_html
    assert 'aria-haspopup="dialog"' in equipment_html
    assert 'data-equipment-master-usage-dialog' in equipment_html
    assert 'data-equipment-master-usage-title' in equipment_html
    assert 'data-equipment-master-usage-summary' in equipment_html
    assert 'data-equipment-master-usage-results' in equipment_html
    assert 'data-equipment-master-usage-close' in equipment_html
    assert 'data-master-reference-row' not in equipment_html
    assert '<strong aria-hidden="true">1</strong>' in equipment_html
    assert "recipe" in equipment_html
    assert '<strong data-equipment-master-total-count>2</strong>' in equipment_html
    assert '<strong data-equipment-master-type-count>2</strong>' in equipment_html
    assert '<strong data-equipment-master-used-count>2</strong>' in equipment_html
    assert '<strong data-equipment-master-unused-count>0</strong>' in equipment_html
    assert 'aria-label="Equipment summary"' in equipment_html
    assert 'aria-current="page"' in equipment_html
    assert "Generate Missing Images" in equipment_html
    assert "Store Sections" in equipment_html
    assert 'name="store_section"' not in equipment_html
    assert 'name="equipment_section"' in equipment_html
    assert 'class="master-data-filter-form equipment-master-toolbar"' in equipment_html
    assert 'class="master-data-thumbnail-size-section equipment-master-thumbnail-field"' in equipment_html
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
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE recipe_ingredients
               SET preparation = 'diced',
                   notes = 'use ripe tomatoes',
                   buy_as = 'tomato'
             WHERE ingredient_id = ?
            """,
            (user_a_tomato["id"],),
        )
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
    assert admin_payload["total_reference_count"] == 1
    assert admin_payload["ingredient_name_recipe_count"] == 1
    assert admin_payload["buy_as_recipe_count"] == 1
    assert admin_payload["references"][0]["recipe_title"] == "User A Soup"
    assert admin_payload["references"][0]["ingredient_name"] == "Tomato"
    assert admin_payload["references"][0]["matches_ingredient_name"] is True
    assert admin_payload["references"][0]["matches_buy_as"] is True
    assert admin_payload["references"][0]["recipe_url"] == "https://example.com/user-a-soup"
    assert admin_payload["references"][0]["preparation"] == "diced"
    assert admin_payload["references"][0]["notes"] == "use ripe tomatoes"
    assert admin_payload["references"][0]["edit_url"] == ""
    for image_key in ("recipe_image_url", "recipe_image_full_url"):
        image_url = urlsplit(admin_payload["references"][0][image_key])
        assert image_url.path == "/recipe_cover_image"
        assert dict(parse_qsl(image_url.query)) == {
            "viewer_user_id": "admin-user",
            "url": "https://example.com/user-a-soup",
        }
    assert admin_payload["references"][0]["recipe_image_alt"] == "User A Soup title image"
    assert own_response.status_code == 200
    assert own_payload["record"]["name"] == "Tomato"
    own_edit_url = urlsplit(own_payload["references"][0]["edit_url"])
    assert own_edit_url.path == "/recipe/edit"
    assert parse_qsl(own_edit_url.query) == [
        ("viewer_user_id", "user-a"),
        ("url", "https://example.com/user-a-soup"),
    ]
    assert blocked_response.status_code == 404
    assert blocked_payload["ok"] is False


def test_equipment_usage_modal_endpoint_preserves_workspace_scope(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    user_a_equipment = master_data.master_record_for_name(
        "equipment",
        "user-a",
        "large pot",
    )
    user_b_equipment = master_data.master_record_for_name(
        "equipment",
        "user-b",
        "whisk",
    )

    with app.test_client() as client:
        sign_in(client, "user-a")
        own_response = client.get(
            f"/api/master-data/equipment/{user_a_equipment['id']}/references",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        blocked_response = client.get(
            f"/api/master-data/equipment/{user_b_equipment['id']}/references",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        sign_in(client, "admin-user")
        admin_response = client.get(
            f"/api/master-data/equipment/{user_b_equipment['id']}/references?scope=all",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

    own_payload = own_response.get_json()
    admin_payload = admin_response.get_json()
    assert own_response.status_code == 200
    assert own_payload["record"]["name"] == "Large pot"
    assert own_payload["total"] == 1
    assert own_payload["references"][0]["original_recipe_text"] == "Large pot"
    assert urlsplit(own_payload["references"][0]["edit_url"]).path == "/recipe/edit"
    assert blocked_response.status_code == 404
    assert admin_response.status_code == 200
    assert admin_payload["record"]["name"] == "Whisk"
    assert admin_payload["references"][0]["edit_url"] == ""


def test_equipment_display_name_route_updates_only_the_active_workspace(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    user_a_equipment = master_data.master_record_for_name("equipment", "user-a", "large pot")
    user_b_equipment = master_data.master_record_for_name("equipment", "user-b", "whisk")

    with app.test_client() as client:
        sign_in(client, "user-a")
        saved_response = client.patch(
            f"/api/master-data/equipment/{user_a_equipment['id']}/display-name",
            json={"display_name": "Family stockpot"},
        )
        blocked_response = client.patch(
            f"/api/master-data/equipment/{user_b_equipment['id']}/display-name",
            json={"display_name": "Not mine"},
        )
        renamed_page = client.get("/admin/master-data/equipment")
        reset_response = client.patch(
            f"/api/master-data/equipment/{user_a_equipment['id']}/display-name",
            json={"reset": True},
        )
        sign_in(client, "admin-user")
        admin_blocked_response = client.patch(
            f"/api/master-data/equipment/{user_a_equipment['id']}/display-name",
            json={"display_name": "Admin overwrite"},
        )

    renamed_html = renamed_page.get_data(as_text=True)
    assert saved_response.status_code == 200
    assert saved_response.get_json()["record"]["name"] == "Family stockpot"
    assert saved_response.get_json()["record"]["has_display_name_override"] is True
    assert blocked_response.status_code == 404
    assert admin_blocked_response.status_code == 404
    assert '<strong data-equipment-master-display-name>Family stockpot</strong>' in renamed_html
    assert 'data-current-name="Family stockpot"' in renamed_html
    assert 'data-detected-name="Large pot"' in renamed_html
    assert 'data-has-display-name-override="true"' in renamed_html
    assert "Edit display name" in renamed_html
    assert "data-equipment-master-display-dialog" in renamed_html
    renamed_soup = BeautifulSoup(renamed_html, "html.parser")
    display_dialog = renamed_soup.select_one("[data-equipment-master-display-dialog]")
    reset_button = display_dialog.select_one("[data-equipment-master-display-reset]")
    save_button = display_dialog.select_one("[data-equipment-master-display-save]")
    cancel_button = display_dialog.select_one(
        "footer [data-equipment-master-display-close]"
    )
    assert reset_button.get_text(strip=True) == "Reset"
    assert reset_button["aria-label"] == "Reset display name to detected name"
    assert cancel_button.get_text(strip=True) == "Cancel"
    assert save_button.get_text(strip=True) == "Save"
    assert save_button["aria-label"] == "Save display name"
    assert reset_response.status_code == 200
    assert reset_response.get_json()["record"]["name"] == "Large pot"
    assert reset_response.get_json()["record"]["has_display_name_override"] is False


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
    template = (root / "PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    script = (root / "PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = (root / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "function friendlyIngredientStoreSection(value)" in script
    assert '"SPICES & SEASONINGS": "Spices"' in script
    assert '"CANNED": "Canned Goods"' in script
    assert "Classification details" in script
    assert "MISC_REVIEW_STORE_SECTIONS" in script
    assert "requestMiscAiSecondOpinions" in script
    assert "acceptMiscAiSuggestions" in script
    assert "miscReviewDecisionPayload" in script
    assert "miscReviewDecisionForRow" in script
    assert "requestMiscRowReclassification" in script
    assert "function miscReviewIngredientImage(row)" in script
    assert "function miscReviewReferenceUrl(panel, ingredientId)" in script
    assert "function miscReviewReferenceElements()" in script
    assert "function renderMiscReviewReferenceDialog(els, row)" in script
    assert "async function openMiscReviewReferences(panel, row, trigger)" in script
    assert "function closeMiscReviewReferences()" in script
    assert "function initMiscReviewReferenceDialog()" in script
    assert "imageUrl: text(change.image_url)" in script
    assert "imageUrl: text(opinion.image_url)" in script
    assert 'image.className = "master-data-thumbnail master-data-misc-thumbnail"' in script
    assert 'name.className = "master-data-misc-ingredient-name"' in script
    assert 'name.setAttribute("aria-haspopup", "dialog")' in script
    assert 'name.setAttribute("aria-controls", "masterDataMiscReferencesDialog")' in script
    assert "openMiscReviewReferences(panel, row, name)" in script
    assert "if (event.target === els.dialog) closeMiscReviewReferences()" in script
    assert "if (returnFocus && returnFocus.isConnected) returnFocus.focus()" in script
    assert 'data-reference-url="{{ master_data.ingredient_reference_url }}"' in template
    assert 'id="masterDataMiscReferencesDialog"' in template
    assert "data-master-misc-reference-dialog" in template
    assert "data-master-misc-reference-close" in template
    assert "data-master-misc-reference-body" in template
    assert 'id="masterDataStoreSectionUndoDialog"' in template
    assert "data-master-store-section-undo-history-list" in template
    assert "data-master-store-section-undo-change-list" in template
    assert "data-master-store-section-undo-confirm" in template
    assert "data-master-store-section-undo-restored-sections" in template
    assert "data-master-store-section-undo-current-sections" in template
    assert "data-master-store-section-undo-recipes" in template
    assert "Review ingredient details" in template
    assert "data-undo-preview-url" in template
    assert "requestMiscReclassificationUndo" in script
    assert "panel.dataset.undoBatchId" in script
    assert "function miscStoreSectionUndoElements()" in script
    assert "async function openMiscStoreSectionUndoPreview(panel, trigger)" in script
    assert "async function loadMiscStoreSectionUndoPreview(panel, batchId = 0, ingredientId = 0)" in script
    assert "function renderMiscStoreSectionUndoPreview(panel, preview, items)" in script
    assert "function renderMiscStoreSectionUndoComparison(els, preview)" in script
    assert "function renderMiscStoreSectionUndoRecipes(els, preview)" in script
    assert "function miscStoreSectionUndoHistoryKey(item)" in script
    assert "function renderMiscStoreSectionUndoHistory(panel, items, selectedItemKey)" in script
    assert "miscStoreSectionUndoCollapsedDateGroups" in script
    assert "data.items" in script
    assert "ingredient_id: Number(preview.ingredient_id) || 0" in script
    assert "Restorable decisions" in template
    assert "openMiscStoreSectionUndoPreview(panel, undoButton)" in script
    assert "requestMiscReclassificationUndo(panel)" in script
    assert "batch_id: Number(preview.batch_id) || 0" in script
    assert "AI suggestions for unresolved ingredients are preselected and remain editable." in script
    assert ".master-data-misc-reclassification-header" in css
    assert ".master-data-misc-reclassification-list" in css
    assert ".master-data-section-pill.is-proposed" in css
    assert ".master-data-misc-reclassification-actions" in css
    assert ".master-data-misc-ai-status" in css
    assert ".master-data-misc-decision" in css
    assert ".master-data-misc-decision-control" in css
    assert ".master-data-misc-decision-actions" in css
    assert ".master-data-misc-row-apply-button" in css
    assert ".master-data-misc-ingredient-copy" in css
    assert ".master-data-misc-thumbnail" in css
    assert ".master-data-misc-ingredient-name" in css
    assert ".master-data-misc-reference-dialog" in css
    assert ".master-data-misc-reference-heading" in css
    assert ".master-data-misc-reference-dialog-content" in css
    assert ".master-data-store-section-undo-comparison" in css
    assert ".master-data-store-section-undo-state.is-restored" in css
    assert ".master-data-store-section-undo-direction svg" in css
    assert ".master-data-store-section-undo-recipes" in css
    assert ".master-data-store-section-undo-change-list" in css
    assert ".master-data-store-section-undo-transition" in css
    assert ".master-data-section-pill.is-restored" in css
    assert "height: calc(100dvh - 12px);" in css
    assert "miscReviewReferencePanel" not in script
    assert "referencesExpanded" not in script
    assert ".is-accept-ai" in css
    assert ".master-data-action-undo" in css
    decision_start = script.index("function miscReviewDecisionSelect")
    decision_end = script.index("function miscReviewIngredientCell", decision_start)
    decision_block = script[decision_start:decision_end]
    assert 'label.className = "master-data-misc-decision-control"' in decision_block
    assert 'applyRowButton.textContent = row.applying ? "Applying..." : "Apply Row"' in decision_block
    assert "requestMiscRowReclassification(panel, row)" in decision_block
    assert 'labelText.className = "sr-only"' in decision_block
    assert 'label.className = "sr-only"' not in decision_block
    accept_start = script.index("function acceptMiscAiSuggestions")
    accept_end = script.index("async function requestMiscAiSecondOpinions", accept_start)
    accept_block = script[accept_start:accept_end]
    assert "row.decisionSection = row.ai.storeSection" in accept_block
    assert "row.requiresDecision = false" in accept_block
    ai_request_start = script.index("async function requestMiscAiSecondOpinions")
    ai_request_end = script.index("function initMiscIngredientReclassification", ai_request_start)
    ai_request_block = script[ai_request_start:ai_request_end]
    assert "else if (!row.deterministic)" in ai_request_block
    assert "row.decisionSection = row.ai.storeSection" in ai_request_block
    assert "row.decisionSource = miscReviewDecisionSource" in ai_request_block


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
    assert 'data-equipment-master-registry' in all_html
    assert '<section class="unit-master-category equipment-master-category"' in all_html
    assert "COOKWARE" in all_html
    assert "PREP TOOLS" in all_html
    assert cookware_response.status_code == 200
    assert 'value="COOKWARE" selected' in cookware_html
    assert "Large pot" in cookware_html
    assert "Whisk" not in cookware_html
    assert '<section class="unit-master-category equipment-master-category"' in cookware_html
    assert '<h3 id="equipmentCategory-1">Cookware</h3>' in cookware_html
    assert 'aria-label="Cookware equipment"' in cookware_html


def test_equipment_user_column_only_renders_for_all_users_scope(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with app.test_client() as client:
        sign_in(client, "user-a")
        mine_response = client.get("/admin/master-data/equipment")
        sign_in(client, "admin-user")
        specific_response = client.get(
            "/admin/master-data/equipment?scope=user&user_id=user-b",
        )
        all_response = client.get("/admin/master-data/equipment?scope=all")

    for response in (mine_response, specific_response, all_response):
        assert response.status_code == 200

    mine_soup = BeautifulSoup(mine_response.get_data(as_text=True), "html.parser")
    specific_soup = BeautifulSoup(specific_response.get_data(as_text=True), "html.parser")
    all_soup = BeautifulSoup(all_response.get_data(as_text=True), "html.parser")

    for table in mine_soup.select(".equipment-master-category table"):
        assert [
            header.get_text(" ", strip=True)
            for header in table.select("thead th")
        ] == ["Item", "Used In", "Updated", "Action"]
        for row in table.select("tbody > .master-data-record-row"):
            assert [cell.get("data-label") for cell in row.find_all("td", recursive=False)] == [
                "Item",
                "Used In",
                "Updated",
                "Action",
            ]
            item_cell = row.select_one(".master-data-item-cell")
            action_cell = row.select_one(".equipment-master-action-cell")
            edit_button = action_cell.select_one("[data-equipment-master-display-edit]")
            assert item_cell.select_one("[data-equipment-master-display-edit]") is None
            assert edit_button.get_text(strip=True) == "Edit"
            assert edit_button["aria-label"].startswith("Edit display name for ")

    for table in specific_soup.select(".equipment-master-category table"):
        assert [
            header.get_text(" ", strip=True)
            for header in table.select("thead th")
        ] == ["Item", "Used In", "Updated", "Action"]
        assert table.select_one("[data-equipment-master-display-edit]") is None

    for table in all_soup.select(".equipment-master-category table"):
        assert [
            header.get_text(" ", strip=True)
            for header in table.select("thead th")
        ] == ["Item", "User", "Used In", "Updated", "Action"]
        for row in table.select("tbody > .master-data-record-row"):
            assert [cell.get("data-label") for cell in row.find_all("td", recursive=False)] == [
                "Item",
                "User",
                "Used In",
                "Updated",
                "Action",
            ]
        assert table.select_one("[data-equipment-master-display-edit]") is None

    mine_table = mine_response.get_data(as_text=True).split(
        '<table class="master-data-table', 1
    )[1].split("</table>", 1)[0]
    specific_table = specific_response.get_data(as_text=True).split(
        '<table class="master-data-table', 1
    )[1].split("</table>", 1)[0]
    all_table = all_response.get_data(as_text=True).split(
        '<table class="master-data-table', 1
    )[1].split("</table>", 1)[0]

    for single_user_table in (mine_table, specific_table):
        assert '<th scope="col">User</th>' not in single_user_table
        assert 'class="master-data-user-data-cell"' not in single_user_table
        assert 'data-master-reference-row' not in single_user_table
        assert "master-data-table--show-user" not in single_user_table

    assert '<th scope="col">User</th>' in all_table
    assert 'class="master-data-user-data-cell"' in all_table
    assert 'data-master-reference-row' not in all_table
    assert "master-data-table--show-user" in all_table


def test_equipment_summary_counts_include_unused_records(monkeypatch, tmp_path):
    configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with master_data.recipe_master_connection() as connection:
        connection.execute(
            "DELETE FROM recipe_equipment WHERE user_id = ?",
            ("user-a",),
        )

    user_summary = master_data.equipment_summary_counts("user-a")
    all_summary = master_data.equipment_summary_counts(include_all_users=True)

    assert user_summary == {
        "total_count": 1,
        "type_count": 1,
        "in_use_count": 0,
        "unused_count": 1,
    }
    assert all_summary == {
        "total_count": 2,
        "type_count": 2,
        "in_use_count": 1,
        "unused_count": 1,
    }


def test_equipment_registry_renders_single_name_created_details_and_unused_state(
    monkeypatch,
    tmp_path,
):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()

    with master_data.recipe_master_connection() as connection:
        connection.execute(
            "DELETE FROM recipe_equipment WHERE user_id = ?",
            ("user-a",),
        )

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/equipment")

    html = response.get_data(as_text=True)
    registry_html = html.split('data-equipment-master-registry', 1)[1].split("</section>", 1)[0]

    assert response.status_code == 200
    assert "Showing 1-1 of 1 equipment." in html
    assert '<h3 id="equipmentCategory-1">Cookware</h3>' in html
    assert html.count('<strong data-equipment-master-display-name>Large pot</strong>') == 1
    assert "<code>large pot</code>" not in html
    assert '<details class="master-data-equipment-details">' in html
    assert ">Details</summary>" in html
    assert 'aria-label="Show created date for Large pot"' in html
    assert ">Created</span>" in html
    assert "<strong>Unused</strong>" in html
    assert "<small>0 uses</small>" in html
    assert "equipment-master-usage-button" not in registry_html
    assert ">Add" not in registry_html
    assert 'aria-label="Edit display name for Large pot"' in registry_html
    assert ">Edit</button>" in registry_html
    assert ">Delete" not in registry_html


def test_master_data_date_label_is_human_readable():
    assert main_routes.master_data_date_label("2026-08-03T22:36:11Z") == "Aug 3, 2026"
    assert main_routes.master_data_date_label("") == "Unknown"


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
    manage_url = urlsplit(payload["manage_url"])
    assert manage_url.path == "/admin/master-data/ingredients"
    assert parse_qsl(manage_url.query) == []
    assert payload["ingredients"] == [{
        "ingredient_id": payload["ingredients"][0]["ingredient_id"],
        "name": "Tomato",
        "normalized_name": "tomato",
        "canonical_ingredient": "tomato",
        "form": "",
        "store_section": "PRODUCE",
        "store_section_source": "deterministic_rule",
        "store_section_confidence": 0.95,
        "store_section_user_confirmed": False,
        "classifier_version": "2.0",
        "store_section_reason": "Matched a deterministic ingredient keyword rule.",
        "store_section_rule": "keyword.6",
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
    merge_redirect = urlsplit(merge_payload["redirect_url"])
    assert merge_redirect.path == "/admin/master-data/ingredients"
    assert dict(parse_qsl(merge_redirect.query)) == {
        "search": "potato",
    }
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
    assert "data-master-auto-normalized-name" in template
    assert "update_ingredient_master_record_route" in template
    assert '<button type="submit">Save</button>' not in template

    assert "function initMasterDataStoreSectionBatchSave" in script
    assert "function changedStoreSectionForms" in script
    assert "function saveChangedStoreSections" in script
    assert "function submitStoreSectionForm" in script
    assert "function masterDataRecordFields" in script
    assert "function normalizeMasterDataIngredientName(value)" in script
    assert '.replace(/\\s+/g, " ").trim().toLowerCase()' in script
    assert "normalizedInput.value = normalizeMasterDataIngredientName(nameInput.value);" in script
    assert "currentMasterRecordFieldValue(field) !== originalMasterRecordFieldValue(field)" in script
    assert "initMasterDataStoreSectionBatchSave();" in script
    assert '"X-Requested-With": "fetch"' in script
    assert "window.location.assign(canonicalMasterDataUrl(window.location.href).toString())" in script

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


def test_master_data_mobile_layout_prioritizes_filters_and_results():
    template = Path("PushShoppingList/templates/master_data.html").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/master-data.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    filter_position = template.index('class="master-data-filter-form')
    results_position = template.index('data-master-results-header')
    pagination_position = template.index('data-master-pagination')

    assert filter_position < results_position < pagination_position
    assert "data-master-maintenance open" not in template
    assert "<span>Maintenance tools</span>" in template
    assert 'data-label="Store section"' in template
    assert 'class="unit-master-category equipment-master-category"' in template
    assert ".equipment-master-category-list" in css
    assert ".equipment-master-category .master-data-record-row" in css
    assert ".equipment-master-read-only-badge" in css
    assert ".equipment-master-admin-view" in css
    assert ".equipment-master-display-dialog" in css
    assert ".equipment-master-action-cell" in css
    assert ".equipment-master-row-editable" in css
    assert "@media (max-width: 1280px)" in css
    assert ".equipment-master-category .master-data-equipment-details summary:is(:hover, :focus-visible)" in css
    assert "data-master-mobile-record-name" in template
    assert "data-master-mobile-section-summary" in template
    assert "data-master-mobile-record-toggle" in template
    assert "data-master-auto-normalized-name" in template
    assert "data-master-desktop-section-summary" in template
    assert "data-master-mobile-reference-dialog" in template
    assert "data-master-mobile-reference-title" in template
    assert "data-master-mobile-reference-panel" in template
    assert "data-master-mobile-reference-close" in template
    assert "function initMasterDataMaintenance()" in script
    assert 'const pagination = document.querySelector("[data-master-pagination]");' in script
    assert 'pagination.insertAdjacentElement("afterend", maintenance);' in script
    assert "maintenance.open = false;" in script
    assert "function initMasterDataMobileRecords()" in script
    assert "function setMasterDataMobileRecordExpanded(row, expanded)" in script
    assert "function syncMasterDataMobileSectionSummary(select)" in script
    assert '"[data-master-mobile-section-summary], [data-master-desktop-section-summary]"' in script
    assert 'row.querySelector(\'input[name="normalized_name"]\')' in script
    assert "async function loadReferenceData(button, panel, options = {})" in script
    assert "function masterDataMobileReferenceElements()" in script
    assert "async function openMasterDataMobileReferences(button)" in script
    assert "function closeMasterDataMobileReferences()" in script
    assert "function initEquipmentMasterDisplayName()" in script
    assert "async function saveEquipmentMasterDisplayName(reset = false)" in script
    assert 'method: "PATCH"' in script
    assert 'window.matchMedia("(max-width: 760px)").matches' in script
    assert "await loadReferenceData(button, els.panel, { hideHeader: true });" in script
    assert "if (referenceRow) referenceRow.hidden = true;" in script
    assert 'window.matchMedia("(max-width: 760px)")' in script
    assert "initMasterDataMaintenance();" in script
    assert "initMasterDataMobileRecords();" in script
    assert "initEquipmentMasterDisplayName();" in script
    assert "@media (max-width: 760px)" in css
    assert ".master-data-maintenance:not([open]) > .master-data-maintenance-content" in css
    assert ".master-data-maintenance {" in css
    assert "order: 100;" in css
    assert ".master-data-ingredients-table .master-data-record-row" in css
    assert ".master-data-mobile-record-toggle[aria-expanded=\"true\"] svg" in css
    assert ".master-data-record-row.master-data-record-row-expanded" in css
    assert ".master-data-desktop-section-summary" in css
    assert "@media (min-width: 761px)" in css
    assert "grid-template-columns: 17px minmax(0, 1fr);" in css
    assert "max-width: 240px;" in css
    assert "background: rgba(45, 143, 112, .045);" in css
    assert "grid-template-columns: minmax(0, 1fr) auto;" in css
    assert "box-shadow: inset 3px 0 0 #2d8f70;" in css
    assert "white-space: nowrap;" in css
    assert ".master-data-table--show-user" in css
    assert ".master-data-mobile-reference-dialog" in css
    assert ".master-data-mobile-reference-dialog::backdrop" in css
    assert ".master-data-mobile-reference-panel" in css
    assert ".master-data-mobile-reference-footer" in css
    assert "> :is(.master-data-user-data-cell, .master-data-updated-cell, .master-data-created-cell)" in css
    assert "master-data-table--section-filtered" in template
    assert ".master-data-ingredients-table.master-data-table--section-filtered" in css
    assert ".master-data-scope-filter-field" in css
    assert "[data-master-record-results]" in css
    assert "overflow-x: clip;" in css


def test_equipment_registry_header_uses_the_units_surface_treatment():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    selector = ".equipment-master-category .master-data-table th {"
    rule_start = css.index(selector)
    rule = css[rule_start:css.index("}", rule_start)]

    assert "padding: 10px 12px;" in rule
    assert "border-bottom-color: var(--app-border);" in rule
    assert "background: transparent;" in rule
    assert "color: var(--app-muted);" in rule
    assert "#0b1420" not in rule


def test_equipment_display_dialog_reuses_compact_units_button_styles():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert css.count(".equipment-master-display-dialog") >= 7
    assert ") button {" in css
    assert ") button.secondary {" in css
    assert ".equipment-master-display-form > footer button {" in css
    assert "white-space: nowrap;" in css


def test_equipment_usage_pill_uses_the_complete_units_visual_contract():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    template = Path("PushShoppingList/templates/master_data.html").read_text(
        encoding="utf-8"
    )

    selector = ".unit-master-usage-button {"
    rule_start = css.index(selector)
    rule = css[rule_start:css.index("}", rule_start)]

    assert "unit-master-usage-button equipment-master-usage-button" in template
    for declaration in (
        "width: auto;",
        "align-items: baseline;",
        "justify-content: center;",
        "gap: 4px;",
        "padding: 5px 8px !important;",
        "margin: 0;",
        "border: 1px solid color-mix(",
        "border-radius: 7px;",
        "font: inherit;",
        "font-size: 13px;",
        "font-weight: 850;",
        "white-space: nowrap;",
    ):
        assert declaration in rule
    assert ".unit-master-usage-button:focus-visible {" in css


def test_equipment_usage_pills_are_centered_and_consistently_sized():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    alignment_selector = ".equipment-master-category :is("
    alignment_start = css.index(alignment_selector)
    alignment_rule = css[alignment_start:css.index("}", alignment_start)]

    for selector in (
        ".equipment-master-usage-button,",
        ".master-data-updated-cell time,",
        ".equipment-master-display-edit",
    ):
        assert selector in alignment_rule
    for declaration in (
        "box-sizing: border-box;",
        "height: 36px;",
        "vertical-align: middle;",
    ):
        assert declaration in alignment_rule

    selector = ".equipment-master-usage-button {"
    rule_start = css.index(selector)
    rule = css[rule_start:css.index("}", rule_start)]

    assert "min-width: 72px;" in rule
    assert "align-items: center;" in rule

    date_selector = ".equipment-master-category .master-data-updated-cell time {"
    date_start = css.index(date_selector)
    date_rule = css[date_start:css.index("}", date_start)]
    for declaration in (
        "display: inline-flex;",
        "align-items: center;",
        "line-height: 1;",
    ):
        assert declaration in date_rule

    edit_selector = ".equipment-master-display-edit {"
    edit_start = css.index(edit_selector)
    edit_rule = css[edit_start:css.index("}", edit_start)]
    assert "margin: 0;" in edit_rule

    assert ".equipment-master-usage-button span {" in css
    assert "line-height: 1;" in css[
        css.index(".equipment-master-usage-button span {"):
        css.index("}", css.index(".equipment-master-usage-button span {"))
    ]


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
    assert 'return canonicalMasterDataUrl(url, { ...context, limit: "500" }).toString();' in script
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
    app_script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert '<th scope="col">Item</th>' in template
    assert '<th scope="col">Normalized Name</th>' not in template
    assert '<th scope="col">Image</th>' not in template
    assert "master-data-item-cell" in template
    assert "master-data-item-copy" in template
    assert "data-master-reference-toggle" in template
    assert "data-master-reference-row" in template
    assert "row.usage_count and master_data.record_type == 'ingredients'" in template
    assert "data-equipment-master-usage-dialog" in template
    assert "data-equipment-master-usage-button" in template
    assert "master_data_record_references_route" in template
    assert "aria-expanded=\"false\"" in template
    assert "aria-label=\"Show {{ row.usage_count }} recipe" in template
    assert "{{ row.ingredient_name_usage_count }} by Ingredient Name" in template
    assert "{{ row.buy_as_usage_count }} by Buy As" in template
    assert 'class="master-data-usage-total"' in template
    assert 'class="master-data-usage-breakdown"' in template
    assert "master-data-record-row-unused" in template
    assert 'data-master-record-unused="true"' in template
    assert "<strong>Unused</strong>" in template
    assert "<small>0 uses</small>" in template
    assert "View recipes" not in template
    assert "master-data-usage-chevron" not in template
    assert "data-reference-url" in template
    assert "js/master-data.js" in template
    assert "data-master-thumbnail-size-controls" in template
    assert "data-master-thumbnail-size-decrease" in template
    assert "data-master-thumbnail-size-increase" in template
    assert "data-master-thumbnail-size-value>64px" in template
    assert "data-full-src=\"{{ row.image_url }}\"" in template
    assert "data-master-store-section-select" in template
    assert 'data-store-section-allow-custom="false"' in template
    assert ".master-data-record-row-unused td" in css
    assert ".master-data-record-row-unused td:first-child" in css
    assert ".master-data-usage-empty strong" in css

    assert "function toggleReferenceRow" in script
    assert "function openEquipmentMasterUsage(button)" in script
    assert "function closeEquipmentMasterUsage()" in script
    assert "function restoreEquipmentMasterUsageFocus()" in script
    assert 'button.matches("[data-equipment-master-usage-button]")' in script
    assert "equipmentMasterUsageRequestId" in script
    assert "function renderReferences" in script
    assert "master-data-reference-usage-breakdown" in script
    assert "Ingredient Name ${ingredientNameCount}" in script
    assert "Buy As ${buyAsCount}" in script
    assert "Counts overlap when a recipe uses this record in both fields." in script
    assert "master-data-reference-matches" in script
    assert 'nameMatch.textContent = "Ingredient Name";' in script
    assert 'buyAsMatch.textContent = "Buy As";' in script
    assert "[data-master-reference-toggle]" in script
    assert "function initMasterDataStoreSectionIconPickers()" in script
    assert "createRecipeIngredientStoreSectionTrigger(select)" in script
    assert "initMasterDataStoreSectionIconPickers();" in script
    assert 'select.dataset.storeSectionAllowCustom !== "false"' in app_script
    assert ".master-data-store-section-trigger .recipe-edit-store-section-icon" in css
    assert "data-master-reference-panel" in script
    assert "recipe_image_url" in script
    assert "recipe_image_full_url" in script
    assert "recipe_image_srcset" in script
    assert "master-data-reference-title-image" in script
    assert "master-data-reference-copy" in script
    assert "master-data-reference-title-link" in script
    assert "has-title-image" in script
    assert "Open Recipe" in script
    assert ".equipment-master-usage-dialog .master-data-reference-main code" in css
    assert ".equipment-master-usage-dialog .master-data-reference-link" in css
    assert 'details.push(`Preparation: ${reference.preparation}`)' in script
    assert 'details.push(`Notes: ${reference.notes}`)' in script
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
    assert ".master-data-usage-total" in css
    assert ".master-data-usage-breakdown" in css
    assert ".master-data-reference-usage-breakdown" in css
    assert ".master-data-reference-matches" in css
    assert ".master-data-usage-button span:nth-child" not in css
    assert ".master-data-usage-chevron" not in css
    assert ".master-data-reference-row[hidden]" in css
    assert ".master-data-reference-panel" in css
    assert ".master-data-reference-title-row" in css
    assert ".master-data-reference-title-row.has-title-image" in css
    assert ".master-data-reference-title-image" in css
    assert ".master-data-reference-copy" in css
    assert ".master-data-reference-title-link" in css
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
    assert '<span class="user-account-menu-item-label">Equipment</span>' in html
    assert ">Units<" in html
    assert "Store Sections" in html
    assert 'href="/admin/master-data/ingredients"' in html
    assert 'href="/admin/master-data/equipment"' in html
    assert 'href="/admin/master-data/units"' in html
    assert 'href="/admin/master-data/store-sections"' in html


def test_store_sections_page_manages_only_the_active_workspace(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/store-sections")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Store Sections" in html
        assert "Add Store Section" in html
        assert "Produce" in html
        assert "/admin/master-data/ingredients" in html
        assert "/admin/master-data/equipment" in html
        assert "/admin/master-data/units" in html
        assert "data-store-section-master-icon-picker" in html
        assert 'data-store-section-master-icon-option="leaf"' in html
        assert "recipe-edit-store-section-icon is-leaf" in html
        toggle_count = html.count(
            "data-store-section-master-mobile-details-toggle"
        )
        details_count = html.count(
            "data-store-section-master-mobile-details"
        ) - toggle_count
        assert toggle_count == len(
            master_data.ingredient_store_section_details(
                "user-a",
                include_inactive=True,
            )
        )
        assert details_count == toggle_count
        assert 'aria-controls="storeSectionMobileDetails-' in html
        assert 'id="storeSectionMobileDetails-' in html
        assert "Change display names, icons, and order for this workspace." in html
        assert "Built-in identity and automatic routing stay protected" in html
        assert "Store Section Registry" in html
        assert ">Display Name</div>" in html
        soup = BeautifulSoup(html, "html.parser")
        rendered_section_count = len(
            master_data.ingredient_store_section_details(
                "user-a",
                include_inactive=True,
            )
        )
        assert soup.select_one("#storeSectionOrderTitle").get_text(
            " ", strip=True
        ) == "Store Section Registry"
        assert soup.select_one(
            "[data-store-section-master-visible-count]"
        ).get_text(" ", strip=True) == (
            f"Showing {rendered_section_count} of {rendered_section_count} "
            "Store Sections"
        )
        search_label = soup.select_one(".store-section-master-search")
        assert search_label.select_one(
            ".store-section-master-search-label"
        ).get_text(" ", strip=True) == "Search"
        assert search_label.select_one(
            "input[data-store-section-master-search]"
        ).get("placeholder") == "Store Section name"
        inline_create = soup.select_one("#storeSectionMasterInlineCreatePanel")
        add_shortcuts = soup.select(
            "button[data-store-section-master-add-shortcut]"
        )
        assert len(add_shortcuts) == 2
        assert all(shortcut.get("type") == "button" for shortcut in add_shortcuts)
        assert all(shortcut.find_parent("form") is None for shortcut in add_shortcuts)
        assert all(
            shortcut.get("aria-controls") == inline_create.get("id")
            for shortcut in add_shortcuts
        )
        assert all(
            shortcut.get("aria-expanded") == "false"
            for shortcut in add_shortcuts
        )
        assert all(
            shortcut.get_text(" ", strip=True) == "Add Store Section"
            for shortcut in add_shortcuts
        )
        assert soup.select_one(".store-section-master-header-add") == add_shortcuts[0]
        assert soup.select_one(".store-section-master-stats") is None
        assert soup.select_one("#storeSectionMasterCreatePanel") is None
        assert "Workspace setup" not in soup.get_text(" ", strip=True)
        assert soup.select_one(".store-section-master-header-summary") is not None
        category_list = soup.select_one(
            ".unit-master-category-list.store-section-master-category-list"
        )
        assert category_list is not None
        category = next(
            child
            for child in category_list.children
            if getattr(child, "name", None) == "section"
        )
        assert {
            "unit-master-category",
            "store-section-master-category",
        }.issubset(category.get("class", []))
        table = category.select_one(".store-section-master-table")
        assert table is not None
        assert table.get("aria-colcount") == "6"
        assert [
            header.get_text(" ", strip=True)
            for header in table.select('[role="columnheader"]')
        ] == ["Order", "Icon", "Display Name", "Used in", "Source", "Action"]
        add_shortcut = category.select_one(
            "button[data-store-section-master-add-shortcut]"
        )
        assert add_shortcut is not None
        assert inline_create is not None
        assert add_shortcut.get("type") == "button"
        assert add_shortcut.find_parent("form") is None
        assert add_shortcut.get("aria-controls") == inline_create.get("id")
        assert add_shortcut.get("aria-expanded") == "false"
        assert add_shortcut.get_text(" ", strip=True) == "Add Store Section"
        assert inline_create.has_attr("hidden")
        assert inline_create.name == "form"
        assert {
            "store-section-master-row",
            "store-section-master-create-row",
        }.issubset(inline_create.get("class", []))
        assert inline_create.find_parent(
            "div",
            class_="store-section-master-list",
        ) is not None
        assert inline_create.find_next_sibling() is None
        assert not inline_create.has_attr("data-store-section-master-row")
        assert [
            cell.get("data-store-section-master-cell")
            for cell in inline_create.select("[data-store-section-master-cell]")
        ] == ["order", "icon", "section", "usage", "source", "actions"]
        inline_order = inline_create.select_one(
            ".store-section-master-order-step"
        )
        section_count = len(
            master_data.ingredient_store_section_details(
                "user-a",
                include_inactive=True,
            )
        )
        assert inline_order.get_text(" ", strip=True) == str(section_count + 1)
        assert inline_create.select_one(
            ".store-section-master-type > .is-custom"
        ).get_text(" ", strip=True) == "User-created"
        assert [
            button.get_text(" ", strip=True)
            for button in inline_create.select(".store-section-master-usage-button")
        ] == ["0 ingredients", "0 recipe refs"]
        assert inline_create.select_one(
            '.store-section-master-actions > button[type="submit"]'
        ).get_text(" ", strip=True) == "Save"
        cancel_buttons = inline_create.select(
            'button[type="button"][data-store-section-master-create-cancel]'
        )
        assert len(cancel_buttons) == 2
        assert inline_create.select_one(
            ".store-section-master-actions "
            "> button[data-store-section-master-create-cancel]"
        ).get_text(" ", strip=True) == "Cancel"
        assert inline_create.select_one(
            ".store-section-master-mobile-cancel"
        ).get("aria-label") == "Cancel new Store Section"
        assert inline_create.select_one(
            '#storeSectionMasterInlineCreateName[name="display_name"]'
        ) is not None
        assert inline_create.select_one(
            'input[name="return_to_created"][value="1"]'
        ) is not None
        assert soup.select_one("#storeSectionMasterCreateName") is None
        assert soup.select_one("[data-store-section-master-status-filter]") is None
        assert soup.select_one("[data-store-section-master-columns-trigger]") is None
        bakery_row = html.split('data-store-section-key="bakery"', 1)[1].split("</form>", 1)[0]
        assert 'value="archive"' not in bakery_row
        assert 'value="restore"' not in bakery_row
        assert 'data-store-section-is-built-in="true"' in bakery_row
        assert "The built-in section identity and automatic routing stay unchanged." in bakery_row
        assert "store-section-master-mobile-kind" not in bakery_row
        assert "Built-in" in bakery_row
        assert 'value="delete"' not in bakery_row

        created = client.post(
            "/admin/master-data/store-sections",
            data={"display_name": "International Foods", "icon": "basket"},
            follow_redirects=True,
        )
        assert created.status_code == 200
        created_html = created.get_data(as_text=True)
        assert "Store Section created: International Foods." in created_html
        custom_row = created_html.split(
            'data-store-section-key="international foods"',
            1,
        )[1].split("</form>", 1)[0]
        assert 'value="archive"' not in custom_row
        assert 'value="restore"' not in custom_row
        custom_delete_attributes = custom_row.split('value="delete"', 1)[1].split(">", 1)[0]
        assert "disabled" not in custom_delete_attributes
        assert "Permanently delete International Foods" in custom_delete_attributes
        assert 'data-store-section-is-built-in="false"' in custom_row
        assert "store-section-master-mobile-kind" in custom_row
        assert '<span class="is-custom">User-created</span>' in custom_row
        section = next(
            item
            for item in master_data.ingredient_store_section_details(
                "user-a",
                include_inactive=True,
            )
            if item["section_key"] == "INTERNATIONAL FOODS"
        )

        updated = client.post(
            f"/admin/master-data/store-sections/{section['id']}",
            data={
                "action": "save",
                "display_name": "Global Foods",
                "icon": "heart",
            },
            follow_redirects=True,
        )
        assert updated.status_code == 200
        assert "Store Section updated: Global Foods." in updated.get_data(as_text=True)

        moved = client.post(
            f"/admin/master-data/store-sections/{section['id']}",
            data={"action": "move_to", "position": "1"},
            headers={
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
        )
        assert moved.status_code == 200
        assert moved.get_json()["ok"] is True
        assert moved.get_json()["position"] == 1
        reordered = master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
        )
        assert reordered[0]["id"] == section["id"]

        sign_in(client, "user-b")
        other_workspace = client.get("/admin/master-data/store-sections")
        assert other_workspace.status_code == 200
        assert "Global Foods" not in other_workspace.get_data(as_text=True)


def test_inline_store_section_create_returns_to_new_bottom_row_and_can_delete(
    monkeypatch,
    tmp_path,
):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            "/admin/master-data/store-sections",
            data={
                "display_name": "Inline Test Section",
                "icon": "basket",
                "return_to_created": "1",
            },
        )

        assert response.status_code == 302
        location = urlsplit(response.headers["Location"])
        assert location.path == "/admin/master-data/store-sections"
        assert location.fragment.startswith("storeSectionMasterRow-")

        created_page = client.get(response.headers["Location"])
        created_soup = BeautifulSoup(created_page.get_data(as_text=True), "html.parser")
        created_row = created_soup.select_one(f"#{location.fragment}")
        assert created_row is not None
        assert created_row.get("data-store-section-name") == "inline test section"
        assert created_row == created_soup.select(
            ".store-section-master-list [data-store-section-master-row]"
        )[-1]

        section_id = int(location.fragment.rsplit("-", 1)[1])
        deleted = client.post(
            f"/admin/master-data/store-sections/{section_id}",
            data={"action": "delete"},
            headers={
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
        )

    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True


def test_store_section_fetch_create_and_save_return_json_without_redirecting(
    monkeypatch,
    tmp_path,
):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    fetch_headers = {
        "Accept": "application/json",
        "X-Requested-With": "fetch",
    }

    with app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/admin/master-data/store-sections",
            data={
                "display_name": "Silent Save Test Section",
                "icon": "basket",
                "return_to_created": "1",
            },
            headers=fetch_headers,
        )

        assert created.status_code == 201
        assert "Location" not in created.headers
        created_result = created.get_json()
        assert created_result["ok"] is True
        assert created_result["display_name"] == "Silent Save Test Section"
        section_id = int(created_result["id"])
        with client.session_transaction() as session:
            assert "recipe_master_data_messages" not in session

        saved = client.post(
            f"/admin/master-data/store-sections/{section_id}",
            data={
                "action": "save",
                "display_name": "Silent Save Test Section Updated",
                "icon": "heart",
            },
            headers=fetch_headers,
        )

        assert saved.status_code == 200
        assert "Location" not in saved.headers
        assert saved.get_json() == {
            "changed": True,
            "display_name": "Silent Save Test Section Updated",
            "ok": True,
            "status": 200,
        }

        refreshed_page = client.get("/admin/master-data/store-sections")
        refreshed_soup = BeautifulSoup(
            refreshed_page.get_data(as_text=True),
            "html.parser",
        )
        saved_row = refreshed_soup.select_one(f"#storeSectionMasterRow-{section_id}")
        assert saved_row is not None
        assert saved_row.get("data-store-section-name") == (
            "silent save test section updated"
        )

        deleted = client.post(
            f"/admin/master-data/store-sections/{section_id}",
            data={"action": "delete"},
            headers=fetch_headers,
        )

    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True


def test_builtin_store_section_edit_preserves_identity_and_routing(monkeypatch, tmp_path):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    produce = next(
        section
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
            create=True,
        )
        if section["section_key"] == "PRODUCE"
    )
    original_sort_order = produce["sort_order"]
    original_classification = master_data.classify_ingredient_store_section("fresh carrots")

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            f"/admin/master-data/store-sections/{produce['id']}",
            data={
                "action": "save",
                "display_name": "Fresh Produce",
                "icon": "heart",
                "section_key": "HACKED",
                "is_builtin": "0",
                "is_active": "0",
                "routing": "manual",
            },
            follow_redirects=True,
        )
        archive_response = client.post(
            f"/admin/master-data/store-sections/{produce['id']}",
            data={"action": "archive"},
            headers={
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
        )

    assert response.status_code == 200
    assert "Store Section updated: Fresh Produce." in response.get_data(as_text=True)
    updated = next(
        section
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
        )
        if section["id"] == produce["id"]
    )
    assert updated["display_name"] == "Fresh Produce"
    assert updated["icon"] == "heart"
    assert updated["section_key"] == "PRODUCE"
    assert updated["is_builtin"] is True
    assert updated["is_active"] is True
    assert updated["sort_order"] == original_sort_order
    assert master_data.clean_ingredient_store_section(
        "Fresh Produce",
        user_id="user-a",
    ) == "PRODUCE"
    assert master_data.classify_ingredient_store_section("fresh carrots") == (
        original_classification
    )
    assert archive_response.status_code == 409
    assert (
        archive_response.get_json()["error"]
        == "Store Sections are always active."
    )


def test_store_section_usage_route_lists_records_and_is_workspace_scoped(
    monkeypatch,
    tmp_path,
):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    monkeypatch.setattr(
        master_data,
        "recipe_reference_metadata",
        lambda _user_id: {
            "https://example.com/produce-salad": {
                "name": "Produce Salad",
                "url": "https://example.com/produce-salad",
                "cover_image": {"src": "/static/generated/produce-salad.jpg"},
            },
        },
    )
    monkeypatch.setattr(
        main_routes,
        "recipe_cover_image_for_view",
        lambda *_args, **_kwargs: {
            "thumb_url": "/static/generated/produce-salad-thumb.jpg",
            "detail_url": "/static/generated/produce-salad-detail.jpg",
            "srcset": (
                "/static/generated/produce-salad-thumb.jpg 320w, "
                "/static/generated/produce-salad-detail.jpg 960w"
            ),
            "alt": "Produce Salad cover",
        },
    )
    master_data.sync_recipe_master_records(
        "https://example.com/produce-salad",
        recipe_data={
            "ingredients": [
                {
                    "ingredient": "Tomato",
                    "ingredient_image_url": "/static/generated/tomato.jpg",
                    "store_section": "Produce",
                },
                {"ingredient": "Basil", "store_section": "Produce"},
            ],
        },
        user_id="user-a",
    )
    produce = next(
        section
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
            create=True,
        )
        if section["section_key"] == "PRODUCE"
    )

    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            f"/api/master-data/store-sections/{produce['id']}/usage"
        )
        sign_in(client, "user-b")
        foreign_response = client.get(
            f"/api/master-data/store-sections/{produce['id']}/usage"
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["section"]["section_key"] == "PRODUCE"
    assert payload["ingredient_total"] == 2
    assert payload["recipe_reference_total"] == 2
    assert payload["recipe_total"] == 1
    assert all(item["manage_url"] for item in payload["ingredients"])
    tomato = next(
        item for item in payload["ingredients"] if item["name"] == "Tomato"
    )
    assert tomato["image_url"] == "/static/generated/tomato.jpg"
    assert payload["recipes"][0]["edit_url"]
    assert payload["recipes"][0]["reference_count"] == 2
    assert payload["recipes"][0]["recipe_title"] == "Produce Salad"
    assert (
        payload["recipes"][0]["recipe_image_url"]
        == "/static/generated/produce-salad-thumb.jpg"
    )
    assert (
        payload["recipes"][0]["recipe_image_full_url"]
        == "/static/generated/produce-salad-detail.jpg"
    )
    assert payload["recipes"][0]["recipe_image_alt"] == "Produce Salad cover"
    assert foreign_response.status_code == 404


def test_store_section_archive_restore_fetch_is_rejected_without_flash_message(
    monkeypatch,
    tmp_path,
):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    created = master_data.create_ingredient_store_section(
        "Seasonal",
        "basket",
        user_id="user-a",
    )
    assert created["ok"] is True
    master_data.sync_recipe_master_records(
        "https://example.com/seasonal-cider",
        recipe_data={
            "ingredients": [{
                "ingredient": "Seasonal cider",
                "store_section": "Seasonal",
                "store_section_custom": True,
            }]
        },
        user_id="user-a",
    )

    with app.test_client() as client:
        sign_in(client, "user-a")
        archive_response = client.post(
            f"/admin/master-data/store-sections/{created['id']}",
            data={"action": "archive"},
            headers={
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
        )
        with client.session_transaction() as session:
            assert "recipe_master_data_messages" not in session
        archived_snapshot = next(
            section
            for section in master_data.ingredient_store_section_details(
                "user-a",
                include_inactive=True,
                create=True,
            )
            if section["id"] == created["id"]
        )
        restore_response = client.post(
            f"/admin/master-data/store-sections/{created['id']}",
            data={"action": "restore"},
            headers={
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
        )
        with client.session_transaction() as session:
            assert "recipe_master_data_messages" not in session
        plain_archive_response = client.post(
            f"/admin/master-data/store-sections/{created['id']}",
            data={"action": "archive"},
        )
        plain_restore_response = client.post(
            f"/admin/master-data/store-sections/{created['id']}",
            data={"action": "restore"},
        )
        with client.session_transaction() as session:
            assert "recipe_master_data_messages" not in session

    assert archive_response.status_code == 409
    assert archive_response.get_json() == {
        "ok": False,
        "error": "Store Sections are always active.",
        "status": 409,
    }
    assert archived_snapshot["is_active"] is True
    assert archived_snapshot["recipe_reference_count"] == 1
    assert restore_response.status_code == 409
    assert restore_response.get_json() == {
        "ok": False,
        "error": "Store Sections are always active.",
        "status": 409,
    }
    assert plain_archive_response.status_code == 409
    assert plain_archive_response.get_json() == archive_response.get_json()
    assert plain_restore_response.status_code == 409
    assert plain_restore_response.get_json() == restore_response.get_json()
    restored = next(
        section
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
            create=True,
        )
        if section["id"] == created["id"]
    )
    assert restored["is_active"] is True


def test_store_section_delete_is_custom_only_and_requires_no_usage(
    monkeypatch,
    tmp_path,
):
    app, _db_path, _users_root = configure_master_data_app(monkeypatch, tmp_path)
    unused = master_data.create_ingredient_store_section(
        "Unused Seasonal",
        "basket",
        user_id="user-a",
    )
    used = master_data.create_ingredient_store_section(
        "Used Seasonal",
        "basket",
        user_id="user-a",
    )
    assert unused["ok"] is True
    assert used["ok"] is True
    master_data.sync_recipe_master_records(
        "https://example.com/seasonal-cider",
        recipe_data={
            "ingredients": [
                {
                    "ingredient": "Seasonal cider",
                    "store_section": "Used Seasonal",
                },
            ],
        },
        user_id="user-a",
    )
    used_section_key = master_data.clean_ingredient_store_section(
        "Used Seasonal",
        user_id="user-a",
    )
    assert used_section_key == "USED SEASONAL"
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE ingredients
               SET store_section = ?
             WHERE user_id = ?
               AND normalized_name = ?
            """,
            (used_section_key, "user-a", "seasonal cider"),
        )
        connection.execute(
            """
            UPDATE recipe_ingredients
               SET store_section = ?
             WHERE user_id = ?
               AND normalized_name = ?
            """,
            (used_section_key, "user-a", "seasonal cider"),
        )
    produce = next(
        section
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
            create=True,
        )
        if section["section_key"] == "PRODUCE"
    )
    headers = {
        "Accept": "application/json",
        "X-Requested-With": "fetch",
    }

    with app.test_client() as client:
        sign_in(client, "user-a")
        page = client.get("/admin/master-data/store-sections").get_data(as_text=True)
        used_row = page.split(
            'data-store-section-key="used seasonal"',
            1,
        )[1].split("</form>", 1)[0]
        used_delete_attributes = used_row.split(
            'value="delete"',
            1,
        )[1].split(">", 1)[0]
        assert 'value="archive"' not in used_row
        assert 'value="restore"' not in used_row
        built_in_response = client.post(
            f"/admin/master-data/store-sections/{produce['id']}",
            data={"action": "delete"},
            headers=headers,
        )
        used_response = client.post(
            f"/admin/master-data/store-sections/{used['id']}",
            data={"action": "delete"},
            headers=headers,
        )
        delete_response = client.post(
            f"/admin/master-data/store-sections/{unused['id']}",
            data={"action": "delete"},
            headers=headers,
        )

    assert "disabled" in used_delete_attributes
    assert built_in_response.status_code == 409
    assert (
        built_in_response.get_json()["error"]
        == "Built-in Store Sections cannot be deleted."
    )
    assert used_response.status_code == 409
    assert (
        used_response.get_json()["error"]
        == (
            "Reassign this Store Section's master ingredients and "
            "recipe references before deleting it."
        )
    )
    assert used_response.get_json()["ingredient_count"] == 1
    assert used_response.get_json()["recipe_reference_count"] == 1
    assert delete_response.status_code == 200
    assert delete_response.get_json()["ok"] is True
    assert delete_response.get_json()["deleted"] is True
    remaining_ids = {
        section["id"]
        for section in master_data.ingredient_store_section_details(
            "user-a",
            include_inactive=True,
            create=True,
        )
    }
    assert unused["id"] not in remaining_ids
    assert used["id"] in remaining_ids
    assert produce["id"] in remaining_ids


def test_store_section_manager_uses_compact_registry_and_preserves_interactions():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    store_section_table_script = script.split(
        "function initStoreSectionMasterTable()",
        1,
    )[1].split("function initStoreSectionMasterUsageDialog()", 1)[0]
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    template = Path("PushShoppingList/templates/master_data.html").read_text(
        encoding="utf-8",
    )
    page = Path("PushShoppingList/templates/store_sections.html").read_text(
        encoding="utf-8",
    )

    assert "Manage Store Sections" in script
    assert 'masterDataViewerUrl("/admin/master-data/store-sections")' in script
    assert 'href="/admin/master-data/store-sections"' not in script
    assert "Store Sections" in template
    assert "store_section_url" in template

    soup = BeautifulSoup(page, "html.parser")
    category_list = soup.select_one(
        ".unit-master-category-list.store-section-master-category-list"
    )
    assert category_list is not None
    category = next(
        child
        for child in category_list.children
        if getattr(child, "name", None) == "section"
    )
    assert {
        "unit-master-category",
        "store-section-master-category",
    }.issubset(category.get("class", []))
    table = category.select_one(".store-section-master-table")
    assert table is not None
    assert table.get("aria-colcount") == "6"
    assert [
        (
            header.get("data-store-section-master-column"),
            header.get_text(" ", strip=True),
            header.get("aria-colindex"),
        )
        for header in table.select("[data-store-section-master-column]")
    ] == [
        ("order", "Order", "1"),
        ("icon", "Icon", "2"),
        ("section", "Display Name", "3"),
        ("usage", "Used in", "4"),
        ("source", "Source", "5"),
        ("actions", "Action", "6"),
    ]
    expected_cells = ["order", "icon", "section", "usage", "source", "actions"]
    saved_row = table.select_one("[data-store-section-master-row]")
    draft_row = table.select_one("#storeSectionMasterInlineCreatePanel")
    assert saved_row is not None
    assert draft_row is not None
    assert [
        cell.get("data-store-section-master-cell")
        for cell in saved_row.select("[data-store-section-master-cell]")
    ] == expected_cells
    assert [
        cell.get("data-store-section-master-cell")
        for cell in draft_row.select("[data-store-section-master-cell]")
    ] == expected_cells
    assert not draft_row.has_attr("data-store-section-master-row")

    assert "Add Store Section" in page
    assert "store-section-master-title-count" in page
    assert "data-store-section-master-count" in page
    assert "master ingredients" in page
    assert "recipe references" in page
    assert "store-section-master-header-summary" in page
    assert "store-section-master-stats" not in page
    assert "storeSectionMasterCreatePanel" not in page
    assert "Workspace setup" not in page
    assert "Active sections" not in page
    assert "Archived sections" not in page
    assert "data-store-section-master-active-count" not in page
    assert "data-store-section-master-archived-count" not in page
    assert "data-store-section-master-status-filter" not in page
    assert "data-store-section-master-columns-trigger" not in page
    assert "data-store-section-master-columns-fit" not in page
    assert 'data-store-section-master-column="status"' not in page
    assert 'data-store-section-master-cell="status"' not in page
    assert 'value="archive"' not in page
    assert 'value="restore"' not in page

    assert "data-store-section-master-search" in page
    assert "Store Section Registry" in page
    assert "store-section-master-search-label" in page
    assert 'placeholder="Store Section name"' in page
    assert "data-store-section-master-mobile-save" in page
    assert "data-store-section-master-mobile-details-toggle" in page
    assert "data-store-section-master-mobile-details" in page
    assert "store-section-master-mobile-order-controls" in page
    assert page.count('value="move_up"') == 2
    assert page.count('value="move_down"') == 2
    assert 'data-mobile-label="Used in"' in page
    assert 'data-mobile-label="Source"' in page
    assert 'data-mobile-label="Action"' in page
    assert "Built-in" in page
    assert "User-created" in page
    assert "data-store-section-master-usage-open" in page
    assert "data-store-section-master-usage-dialog" in page
    assert "data-store-section-master-usage-tab" in page
    assert "data-store-section-master-usage-search" in page
    assert "data-store-section-master-drag-handle" in page
    assert 'value="save"' in page
    assert 'value="delete"' in page
    assert "{% if not section.is_builtin %}" in page
    assert "data-store-section-master-icon-picker" in page
    assert "data-store-section-master-icon-option" in page

    assert "function initStoreSectionMasterTable()" in script
    assert "function initStoreSectionMasterIconPickers()" in script
    assert "function initStoreSectionMasterUsageDialog()" in script
    assert 'const primaryColumns = ["order", "icon", "section"];' in script
    assert 'const detailColumns = ["usage", "source", "actions"];' in script
    assert 'table.setAttribute("role", desktop ? "table" : "list");' in script
    assert 'table.setAttribute("aria-colcount", "6");' in script
    assert 'table.removeAttribute("aria-colcount");' in script
    assert 'row.setAttribute("role", "listitem");' in script
    assert 'cell.setAttribute("role", "group");' in script
    assert 'cell.setAttribute("aria-label", mobileColumnLabels[key]);' in script
    assert "STORE_SECTION_MASTER_COLUMN_STORAGE_KEY" not in script
    assert "STORE_SECTION_MASTER_COLUMN_ORDER" not in script
    assert "storeSectionMasterColumnResize" not in script
    assert "localStorage" not in store_section_table_script
    assert "detailsPanel.append(cell)" in script
    assert 'row.querySelectorAll(\'button[value="move_up"]\')' in script
    assert 'row.querySelectorAll(\'button[value="move_down"]\')' in script
    assert 'action: "move_to"' in script
    assert "persistRowPosition" in script
    assert "moveRowByOrderControl" in script
    assert 'if (["move_up", "move_down"].includes(action)) {' in script
    assert 'const direction = action === "move_up" ? -1 : 1;' in script
    assert "storeSectionMasterOrderPending" in script
    assert "button.offsetWidth || button.offsetHeight || button.getClientRects().length" in script
    assert "const setMobileDetailsExpanded = (row, expanded, options = {}) => {" in script
    assert "const updateRowDirtyState = () => {" in script
    assert "row.requestSubmit(saveButton)" in script
    assert 'if (action !== "delete") return;' in script
    assert "row.remove()" in script
    assert "applyFilters()" in store_section_table_script
    assert 'visibleCount.textContent = "Showing "' in store_section_table_script
    assert '+ " Store Sections";' in store_section_table_script
    assert "window.location.reload()" not in store_section_table_script
    assert '"archive"' not in store_section_table_script
    assert '"restore"' not in store_section_table_script

    assert ".store-section-master-title-count {" in css
    assert ".store-section-master-header-summary {" in css
    assert ".store-section-master-header-actions {" in css
    assert ".store-section-master-header-add {" in css
    assert ".store-section-master-search-label {" in css
    assert ".store-section-master-search-control {" in css
    store_heading_alignment_rules = css.rsplit(
        ".store-section-master-page .master-data-header h1,",
        1,
    )[1].split("}", 1)[0]
    assert "text-align: left;" in store_heading_alignment_rules
    for layout_property in (
        "display:",
        "position:",
        "margin:",
        "padding:",
        "width:",
        "transform:",
        "grid-",
        "flex-",
    ):
        assert layout_property not in store_heading_alignment_rules
    assert ".store-section-master-category-list," in css
    assert ".store-section-master-category {" in css
    store_header_rules = css.rsplit(
        ".store-section-master-category .store-section-master-table-head {",
        1,
    )[1].split("}", 1)[0]
    assert "position: sticky;" in store_header_rules
    assert "z-index: 20;" in store_header_rules
    assert (
        "top: calc(-1 * var(--app-content-padding-block-start));"
        in store_header_rules
    )
    assert "min-height: 0;" in store_header_rules
    assert "padding: 10px 14px;" in store_header_rules
    assert "border-bottom: 1px solid var(--app-border);" in store_header_rules
    assert "background: var(--app-surface);" in store_header_rules
    assert "color: var(--app-muted);" in store_header_rules
    assert "font-size: 12px;" in store_header_rules
    assert "font-weight: 850;" in store_header_rules
    assert "letter-spacing: .03em;" in store_header_rules
    assert "text-transform: uppercase;" in store_header_rules
    store_header_cell_rules = css.rsplit(
        ".store-section-master-category .store-section-master-table-head\n"
        "    > [data-store-section-master-column] {",
        1,
    )[1].split("}", 1)[0]
    assert "color: inherit;" in store_header_cell_rules
    assert "font: inherit;" in store_header_cell_rules
    assert "letter-spacing: inherit;" in store_header_cell_rules
    assert "line-height: inherit;" in store_header_cell_rules
    assert "text-align: left;" in store_header_cell_rules
    assert "text-transform: inherit;" in store_header_cell_rules
    assert (
        "grid-template-columns: 116px 46px minmax(180px, 1fr) "
        "104px 92px 112px;"
    ) in css
    assert "@media (min-width: 1641px) and (max-width: 1850px)" in css
    assert (
        "grid-template-columns: 96px 42px minmax(130px, 1fr) "
        "82px 82px 108px;"
    ) in css
    assert "@media (max-width: 1640px)" in css
    assert ".store-section-master-columns," in css
    assert ".store-section-master-column-resize," in css
    assert "display: none !important;" in css
    assert ".store-section-master-mobile-order-controls" in css
    assert '.store-section-master-mobile-order-controls > button[value="move_up"]' in css
    assert '.store-section-master-mobile-order-controls > button[value="move_down"]' in css
    assert (
        ".store-section-master-create-form\n"
        "        > :is(label, .store-section-master-icon-field, button)"
        in css
    )
    assert ".store-section-master-mobile-details[hidden]" in css
    assert ".is-row-drop-before" in css
    assert ".store-section-master-usage-button" in css
    assert ".store-section-master-usage-dialog" in css
    assert ".store-section-master-icon-menu" in css




def test_store_section_icon_picker_matches_recipe_table_dropdown_chrome():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    page = Path("PushShoppingList/templates/store_sections.html").read_text(
        encoding="utf-8",
    )

    assert '{% import "includes/app_shell_macros.html" as shell %}' in page
    assert 'role="combobox"' in page
    assert 'shell.svg_icon("chevron-down")' in page
    assert 'shell.svg_icon("check")' in page
    assert "grid-template-columns: 16px minmax(0, 1fr) 14px;" in css
    assert "> [data-store-section-master-icon-label]" in css
    assert ".store-section-master-row .store-section-master-icon-chevron" in css
    assert "opacity: 0;" in css
    assert (
        ".store-section-master-icon-trigger:is(:hover, :focus-visible)"
        in css
    )
    assert "grid-template-columns: 17px minmax(0, 1fr) 16px;" in css
    assert "const menuWidth = Math.max(220, rect.width);" in script


def test_store_section_manager_add_shortcuts_target_single_inline_create_form():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    page = Path("PushShoppingList/templates/store_sections.html").read_text(
        encoding="utf-8",
    )

    soup = BeautifulSoup(page, "html.parser")
    create_panel = soup.select_one("#storeSectionMasterInlineCreatePanel")
    create_name = soup.select_one("#storeSectionMasterInlineCreateName")
    shortcuts = soup.select("button[data-store-section-master-add-shortcut]")
    assert create_panel is not None
    assert create_name is not None
    assert len(shortcuts) == 2
    assert all(shortcut.get("type") == "button" for shortcut in shortcuts)
    assert all(shortcut.find_parent("form") is None for shortcut in shortcuts)
    assert all(
        shortcut.get("aria-controls") == create_panel.get("id")
        for shortcut in shortcuts
    )
    assert shortcuts[0].find_parent("header", class_="master-data-header")
    assert shortcuts[1].find_parent(
        "section", class_="store-section-master-category"
    )
    assert shortcuts[1].find_previous(class_="store-section-master-table") is not None
    assert create_panel.has_attr("hidden")
    assert create_panel.name == "form"
    assert {
        "store-section-master-row",
        "store-section-master-create-row",
    }.issubset(create_panel.get("class", []))
    assert create_panel.find_parent(
        "div",
        class_="store-section-master-list",
    ) is not None
    assert create_panel.find_next_sibling() is None
    assert not create_panel.has_attr("data-store-section-master-row")
    assert [
        cell.get("data-store-section-master-cell")
        for cell in create_panel.select("[data-store-section-master-cell]")
    ] == ["order", "icon", "section", "usage", "source", "actions"]
    assert create_panel.select_one(
        ".store-section-master-type > .is-custom"
    ).get_text(" ", strip=True) == "User-created"
    assert create_panel.select_one(
        '.store-section-master-actions > button[type="submit"]'
    ).get_text(" ", strip=True) == "Save"
    cancel_buttons = create_panel.select(
        'button[type="button"][data-store-section-master-create-cancel]'
    )
    assert len(cancel_buttons) == 2
    assert create_panel.select_one(
        ".store-section-master-actions "
        "> button[data-store-section-master-create-cancel]"
    ).get_text(" ", strip=True) == "Cancel"
    assert create_panel.select_one(
        ".store-section-master-mobile-cancel"
    ).get("aria-label") == "Cancel new Store Section"

    assert "function initStoreSectionMasterAddShortcut(page, announce = () => {})" in script
    assert 'page?.querySelector("#storeSectionMasterInlineCreatePanel")' in script
    assert 'page?.querySelector("#storeSectionMasterInlineCreateName")' in script
    assert 'page?.querySelectorAll("[data-store-section-master-add-shortcut]")' in script
    assert "event.preventDefault();" in script
    assert "createPanel.hidden = false;" in script
    assert 'button.setAttribute("aria-expanded", "true");' in script
    assert "createNameInput.focus({ preventScroll: true });" in script
    assert 'createPanel.scrollIntoView({ block: "nearest", inline: "nearest" });' in script
    shortcut_script = script[
        script.index("function initStoreSectionMasterAddShortcut("):
        script.index("function initStoreSectionMasterTable()")
    ]
    assert "#storeSectionMasterCreatePanel" not in shortcut_script
    assert 'block: "center"' not in shortcut_script
    assert "storeSectionMasterBottomViewportInset()" in shortcut_script
    assert "initStoreSectionMasterAddShortcut(page, announce);" in script

    table_script = script[
        script.index("function initStoreSectionMasterTable()"):
        script.index("function initStoreSectionMasterUsageDialog()")
    ]
    inline_submit_handler = table_script[
        table_script.index('if (event.target === inlineCreate) {'):
        table_script.index('if (["move_up", "move_down"].includes(action))')
    ]
    assert "event.preventDefault();" in inline_submit_handler
    assert "await saveInlineStoreSectionMasterRow(submitter);" in inline_submit_handler
    assert "window.location" not in inline_submit_handler
    assert "location.reload" not in inline_submit_handler
    assert "requestSubmit" not in inline_submit_handler

    inline_save_helper = table_script[
        table_script.index("const saveInlineStoreSectionMasterRow = async"):
        table_script.index('list.addEventListener("submit"')
    ]
    assert 'Accept: "application/json"' in inline_save_helper
    assert '"X-Requested-With": "fetch"' in inline_save_helper
    assert "list.insertBefore(savedRow, inlineCreate);" in inline_save_helper
    assert "updateRowOrderControls();" in inline_save_helper
    assert "inlineCreate.hidden = true;" in inline_save_helper
    inline_save_success = inline_save_helper.split("} catch (error) {", 1)[0]
    assert "focus({ preventScroll: true })" not in inline_save_success
    assert "nameInput?.focus({ preventScroll: true });" in inline_save_helper
    assert "window.location" not in inline_save_helper
    assert "location.reload" not in inline_save_helper
    assert "location.hash" not in inline_save_helper

    inline_cancel_helper = table_script[
        table_script.index("const cancelInlineStoreSectionMasterRow = () => {"):
        table_script.index('list.addEventListener("submit"')
    ]
    assert "inlineCreate.reset();" in inline_cancel_helper
    assert 'inlineCreate.style.scrollMarginBottom = "";' in inline_cancel_helper
    assert "inlineCreate.hidden = true;" in inline_cancel_helper
    assert 'button.setAttribute("aria-expanded", "false");' in inline_cancel_helper
    assert "bottomAddShortcut?.focus({ preventScroll: true });" in inline_cancel_helper
    assert 'announce("New Store Section discarded.");' in inline_cancel_helper
    assert "fetch(" not in inline_cancel_helper
    assert "requestSubmit" not in inline_cancel_helper
    assert 'list.addEventListener("click"' in inline_cancel_helper
    assert '"[data-store-section-master-create-cancel]"' in inline_cancel_helper

    persisted_save_handler = table_script[
        table_script.index('if (action === "save") {'):
        table_script.index('if (action !== "delete") return;')
    ]
    assert "event.preventDefault();" in persisted_save_handler
    assert "await saveStoreSectionMasterRow(row, submitter);" in persisted_save_handler

    persisted_save_helper = table_script[
        table_script.index("const saveStoreSectionMasterRow = async"):
        table_script.index("const saveInlineStoreSectionMasterRow = async")
    ]
    persisted_save_success = persisted_save_helper.split("} catch (error) {", 1)[0]
    assert "focus({ preventScroll: true })" not in persisted_save_success
    assert "nameInput?.focus({ preventScroll: true });" in persisted_save_helper

    assert ".store-section-master-add-footer {" in css
    assert ".store-section-master-add-shortcut {" in css
    assert "padding: 12px 16px 16px;" in css
    add_footer_rules = css.rsplit(
        ".store-section-master-add-footer {",
        1,
    )[1].split("}", 1)[0]
    assert "overflow-anchor: none;" in add_footer_rules
    assert ".store-section-master-create-row" in css
    assert ".store-section-master-mobile-cancel" in css
    assert ".store-section-master-add-shortcut:hover {" in css
    assert ".store-section-master-add-shortcut:focus-visible {" in css
    assert ".store-section-master-add-shortcut:is(:hover, :focus-visible)" not in css
    shortcut_rules = css.rsplit(
        ".store-section-master-page .store-section-master-add-shortcut {",
        1,
    )[1].split("}", 1)[0]
    assert "width: 100%;" in shortcut_rules
    assert "border: 1px dashed" in shortcut_rules
    assert "background: transparent;" in shortcut_rules


def test_store_section_manager_bottom_add_shortcut_preserves_scroll_and_focuses_inline_input():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Store Section shortcut interaction test")

    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    helper = script[
        script.index("function storeSectionMasterBottomViewportInset("):
        script.index("function initStoreSectionMasterTable()")
    ]
    harness = helper + r"""
const listeners = [{}, {}];
const scrollCalls = [];
const announcements = [];
const interactionOrder = [];
const attributes = [{}, {}];
let focusOptions = null;
let focusCount = 0;
let preventDefaultCount = 0;
let submitCount = 0;
let panelRect = {top: 620, right: 760, bottom: 700, left: 220};
const body = {};
const scrollContainer = {
    parentElement: body,
    scrollTop: 920,
    getBoundingClientRect() {
        return {top: 120, right: 1100, bottom: 760, left: 180};
    },
};
const createPanel = {
    hidden: true,
    parentElement: scrollContainer,
    style: {},
    getBoundingClientRect() { return panelRect; },
    scrollIntoView(options) {
        scrollCalls.push(options);
        interactionOrder.push("scroll");
    },
};
const createNameInput = {
    focus(options) {
        focusOptions = options;
        focusCount += 1;
        document.activeElement = createNameInput;
        interactionOrder.push("focus");
    },
};
const addShortcuts = listeners.map((shortcutListeners, index) => ({
    form: {requestSubmit() { submitCount += 1; }},
    addEventListener(type, callback) { shortcutListeners[type] = callback; },
    setAttribute(name, value) { attributes[index][name] = value; },
}));
const nodes = new Map([
    ["#storeSectionMasterInlineCreatePanel", createPanel],
    ["#storeSectionMasterInlineCreateName", createNameInput],
]);
const page = {
    querySelector: selector => nodes.get(selector) || null,
    querySelectorAll: selector => selector === "[data-store-section-master-add-shortcut]"
        ? addShortcuts
        : [],
};
global.document = {
    activeElement: null,
    body,
    documentElement: {clientWidth: 1200, clientHeight: 800},
    querySelector: () => null,
};
global.window = {
    innerWidth: 1200,
    innerHeight: 800,
    scrollY: 740,
    getComputedStyle: () => ({overflow: "", overflowX: "visible", overflowY: "auto"}),
};

initStoreSectionMasterAddShortcut(page, message => {
    announcements.push(message);
    interactionOrder.push("announce");
});
const clickEvent = {preventDefault() { preventDefaultCount += 1; }};
listeners[0].click(clickEvent);
listeners[0].click(clickEvent);
const scrollCallsWhileVisible = [...scrollCalls];
panelRect = {top: 748, right: 760, bottom: 828, left: 220};
listeners[1].click(clickEvent);

console.log(JSON.stringify({
    registeredClicks: listeners.map(item => typeof item.click === "function"),
    focusedNameInput: document.activeElement === createNameInput,
    panelHidden: createPanel.hidden,
    ariaExpanded: attributes.map(item => item["aria-expanded"]),
    preventDefaultCount,
    submitCount,
    focusCount,
    focusOptions,
    scrollCallsWhileVisible,
    scrollCalls,
    windowScrollY: window.scrollY,
    nestedScrollTop: scrollContainer.scrollTop,
    announcements,
    interactionOrder,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert result == {
        "registeredClicks": [True, True],
        "focusedNameInput": True,
        "panelHidden": False,
        "ariaExpanded": ["true", "true"],
        "preventDefaultCount": 3,
        "submitCount": 0,
        "focusCount": 3,
        "focusOptions": {"preventScroll": True},
        "scrollCallsWhileVisible": [],
        "scrollCalls": [{"block": "nearest", "inline": "nearest"}],
        "windowScrollY": 740,
        "nestedScrollTop": 920,
        "announcements": [
            "Add Store Section form focused.",
            "Add Store Section form focused.",
            "Add Store Section form focused.",
        ],
        "interactionOrder": [
            "focus",
            "announce",
            "focus",
            "announce",
            "focus",
            "scroll",
            "announce",
        ],
    }


def test_store_section_order_column_uses_step_badges_without_duplicate_icons():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    page = Path("PushShoppingList/templates/store_sections.html").read_text(
        encoding="utf-8",
    )

    assert 'class="store-section-master-order-cell"' in page
    assert 'class="store-section-master-order-step"' in page
    assert "data-store-section-master-order-number" in page
    assert 'aria-label="Step {{ loop.index }}"' in page
    assert "data-store-section-master-row-icon" not in page
    assert ".store-section-master-order-step {" in css
    assert "border-radius: 50%;" in css
    assert (
        "> button:not(.store-section-master-drag-handle)"
        in css
    )
    assert ".store-section-master-row:is(:hover, :focus-within)" in css
    assert 'const primaryColumns = ["order", "icon", "section"];' in script
    assert 'row.querySelectorAll(\'button[value="move_up"]\')' in script
    assert 'row.querySelectorAll(\'button[value="move_down"]\')' in script
    assert "store-section-master-mobile-order-controls" in page
    assert '"[data-store-section-master-order-number]"' in script
    assert 'number.setAttribute("aria-label", "Step " + (index + 1));' in script


def test_store_section_usage_dialog_title_uses_the_selected_section_icon():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    page = Path("PushShoppingList/templates/store_sections.html").read_text(
        encoding="utf-8",
    )

    assert "data-store-section-master-usage-icon" in page
    assert "data-store-section-master-usage-title-text" in page
    assert "store-section-master-usage-title-icon" in page
    assert ".store-section-master-usage-title-icon {" in css
    assert "flex: 0 0 20px;" in css
    assert (
        'const titleIcon = dialog.querySelector("[data-store-section-master-usage-icon]");'
        in script
    )
    assert '"[data-store-section-master-icon-select]"' in script
    assert "renderStoreSectionMasterIconVisual(titleIcon, sectionIcon);" in script
    assert "titleText.textContent = `${sectionName} usage`;" in script
