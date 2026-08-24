import json

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import cuisine_category_service as cuisines
from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service


@pytest.fixture
def cuisine_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(
        master_data,
        "RECIPE_MASTER_DB_PATH",
        tmp_path / "recipe_master.sqlite3",
    )
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    return tmp_path


def write_recipe_output(user_id, recipe_url, payload):
    output_folder = cuisines._workspace_recipe_output_folder(user_id)
    path = recipe_edit_service.recipe_output_json_path(
        recipe_url,
        output_folder=output_folder,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    recipe_edit_service.save_recipe_output_to_path(
        path,
        {
            "source_url": recipe_url,
            "recipe_title": "Recipe",
            "ingredients": [],
            **payload,
        },
        url=recipe_url,
    )
    return path


def write_cookbooks(user_id, payload):
    path = cuisines._workspace_cookbooks_path(user_id)
    cuisines._save_workspace_cookbooks(user_id, payload)
    return path


def category_named(registry, name):
    return next(item for item in registry["categories"] if item["name"] == name)


def test_default_registry_is_read_only_and_has_stable_seed_ids(cuisine_workspace):
    registry = cuisines.cuisine_category_registry_payload("user-a")

    assert [item["id"] for item in registry["categories"]] == [
        "american",
        "mexican",
        "peruvian",
        "italian",
        "japanese",
        "thai",
        "chinese",
        "indian",
        "french",
        "other_fusion",
    ]
    assert registry["categories"][0]["name"] == "🇺🇸 American"
    assert registry["categories"][-1]["name"] == "🌍 Other / Fusion"
    assert all(item["seeded"] and item["active"] for item in registry["categories"])
    assert cuisines.active_workspace_cuisine_category_labels("user-a") == [
        item["name"] for item in registry["categories"]
    ]
    assert not master_data.recipe_master_db_path().exists()


def test_seed_and_custom_categories_are_idempotent_and_workspace_isolated(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {"name": "Levantine", "active": True},
        user_id="user-a",
    )
    assert created["ok"] is True
    assert created["created"] is True
    category_id = created["category_id"]
    assert category_id.startswith("custom_")

    user_a = cuisines.cuisine_category_registry_payload("user-a")
    custom = category_named(user_a, "Levantine")
    assert custom["id"] == category_id
    assert custom["custom"] is True
    assert custom["seeded"] is False

    duplicate = cuisines.save_workspace_cuisine_category(
        {"name": "levantine", "active": True},
        user_id="user-a",
    )
    assert duplicate["status"] == 422
    assert len(cuisines.cuisine_category_registry_payload("user-a")["categories"]) == 11
    assert len(cuisines.cuisine_category_registry_payload("user-b")["categories"]) == 10
    assert all(
        item["name"] != "Levantine"
        for item in cuisines.cuisine_category_registry_payload("user-b")["categories"]
    )

    with master_data.recipe_master_connection(user_id="user-a") as connection:
        seed_markers = connection.execute(
            """
            SELECT COUNT(*)
              FROM workspace_cuisine_category_registry_seeds
             WHERE user_id = ?
            """,
            ("user-a",),
        ).fetchone()[0]
        seeded_rows = connection.execute(
            """
            SELECT COUNT(*)
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND is_seeded = 1
            """,
            ("user-a",),
        ).fetchone()[0]
    assert seed_markers == 1
    assert seeded_rows == 10


def test_recognized_national_cuisines_receive_flags_without_guessing_regions(
    cuisine_workspace,
):
    assert cuisines.decorate_recognized_cuisine_name("United Kingdom") == (
        "🇬🇧 United Kingdom"
    )
    assert cuisines.decorate_recognized_cuisine_name("British") == "🇬🇧 British"
    assert cuisines.decorate_recognized_cuisine_name("Korean") == "🇰🇷 Korean"
    assert cuisines.decorate_recognized_cuisine_name("Mediterranean") == (
        "Mediterranean"
    )
    assert cuisines.decorate_recognized_cuisine_name("Cajun") == "Cajun"
    assert cuisines.decorate_recognized_cuisine_name("🍜 United Kingdom") == (
        "🍜 United Kingdom"
    )
    assert cuisines.decorate_recognized_cuisine_name("🇬🇧 United Kingdom") == (
        "🇬🇧 United Kingdom"
    )

    created = cuisines.save_workspace_cuisine_category(
        {"name": "  United   Kingdom  ", "active": True},
        user_id="user-a",
    )
    assert created["ok"] is True
    assert created["name"] == "🇬🇧 United Kingdom"
    assert category_named(
        cuisines.cuisine_category_registry_payload("user-a"),
        "🇬🇧 United Kingdom",
    )["id"] == created["category_id"]

    duplicate = cuisines.save_workspace_cuisine_category(
        {"name": "🇬🇧 United Kingdom", "active": True},
        user_id="user-a",
    )
    assert duplicate["status"] == 422
    assert duplicate["errors"]["name"] == (
        "A cuisine category with that name already exists."
    )

    regional = cuisines.save_workspace_cuisine_category(
        {"name": "Levantine", "active": True},
        user_id="user-a",
    )
    explicit_icon = cuisines.save_workspace_cuisine_category(
        {"name": "🍜 Korean", "active": True},
        user_id="user-a",
    )
    assert regional["name"] == "Levantine"
    assert explicit_icon["name"] == "🍜 Korean"


def test_import_deduplicates_plain_and_flagged_national_cuisine_names(
    cuisine_workspace,
):
    result = cuisines.import_workspace_cuisine_category_names(
        ["United Kingdom", "🇬🇧 United Kingdom", "Mediterranean"],
        user_id="user-a",
    )

    assert result["imported"] == ["🇬🇧 United Kingdom", "Mediterranean"]
    assert result["skipped"] == ["🇬🇧 United Kingdom"]
    names = [
        item["name"]
        for item in cuisines.cuisine_category_registry_payload("user-a")[
            "categories"
        ]
    ]
    assert names.count("🇬🇧 United Kingdom") == 1
    assert "United Kingdom" not in names


def test_legacy_plain_national_cuisine_displays_and_migrates_to_flagged_name(
    cuisine_workspace,
):
    category_id = "custom_legacy_united_kingdom"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        cuisines._seed_registry(connection, "user-a")
        timestamp = master_data.utc_now_iso()
        connection.execute(
            """
            INSERT INTO workspace_cuisine_categories (
                user_id, id, name, normalized_name, aliases_json, is_seeded,
                is_active, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '[]', 0, 1, 10, ?, ?)
            """,
            (
                "user-a",
                category_id,
                "United Kingdom",
                "united kingdom",
                timestamp,
                timestamp,
            ),
        )

    public_before_save = category_named(
        cuisines.cuisine_category_registry_payload("user-a"),
        "🇬🇧 United Kingdom",
    )
    assert public_before_save["id"] == category_id
    assert public_before_save["aliases"] == ["United Kingdom"]

    recipe_path = write_recipe_output(
        "user-a",
        "https://example.test/united-kingdom",
        {
            "recipe_title": "British plate",
            "cuisine": "United Kingdom",
            "cuisine_tags": [
                "United Kingdom",
                "🇬🇧 United Kingdom",
                "Italian",
            ],
        },
    )
    cookbook_path = write_cookbooks(
        "user-a",
        {
            "cookbooks": [{
                "id": "british",
                "name": "British recipes",
                "recipes": [{
                    "url": "https://example.test/united-kingdom",
                    "name": "British plate",
                    "cuisine": "United Kingdom",
                }],
            }],
        },
    )

    saved = cuisines.save_workspace_cuisine_category(
        {"name": "United Kingdom", "active": True},
        category_id=category_id,
        user_id="user-a",
    )
    assert saved["ok"] is True
    assert saved["name"] == "🇬🇧 United Kingdom"
    assert saved["migration"] == {"recipe_records": 1, "cookbook_records": 1}

    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe_payload["cuisine"] == "🇬🇧 United Kingdom"
    assert recipe_payload["cuisine_tags"] == [
        "🇬🇧 United Kingdom",
        "Italian",
    ]
    cookbook_payload = json.loads(cookbook_path.read_text(encoding="utf-8"))
    assert cookbook_payload["cookbooks"][0]["recipes"][0]["cuisine"] == (
        "🇬🇧 United Kingdom"
    )

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    category = category_named(registry, "🇬🇧 United Kingdom")
    assert category["aliases"] == ["United Kingdom"]
    assert category["recipe_count"] == 1
    assert sum(item["id"] == category_id for item in registry["categories"]) == 1


def test_usage_and_references_dedupe_primary_tags_and_cookbook_metadata(
    cuisine_workspace,
):
    write_recipe_output(
        "user-a",
        "https://example.test/one",
        {
            "recipe_title": "One",
            "cuisine": "🇮🇹 Italian",
            "cuisine_tags": ["Italian", "🇲🇽 Mexican"],
        },
    )
    write_recipe_output(
        "user-a",
        "https://example.test/two",
        {
            "recipe_title": "Two",
            "cuisine": "Italian",
            "cuisine_tags": ["italian"],
        },
    )
    write_cookbooks(
        "user-a",
        {
            "cookbooks": [{
                "id": "favorites",
                "name": "Favorites",
                "recipes": [
                    {
                        "url": "https://example.test/one",
                        "name": "One duplicate",
                        "cuisine": "Italian",
                    },
                    {
                        "url": "https://example.test/three",
                        "name": "Three",
                        "cuisine": "🇮🇹 Italian",
                    },
                ],
            }],
        },
    )

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    assert category_named(registry, "🇮🇹 Italian")["recipe_count"] == 3
    assert category_named(registry, "🇲🇽 Mexican")["recipe_count"] == 1

    references = cuisines.workspace_cuisine_category_recipe_references(
        "italian",
        user_id="user-a",
    )
    assert references["total"] == 3
    assert references["total_reference_count"] == 3
    assert {item["recipe_url"] for item in references["references"]} == {
        "https://example.test/one",
        "https://example.test/two",
        "https://example.test/three",
    }
    one = next(
        item
        for item in references["references"]
        if item["recipe_url"] == "https://example.test/one"
    )
    assert {match["source"] for match in one["matches"]} == {
        "recipe",
        "cookbook",
    }

    other_workspace = cuisines.cuisine_category_registry_payload(
        "user-b",
        include_usage=True,
    )
    assert category_named(other_workspace, "🇮🇹 Italian")["recipe_count"] == 0


def test_secondary_recipe_output_tag_blocks_delete_and_stays_tenant_scoped(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {"name": "Levantine", "active": True},
        user_id="user-a",
    )
    category_id = created["category_id"]
    write_recipe_output(
        "user-a",
        "https://example.test/secondary-cuisine",
        {
            "recipe_title": "Secondary cuisine",
            "cuisine": "Italian",
            "cuisine_tags": ["Italian", "Levantine"],
        },
    )

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    assert category_named(registry, "Levantine")["recipe_count"] == 1
    references = cuisines.workspace_cuisine_category_recipe_references(
        category_id,
        user_id="user-a",
    )
    assert references["total"] == 1
    assert references["references"][0]["recipe_url"] == (
        "https://example.test/secondary-cuisine"
    )

    blocked = cuisines.delete_workspace_cuisine_category(
        category_id,
        user_id="user-a",
    )
    assert blocked["status"] == 409
    assert all(
        item["name"] != "Levantine"
        for item in cuisines.cuisine_category_registry_payload(
            "user-b",
            include_usage=True,
        )["categories"]
    )


def test_rename_migrates_recipe_and_cookbook_values_and_keeps_an_alias(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {"name": "Regional", "active": True},
        user_id="user-a",
    )
    category_id = created["category_id"]
    recipe_path = write_recipe_output(
        "user-a",
        "https://example.test/regional",
        {
            "recipe_title": "Regional plate",
            "cuisine": "Regional",
            "cuisine_tags": ["Regional", "Italian"],
        },
    )
    cookbook_path = write_cookbooks(
        "user-a",
        {
            "cookbooks": [{
                "id": "regional",
                "name": "Regional",
                "recipes": [{
                    "url": "https://example.test/regional",
                    "name": "Regional plate",
                    "cuisine": "Regional",
                }],
            }],
        },
    )

    renamed = cuisines.save_workspace_cuisine_category(
        {"name": "Levantine", "active": True},
        category_id=category_id,
        user_id="user-a",
    )
    assert renamed["ok"] is True
    assert renamed["migration"] == {"recipe_records": 1, "cookbook_records": 1}
    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe_payload["cuisine"] == "Levantine"
    assert recipe_payload["cuisine_tags"] == ["Levantine", "Italian"]
    cookbook_payload = json.loads(cookbook_path.read_text(encoding="utf-8"))
    assert cookbook_payload["cookbooks"][0]["recipes"][0]["cuisine"] == "Levantine"

    renamed_category = category_named(
        cuisines.cuisine_category_registry_payload("user-a"),
        "Levantine",
    )
    assert renamed_category["aliases"] == ["Regional"]

    # The persisted alias keeps an old imported value resolvable even if a
    # later legacy import reintroduces the former label.
    recipe_payload["cuisine"] = "Regional"
    recipe_payload["cuisine_tags"] = ["Regional", "Italian"]
    recipe_edit_service.save_recipe_output_to_path(
        recipe_path,
        recipe_payload,
        url="https://example.test/regional",
    )
    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    assert category_named(registry, "Levantine")["recipe_count"] == 1

    blocked = cuisines.delete_workspace_cuisine_category(
        category_id,
        user_id="user-a",
    )
    assert blocked["status"] == 409
    assert "Deactivate it instead" in blocked["error"]


def test_deactivation_import_and_safe_delete_rules(cuisine_workspace):
    seeded_delete = cuisines.delete_workspace_cuisine_category(
        "italian",
        user_id="user-a",
    )
    assert seeded_delete["status"] == 422

    seeded_rename = cuisines.save_workspace_cuisine_category(
        {"name": "Tuscan", "active": True},
        category_id="italian",
        user_id="user-a",
    )
    assert seeded_rename["status"] == 422
    assert seeded_rename["errors"]["name"] == (
        "Built-in cuisine category names cannot be changed."
    )
    assert category_named(
        cuisines.cuisine_category_registry_payload("user-a"),
        "🇮🇹 Italian",
    )["seeded"] is True

    deactivated = cuisines.save_workspace_cuisine_category(
        {"name": "🇮🇹 Italian", "active": False},
        category_id="italian",
        user_id="user-a",
    )
    assert deactivated["ok"] is True
    assert "🇮🇹 Italian" not in cuisines.active_workspace_cuisine_category_labels(
        "user-a"
    )

    imported = cuisines.import_workspace_cuisine_category_names(
        ["Nordic", "nordic", "Italian", ""],
        user_id="user-a",
    )
    assert imported["imported"] == ["Nordic"]
    assert imported["skipped"] == ["nordic", "Italian"]
    nordic = category_named(
        cuisines.cuisine_category_registry_payload("user-a"),
        "Nordic",
    )
    deleted = cuisines.delete_workspace_cuisine_category(
        nordic["id"],
        user_id="user-a",
    )
    assert deleted["ok"] is True
    assert deleted["deleted"] is True


@pytest.mark.parametrize(
    ("name", "message"),
    (
        (
            "Cajun, Creole",
            "Cuisine category names cannot contain commas, semicolons, or line breaks.",
        ),
        (
            "Cajun; Creole",
            "Cuisine category names cannot contain commas, semicolons, or line breaks.",
        ),
        (
            "Cajun\nCreole",
            "Cuisine category names cannot contain commas, semicolons, or line breaks.",
        ),
        (
            "🔥",
            "Enter a cuisine category name containing letters or numbers.",
        ),
    ),
)
def test_invalid_cuisine_category_names_are_rejected(
    cuisine_workspace,
    name,
    message,
):
    result = cuisines.save_workspace_cuisine_category(
        {"name": name, "active": True},
        user_id="user-a",
    )

    assert result["status"] == 422
    assert result["errors"]["name"] == message
    assert len(cuisines.cuisine_category_registry_payload("user-a")["categories"]) == 10


def test_db_only_recipe_output_usage_and_rename_use_explicit_workspace_identity(
    cuisine_workspace,
    monkeypatch,
):
    db_path = master_data.recipe_master_db_path()
    application_data.install_application_schema(
        db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    monkeypatch.setenv(durable_runtime.DURABLE_BACKEND_ENV, "db_only")
    created = cuisines.save_workspace_cuisine_category(
        {"name": "Regional", "active": True},
        user_id="user-a",
    )
    category_id = created["category_id"]
    recipe_url = "https://example.test/database-regional"
    output_path = recipe_edit_service.recipe_output_json_path(
        recipe_url,
        output_folder=cuisines._workspace_recipe_output_folder("user-a"),
    )
    recipe_payload = {
        "source_url": recipe_url,
        "recipe_title": "Database regional recipe",
        "cuisine": "Regional",
        "cuisine_tags": ["Regional", "Italian"],
        "ingredients": [],
    }
    identity = {
        "workspace_id": "user-a",
        "workspace_type": "user",
        "subject_id": "user-a",
        "domain": "recipes",
        "document_key": recipe_edit_service.recipe_output_document_key(
            recipe_payload
        ),
        "source_key": recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
        "source_ref": recipe_edit_service.recipe_output_source_ref(output_path),
    }
    durable_runtime.write_database_document(
        recipe_payload,
        db_path=db_path,
        **identity,
    )

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    assert category_named(registry, "Regional")["recipe_count"] == 1

    renamed = cuisines.save_workspace_cuisine_category(
        {"name": "Levantine", "active": True},
        category_id=category_id,
        user_id="user-a",
    )
    assert renamed["migration"] == {"recipe_records": 1, "cookbook_records": 0}
    stored = durable_runtime.read_database_document(
        db_path=db_path,
        workspace_id=identity["workspace_id"],
        domain=identity["domain"],
        document_key=identity["document_key"],
        source_key=identity["source_key"],
        source_ref=identity["source_ref"],
    )
    assert stored["cuisine"] == "Levantine"
    assert stored["cuisine_tags"] == ["Levantine", "Italian"]
    assert not output_path.exists()
