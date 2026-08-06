import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from flask import session

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import unit_suggestion_service
from PushShoppingList.services import user_account_service
from PushShoppingList.services.ingredient_unit_service import canonical_unit
from PushShoppingList.services.ingredient_unit_service import normalize_ingredient_unit_fields


@pytest.fixture
def unit_registry_app(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({
            "users": [
                {
                    "user_id": "user-a",
                    "username": "user-a",
                    "email": "user-a@example.com",
                    "account_status": "active",
                },
                {
                    "user_id": "user-b",
                    "username": "user-b",
                    "email": "user-b@example.com",
                    "account_status": "active",
                },
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        master_data,
        "RECIPE_MASTER_DB_PATH",
        tmp_path / "recipe_master.sqlite3",
    )
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(user_account_service, "USERS_FILE", users_file)
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_DATA_DIR",
        tmp_path / "guests",
    )
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")

    app = create_app()
    app.config.update(TESTING=True)
    return app


def sign_in(client, user_id):
    with client.session_transaction() as active_session:
        active_session["user_id"] = user_id


def registry_for(client):
    response = client.get("/api/master-data/units")
    assert response.status_code == 200
    return response.get_json()["registry"]


def unit_named(registry, name):
    return next(unit for unit in registry["units"] if unit["name"] == name)


def test_create_unit_with_multiple_aliases_persists_and_reaches_editor_menu(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scoops", "sc"],
            },
        )
        assert created.status_code == 201
        payload = created.get_json()
        assert payload["ok"] is True
        assert unit_named(payload["registry"], "scoop")["aliases"] == ["sc", "scoops"]

    with unit_registry_app.test_client() as next_client:
        sign_in(next_client, "user-a")
        persisted = registry_for(next_client)
        assert unit_named(persisted, "scoop")["custom"] is True
        editor = next_client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "user-a",
                "url": "https://example.test/recipes/persistent-unit",
            },
        )
        assert editor.status_code == 200
        soup = BeautifulSoup(editor.get_data(as_text=True), "html.parser")
        editor_registry = json.loads(soup.select_one("#ingredientUnitConfig").string)
        assert unit_named(editor_registry, "scoop")["id"] == payload["unit_id"]
        assert editor_registry["aliases"]["sc"] == "scoop"


def test_edit_custom_name_and_add_remove_aliases_updates_normalization(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scoops", "scoopful"],
            },
        ).get_json()
        unit_id = created["unit_id"]
        edited = client.put(
            f"/api/master-data/units/{unit_id}",
            json={
                "canonical_name": "measuring scoop",
                "category": "volume",
                "aliases": ["scoops", "ms"],
            },
        )
        assert edited.status_code == 200
        unit = unit_named(edited.get_json()["registry"], "measuring scoop")
        assert unit["category"] == "volume"
        assert set(unit["aliases"]) == {"scoop", "scoops", "ms"}
        assert "scoopful" not in edited.get_json()["registry"]["aliases"]

        with unit_registry_app.test_request_context("/"):
            session["user_id"] = "user-a"
            normalized = normalize_ingredient_unit_fields({
                "ingredient": "protein powder",
                "quantity": "1",
                "unit": "ms",
            })
            assert normalized["unit"] == "measuring scoop"
            assert normalized["unit_id"] == unit_id

        removed = client.patch(
            f"/api/master-data/units/{unit_id}",
            json={
                "canonical_name": "measuring scoop",
                "category": "volume",
                "aliases": ["ms"],
            },
        ).get_json()
        assert unit_named(removed["registry"], "measuring scoop")["aliases"] == ["ms"]


def test_edit_seeded_unit_keeps_stable_id_and_migrates_recipe_references(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        registry = registry_for(client)
        teaspoon = unit_named(registry, "teaspoon")

        with unit_registry_app.test_request_context("/"):
            session["user_id"] = "user-a"
            master_data.sync_recipe_master_records(
                "https://example.test/recipes/seeded-rename",
                recipe_data={
                    "ingredients": [{
                        "ingredient": "salt",
                        "quantity": "1",
                        "unit": "teaspoon",
                    }],
                },
                user_id="user-a",
            )
            recipe_edit_service.save_recipe_output(
                "https://example.test/recipes/seeded-rename",
                {
                    "source_url": "https://example.test/recipes/seeded-rename",
                    "ingredients": [{
                        "ingredient": "salt",
                        "quantity": "1",
                        "unit": "teaspoon",
                        "unit_id": teaspoon["id"],
                    }],
                },
            )

        edited = client.put(
            f'/api/master-data/units/{teaspoon["id"]}',
            json={
                "canonical_name": "measuring teaspoon",
                "category": "volume",
                "aliases": ["tsp", "tsps", "teaspoons"],
            },
        )
        assert edited.status_code == 200
        renamed = unit_named(edited.get_json()["registry"], "measuring teaspoon")
        assert renamed["id"] == teaspoon["id"]
        assert renamed["seeded"] is True
        assert "teaspoon" in renamed["aliases"]

        with master_data.recipe_master_connection() as connection:
            stored = connection.execute(
                """
                SELECT unit, unit_id FROM recipe_ingredients
                 WHERE user_id = ? AND recipe_id = ?
                """,
                (
                    "user-a",
                    master_data.recipe_id_for_url(
                        "https://example.test/recipes/seeded-rename"
                    ),
                ),
            ).fetchone()
        assert stored["unit"] == "measuring teaspoon"
        assert stored["unit_id"] == teaspoon["id"]

        with unit_registry_app.test_request_context("/"):
            session["user_id"] = "user-a"
            assert canonical_unit("teaspoon")["name"] == "measuring teaspoon"
            assert canonical_unit("tsp")["id"] == teaspoon["id"]
            saved_recipe = recipe_edit_service.load_editable_recipe(
                "https://example.test/recipes/seeded-rename"
            )
            assert saved_recipe["recipe"]["ingredients"][0]["unit"] == "measuring teaspoon"
            assert saved_recipe["recipe"]["ingredients"][0]["unit_id"] == teaspoon["id"]

        refreshed = registry_for(client)
        assert unit_named(refreshed, "measuring teaspoon")["id"] == teaspoon["id"]


def test_collisions_and_repeated_submissions_do_not_create_duplicates(
    unit_registry_app,
):
    request_payload = {
        "canonical_name": "scoop",
        "category": "count_package",
        "aliases": ["scp", "scoops"],
    }
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        first = client.post("/api/master-data/units", json=request_payload)
        repeated = client.post("/api/master-data/units", json=request_payload)
        assert first.status_code == 201
        assert repeated.status_code == 200
        assert repeated.get_json()["created"] is False
        assert sum(
            unit["name"] == "scoop"
            for unit in repeated.get_json()["registry"]["units"]
        ) == 1

        canonical_collision = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "SCOOP",
                "category": "volume",
                "aliases": [],
            },
        )
        assert canonical_collision.status_code == 422
        assert "canonical_name" in canonical_collision.get_json()["errors"]

        alias_collision = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "ladle",
                "category": "volume",
                "aliases": ["scp"],
            },
        )
        assert alias_collision.status_code == 422
        assert alias_collision.get_json()["errors"]["aliases"]["0"]

        built_in_collision = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "pour",
                "category": "volume",
                "aliases": ["cup"],
            },
        )
        assert built_in_collision.status_code == 422

        duplicate_aliases = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "ladle",
                "category": "volume",
                "aliases": ["ld", "LD", ""],
            },
        )
        assert duplicate_aliases.status_code == 422
        assert set(duplicate_aliases.get_json()["errors"]["aliases"]) == {"1", "2"}


def test_registry_is_workspace_isolated_and_unit_routes_require_authorization(
    unit_registry_app,
):
    with unit_registry_app.test_client() as unauthenticated:
        denied = unauthenticated.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": [],
            },
        )
        assert denied.status_code == 401

    with unit_registry_app.test_client() as user_a:
        sign_in(user_a, "user-a")
        created = user_a.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scp"],
            },
        ).get_json()
        unit_id = created["unit_id"]

    with unit_registry_app.test_client() as user_b:
        sign_in(user_b, "user-b")
        registry = registry_for(user_b)
        assert all(unit["name"] != "scoop" for unit in registry["units"])
        forbidden_edit = user_b.put(
            f"/api/master-data/units/{unit_id}",
            json={
                "canonical_name": "stolen scoop",
                "category": "volume",
                "aliases": [],
            },
        )
        assert forbidden_edit.status_code == 404
        assert "scoop" not in forbidden_edit.get_data(as_text=True).lower()
        forbidden_usage = user_b.get(
            f"/api/master-data/units/{unit_id}/references"
        )
        assert forbidden_usage.status_code == 404


def test_units_page_exposes_accessible_persistent_editor_and_import_offer(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/units",
            query_string={"viewer_user_id": "user-a"},
        )
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.select_one("[data-unit-master-add-button]").get_text(strip=True) == "Add Unit"
    dialog = soup.select_one("dialog[data-unit-master-dialog]")
    assert dialog is not None
    assert dialog.select_one("[data-unit-master-name]") is not None
    assert dialog.select_one("[data-unit-master-category-select]") is not None
    assert dialog.select_one("[data-unit-master-alias-chips]") is not None
    assert dialog.select_one("[data-unit-master-save]") is not None
    ai_button = dialog.select_one("[data-unit-master-ai-suggest]")
    assert ai_button is not None
    assert ai_button.get("aria-describedby") == "unitAiAssistHelp"
    assert "Nothing is saved" in dialog.select_one("#unitAiAssistHelp").get_text(" ", strip=True)
    assert soup.select_one("[data-unit-master-page]")["data-suggest-url"] == (
        "/api/master-data/units/suggest"
    )
    assert soup.select_one("[data-unit-master-import]") is not None
    assert len(soup.select("[data-unit-master-edit-button]")) >= 30


def test_unit_usage_counts_distinct_recipes_and_lists_matching_lines(
    unit_registry_app,
    monkeypatch,
):
    monkeypatch.setattr(
        "PushShoppingList.routes.main_routes.recipe_cover_image_for_view",
        lambda *_args, **_kwargs: {
            "thumb_url": "/static/generated/recipe-thumb.webp",
            "srcset": "/static/generated/recipe-thumb.webp 52w",
            "alt": "Recipe thumbnail",
        },
    )
    first_url = "https://example.test/recipes/teaspoon-first"
    second_url = "https://example.test/recipes/teaspoon-option"
    master_data.sync_recipe_master_records(
        first_url,
        recipe_data={
            "ingredients": [
                {
                    "recipe_ingredient_id": "salt",
                    "ingredient": "salt",
                    "quantity": "1",
                    "unit": "tsp",
                    "original_text": "1 tsp salt",
                },
                {
                    "recipe_ingredient_id": "vanilla",
                    "ingredient": "vanilla",
                    "quantity": "2",
                    "unit": "teaspoons",
                    "original_text": "2 teaspoons vanilla",
                },
            ],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        second_url,
        recipe_data={
            "ingredients": [{
                "recipe_ingredient_id": "sweetener",
                "ingredient": "sugar",
                "quantity": "1",
                "unit": "tablespoon",
                "original_text": "1 tablespoon sugar",
                "substitutions": [{
                    "alternative_id": "honey-option",
                    "alternative_label": "Honey",
                    "option_type": "substitution",
                    "ingredient": "honey",
                    "quantity": "1",
                    "unit": "tsp",
                    "original_text": "1 tsp honey",
                }],
            }],
        },
        user_id="user-a",
    )

    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        registry = registry_for(client)
        teaspoon = unit_named(registry, "teaspoon")
        assert teaspoon["recipe_count"] == 2

        response = client.get(
            f'/api/master-data/units/{teaspoon["id"]}/references'
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["total"] == 2
        assert payload["total_reference_count"] >= 3
        assert all(
            reference["recipe_image_url"]
            == "/static/generated/recipe-thumb.webp"
            for reference in payload["references"]
        )
        assert all(
            reference["recipe_image_alt"] == "Recipe thumbnail"
            for reference in payload["references"]
        )
        assert {row["recipe_id"] for row in payload["references"]} == {
            master_data.recipe_id_for_url(first_url),
            master_data.recipe_id_for_url(second_url),
        }
        all_matches = [
            match
            for reference in payload["references"]
            for match in reference["matches"]
        ]
        assert {match["ingredient_line"] for match in all_matches} >= {
            "1 tsp salt",
            "2 teaspoons vanilla",
            "1 tsp honey",
        }
        honey_match = next(
            match for match in all_matches if match["ingredient_line"] == "1 tsp honey"
        )
        assert honey_match["kind"] == "option"
        assert honey_match["context"] == "Honey"


def test_units_page_renders_clickable_recipe_counts_and_usage_dialog(
    unit_registry_app,
):
    master_data.sync_recipe_master_records(
        "https://example.test/recipes/usage-page",
        recipe_data={
            "ingredients": [{
                "ingredient": "salt",
                "quantity": "1",
                "unit": "teaspoon",
                "original_text": "1 teaspoon salt",
            }],
        },
        user_id="user-a",
    )

    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/units",
            query_string={"viewer_user_id": "user-a"},
        )

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    headers = [
        header.get_text(" ", strip=True)
        for header in soup.select(".unit-master-table-head [role='columnheader']")[:5]
    ]
    assert headers == [
        "Canonical name",
        "Accepted aliases",
        "Used in",
        "Source",
        "Action",
    ]
    teaspoon_row = next(
        row
        for row in soup.select("[data-unit-master-row]")
        if row.select_one("strong[role='cell']").get_text(strip=True) == "teaspoon"
    )
    usage_button = teaspoon_row.select_one("[data-unit-master-usage-button]")
    assert usage_button is not None
    assert usage_button.select_one("strong").get_text(strip=True) == "1"
    assert usage_button["aria-controls"] == "unitMasterUsageDialog"
    assert soup.select_one("dialog[data-unit-master-usage-dialog]") is not None
    assert soup.select_one("[data-unit-master-page]")["data-usage-url-template"] == (
        "/api/master-data/units/__UNIT_ID__/references"
    )
    script = Path("PushShoppingList/static/js/units.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    assert "const createUsageRecipeVisual = reference =>" in script
    assert 'image.loading = "lazy";' in script
    assert 'image.addEventListener("error", revealFallback, { once: true });' in script
    assert "unit-master-usage-recipe-fallback" in script
    assert ".unit-master-usage-recipe-visual" in css
    assert ".unit-master-usage-recipe-fallback" in css


def test_unit_editor_resets_legacy_button_sizing_and_uses_contextual_save_label():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/units.js").read_text(encoding="utf-8")
    unit_button_rules = css[
        css.index(".unit-master-page button {"):
        css.index(".unit-master-page button:is(:hover, :focus-visible)")
    ]
    close_button_rules = css[
        css.index(".unit-master-dialog-close {"):
        css.index(".unit-master-editor-grid {")
    ]
    alias_button_rules = css[
        css.index(".unit-master-alias-chip button {"):
        css.index(".unit-master-alias-chip small {")
    ]

    assert "width: auto;" in unit_button_rules
    assert "margin: 0;" in unit_button_rules
    assert "width: 38px;" in close_button_rules
    assert "width: 24px;" in alias_button_rules
    assert 'saveButtonLabel = unit ? "Save Changes" : "Add Unit";' in script
    assert 'saveButton.textContent = saveButtonLabel;' in script


def test_unit_registry_uses_readable_type_at_normal_browser_zoom():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    table_head_start = css.index(".unit-master-table-head {")
    row_start = css.index(".unit-master-row {", table_head_start)
    table_head_rules = css[
        table_head_start:
        row_start
    ]
    row_rules = css[
        row_start:
        css.index(".unit-master-row:last-child")
    ]
    alias_rules = css[
        css.index(".unit-master-aliases code {"):
        css.index(".unit-master-aliases > span")
    ]
    source_badge_rules = css[
        css.index(".unit-master-source-badge {"):
        css.index(".unit-master-source-badge.user-created")
    ]

    assert "font-size: 12px;" in table_head_rules
    assert "font-size: 14px;" in row_rules
    assert "min-height: 58px;" in row_rules
    assert "font-size: 13px;" in alias_rules
    assert "color: var(--app-text);" in alias_rules
    assert "font-size: 12px;" in source_badge_rules


def test_ai_suggestion_populates_valid_details_without_persisting(
    unit_registry_app,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        unit_suggestion_service,
        "request_openai_unit_suggestion",
        lambda values, user_id=None: (
            {
                "canonical_name": "serving scoop",
                "category": "volume",
                "aliases": ["ss", "scoops", "cup", "SS", "serving scoop"],
            },
            "test-model",
            "test",
        ),
    )

    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        before = registry_for(client)
        response = client.post(
            "/api/master-data/units/suggest",
            headers={"X-Requested-With": "fetch"},
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scoopful"],
            },
        )
        after = registry_for(client)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["suggestion"] == {
        "canonical_name": "serving scoop",
        "category": "volume",
        "aliases": ["scoopful", "ss", "scoops", "scoop"],
    }
    assert any('Ignored "cup"' in warning for warning in payload["warnings"])
    assert len(after["units"]) == len(before["units"])
    assert all(unit["name"] != "serving scoop" for unit in after["units"])


def test_ai_suggestion_keeps_entered_name_when_ai_canonical_collides(
    unit_registry_app,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        unit_suggestion_service,
        "request_openai_unit_suggestion",
        lambda values, user_id=None: (
            {
                "canonical_name": "cup",
                "category": "volume",
                "aliases": ["scp", "cups"],
            },
            "test-model",
            "test",
        ),
    )

    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(
            "/api/master-data/units/suggest",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": [],
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["suggestion"]["canonical_name"] == "scoop"
    assert payload["suggestion"]["aliases"] == ["scp"]
    assert any("canonical name already used" in warning for warning in payload["warnings"])


def test_ai_suggestion_collision_filter_is_workspace_scoped(
    unit_registry_app,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        unit_suggestion_service,
        "request_openai_unit_suggestion",
        lambda values, user_id=None: (
            {
                "canonical_name": values["canonical_name"],
                "category": "volume",
                "aliases": ["workspace-only"],
            },
            "test-model",
            "test",
        ),
    )

    with unit_registry_app.test_client() as user_a:
        sign_in(user_a, "user-a")
        created = user_a.post(
            "/api/master-data/units",
            json={
                "canonical_name": "private measure",
                "category": "count_package",
                "aliases": ["workspace-only"],
            },
        )
        assert created.status_code == 201
        response_a = user_a.post(
            "/api/master-data/units/suggest",
            json={"canonical_name": "ladleful", "category": "volume", "aliases": []},
        )

    with unit_registry_app.test_client() as user_b:
        sign_in(user_b, "user-b")
        response_b = user_b.post(
            "/api/master-data/units/suggest",
            json={"canonical_name": "ladleful", "category": "volume", "aliases": []},
        )

    assert response_a.get_json()["suggestion"]["aliases"] == []
    assert response_b.get_json()["suggestion"]["aliases"] == ["workspace-only"]


def test_ai_suggestion_rejects_invalid_or_unauthorized_requests(
    unit_registry_app,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        unit_suggestion_service,
        "request_openai_unit_suggestion",
        lambda values, user_id=None: calls.append(values),
    )

    with unit_registry_app.test_client() as anonymous:
        unauthorized = anonymous.post(
            "/api/master-data/units/suggest",
            headers={"X-Requested-With": "fetch"},
            json={"canonical_name": "scoop"},
        )
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        blank = client.post(
            "/api/master-data/units/suggest",
            json={"canonical_name": "   ", "category": "volume"},
        )
        existing = client.post(
            "/api/master-data/units/suggest",
            json={"canonical_name": "TBSP", "category": "volume"},
        )

    assert unauthorized.status_code == 401
    assert blank.status_code == 422
    assert blank.get_json()["errors"]["canonical_name"]
    assert existing.status_code == 422
    assert "tablespoon" in existing.get_json()["errors"]["canonical_name"]
    assert calls == []


def test_ai_suggestion_failure_does_not_change_the_registry(
    unit_registry_app,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        unit_suggestion_service,
        "request_openai_unit_suggestion",
        lambda values, user_id=None: (_ for _ in ()).throw(RuntimeError("temporary")),
    )

    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        before = registry_for(client)
        response = client.post(
            "/api/master-data/units/suggest",
            json={"canonical_name": "scoop", "category": "count_package"},
        )
        after = registry_for(client)

    assert response.status_code == 503
    assert "not changed" in response.get_json()["error"]
    assert after == before


def test_legacy_browser_unit_import_skips_existing_names(unit_registry_app):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        imported = client.post(
            "/api/master-data/units/import-local",
            json={"units": ["scoop", "SCOOP", "cup", "ladle"]},
        )
        assert imported.status_code == 200
        payload = imported.get_json()
        assert set(payload["imported"]) == {"scoop", "ladle"}
        assert {item["name"] for item in payload["skipped"]} == {"SCOOP", "cup"}
        assert sum(unit["name"] == "scoop" for unit in payload["registry"]["units"]) == 1
