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
    assert [
        {
            "id": item["id"],
            "icon": item["icon"],
            "abbreviation": item["abbreviation"],
            "category_name": item["category_name"],
            "display_label": item["display_label"],
        }
        for item in registry["categories"]
    ] == [
        {
            "id": "american",
            "icon": "flag:us",
            "abbreviation": "US",
            "category_name": "American",
            "display_label": "🇺🇸 American",
        },
        {
            "id": "mexican",
            "icon": "flag:mx",
            "abbreviation": "MX",
            "category_name": "Mexican",
            "display_label": "🇲🇽 Mexican",
        },
        {
            "id": "peruvian",
            "icon": "flag:pe",
            "abbreviation": "PE",
            "category_name": "Peruvian",
            "display_label": "🇵🇪 Peruvian",
        },
        {
            "id": "italian",
            "icon": "flag:it",
            "abbreviation": "IT",
            "category_name": "Italian",
            "display_label": "🇮🇹 Italian",
        },
        {
            "id": "japanese",
            "icon": "flag:jp",
            "abbreviation": "JP",
            "category_name": "Japanese",
            "display_label": "🇯🇵 Japanese",
        },
        {
            "id": "thai",
            "icon": "flag:th",
            "abbreviation": "TH",
            "category_name": "Thai",
            "display_label": "🇹🇭 Thai",
        },
        {
            "id": "chinese",
            "icon": "flag:cn",
            "abbreviation": "CN",
            "category_name": "Chinese",
            "display_label": "🇨🇳 Chinese",
        },
        {
            "id": "indian",
            "icon": "flag:in",
            "abbreviation": "IN",
            "category_name": "Indian",
            "display_label": "🇮🇳 Indian",
        },
        {
            "id": "french",
            "icon": "flag:fr",
            "abbreviation": "FR",
            "category_name": "French",
            "display_label": "🇫🇷 French",
        },
        {
            "id": "other_fusion",
            "icon": "symbol:globe",
            "abbreviation": "FUS",
            "category_name": "Other / Fusion",
            "display_label": "🌍 Other / Fusion",
        },
    ]
    assert cuisines.active_workspace_cuisine_category_labels("user-a") == [
        item["name"] for item in registry["categories"]
    ]
    assert not master_data.recipe_master_db_path().exists()


@pytest.mark.parametrize(
    ("raw_icon", "token", "country_code", "display"),
    (
        ("FLAG : GB", "flag:gb", "GB", "🇬🇧"),
        ("🇬🇧", "flag:gb", "GB", "🇬🇧"),
        ("flag:us", "flag:us", "US", "🇺🇸"),
        (" SYMBOL : NOODLES ", "symbol:noodles", "", "🍜"),
        ("🍜", "🍜", "", "🍜"),
        ("", "", "", ""),
    ),
)
def test_flag_icon_tokens_normalize_and_keep_legacy_presentations(
    raw_icon,
    token,
    country_code,
    display,
):
    assert cuisines.clean_cuisine_category_icon(raw_icon) == token
    assert cuisines.country_code_from_flag(raw_icon) == country_code
    assert cuisines.cuisine_category_icon_display(raw_icon) == display


def test_flag_icon_token_create_normalizes_storage_and_legacy_display(
    cuisine_workspace,
):
    assert cuisines.split_legacy_cuisine_category_label(
        "flag:GB United Kingdom"
    ) == ("flag:gb", "United Kingdom")
    created = cuisines.save_workspace_cuisine_category(
        {
            "icon": " FLAG : gB ",
            "abbreviation": "GBR",
            "category_name": "British Isles",
            "active": True,
        },
        user_id="user-a",
    )

    assert created["ok"] is True
    assert created["icon"] == "flag:gb"
    assert created["category_name"] == "British Isles"
    assert created["display_label"] == "🇬🇧 British Isles"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored = connection.execute(
            """
            SELECT icon, name
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", created["category_id"]),
        ).fetchone()
    assert dict(stored) == {
        "icon": "flag:gb",
        "name": "British Isles",
    }


def test_symbol_icon_token_create_normalizes_storage_and_display(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {
            "icon": " SYMBOL : PLATE ",
            "abbreviation": "MOD",
            "category_name": "Modern Cuisine",
        },
        user_id="user-a",
    )

    assert created["ok"] is True
    assert created["icon"] == "symbol:plate"
    assert created["display_label"] == "🍽️ Modern Cuisine"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored_icon = connection.execute(
            """
            SELECT icon
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", created["category_id"]),
        ).fetchone()["icon"]
    assert stored_icon == "symbol:plate"


@pytest.mark.parametrize("icon", ("flag:GBR", "flag:1x", "flag:", "flag:gb extra"))
def test_invalid_flag_icon_tokens_are_rejected(cuisine_workspace, icon):
    result = cuisines.save_workspace_cuisine_category(
        {
            "icon": icon,
            "abbreviation": "TEST",
            "category_name": f"Invalid token {icon}",
        },
        user_id="user-a",
    )

    assert result["status"] == 422
    assert result["errors"]["icon"] == (
        "Use a flag token in the format flag:us."
    )


@pytest.mark.parametrize(
    "icon",
    ("symbol:alien", "symbol:", "symbol:two words", "symbol:bowl-extra"),
)
def test_invalid_or_unknown_symbol_icon_tokens_are_rejected(
    cuisine_workspace,
    icon,
):
    result = cuisines.save_workspace_cuisine_category(
        {
            "icon": icon,
            "abbreviation": "TEST",
            "category_name": f"Invalid symbol {icon}",
        },
        user_id="user-a",
    )

    assert result["status"] == 422
    assert result["errors"]["icon"] == "Choose a supported cuisine symbol."


def test_legacy_seed_icons_upgrade_to_tokens_without_overwriting_custom_icons(
    cuisine_workspace,
):
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        cuisines._seed_registry(connection, "user-a")
        connection.execute(
            """
            UPDATE workspace_cuisine_categories
               SET icon = CASE id
                    WHEN 'american' THEN '🇺🇸'
                    WHEN 'italian' THEN '🍝'
                    WHEN 'mexican' THEN ''
                    WHEN 'other_fusion' THEN '🌍'
                    ELSE icon
               END
             WHERE user_id = ?
               AND id IN ('american', 'italian', 'mexican', 'other_fusion')
            """,
            ("user-a",),
        )
        connection.execute(
            """
            UPDATE workspace_cuisine_category_registry_seeds
               SET seed_version = 'cuisine_categories_v2'
             WHERE user_id = ?
            """,
            ("user-a",),
        )

        assert cuisines._seed_registry(connection, "user-a") is True
        icons = {
            row["id"]: row["icon"]
            for row in connection.execute(
                """
                SELECT id, icon
                 FROM workspace_cuisine_categories
                 WHERE user_id = ?
                   AND id IN (
                       'american', 'italian', 'mexican', 'other_fusion'
                   )
                """,
                ("user-a",),
            ).fetchall()
        }
        marker = connection.execute(
            """
            SELECT seed_version
              FROM workspace_cuisine_category_registry_seeds
             WHERE user_id = ?
            """,
            ("user-a",),
        ).fetchone()

    assert icons == {
        "american": "flag:us",
        "italian": "🍝",
        "mexican": "",
        "other_fusion": "symbol:globe",
    }
    assert marker["seed_version"] == cuisines.CUISINE_CATEGORY_SEED_VERSION


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


def test_custom_category_create_and_edit_persist_structured_display_fields(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🍲",
            "abbreviation": "lev",
            "category_name": "Levantine",
            "active": True,
        },
        user_id="user-a",
    )

    assert created["ok"] is True
    assert created["icon"] == "🍲"
    assert created["abbreviation"] == "LEV"
    assert created["category_name"] == "Levantine"
    assert created["display_label"] == "🍲 Levantine"
    category_id = created["category_id"]
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored = connection.execute(
            """
            SELECT icon, abbreviation, name, normalized_name
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", category_id),
        ).fetchone()
    assert dict(stored) == {
        "icon": "🍲",
        "abbreviation": "LEV",
        "name": "Levantine",
        "normalized_name": "levantine",
    }

    updated = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🌊",
            "abbreviation": "med",
            "category_name": "Mediterranean",
            "active": True,
        },
        category_id=category_id,
        user_id="user-a",
    )

    assert updated["ok"] is True
    public = next(
        item
        for item in updated["registry"]["categories"]
        if item["id"] == category_id
    )
    assert {
        "icon": public["icon"],
        "abbreviation": public["abbreviation"],
        "category_name": public["category_name"],
        "name": public["name"],
        "display_label": public["display_label"],
    } == {
        "icon": "🌊",
        "abbreviation": "MED",
        "category_name": "Mediterranean",
        "name": "🌊 Mediterranean",
        "display_label": "🌊 Mediterranean",
    }
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored = connection.execute(
            """
            SELECT icon, abbreviation, name, normalized_name
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", category_id),
        ).fetchone()
    assert dict(stored) == {
        "icon": "🌊",
        "abbreviation": "MED",
        "name": "Mediterranean",
        "normalized_name": "mediterranean",
    }


def test_explicit_blank_icon_and_abbreviation_persist_without_inference(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {
            "icon": "",
            "abbreviation": "",
            "category_name": "Korean",
            "active": True,
        },
        user_id="user-a",
    )

    assert created["ok"] is True
    assert created["icon"] == ""
    assert created["abbreviation"] == ""
    assert created["display_label"] == "Korean"
    category = next(
        item
        for item in cuisines.cuisine_category_registry_payload("user-a")[
            "categories"
        ]
        if item["id"] == created["category_id"]
    )
    assert category["icon"] == ""
    assert category["abbreviation"] == ""
    assert category["category_name"] == "Korean"
    assert category["name"] == "Korean"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored = connection.execute(
            """
            SELECT icon, abbreviation, name
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", created["category_id"]),
        ).fetchone()
    assert dict(stored) == {
        "icon": "",
        "abbreviation": "",
        "name": "Korean",
    }


def test_partial_structured_edit_preserves_active_state_and_prefers_category_name(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🍲",
            "abbreviation": "LEV",
            "category_name": "Levantine",
            "active": False,
        },
        user_id="user-a",
    )

    updated = cuisines.save_workspace_cuisine_category(
        {
            # A client may round-trip the legacy display field while editing
            # the new structured category name.
            "name": created["display_label"],
            "category_name": "Eastern Mediterranean",
            "icon": "🫓",
        },
        category_id=created["category_id"],
        user_id="user-a",
    )

    assert updated["ok"] is True
    category = next(
        item
        for item in updated["registry"]["categories"]
        if item["id"] == created["category_id"]
    )
    assert category["category_name"] == "Eastern Mediterranean"
    assert category["icon"] == "🫓"
    assert category["active"] is False


def test_builtin_name_is_immutable_while_icon_and_abbreviation_are_editable(
    cuisine_workspace,
):
    updated = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🍝",
            "abbreviation": "ita",
            "category_name": "Italian",
            "active": True,
        },
        category_id="italian",
        user_id="user-a",
    )

    assert updated["ok"] is True
    assert updated["category_name"] == "Italian"
    assert updated["icon"] == "🍝"
    assert updated["abbreviation"] == "ITA"
    assert updated["display_label"] == "🍝 Italian"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored = connection.execute(
            """
            SELECT icon, abbreviation, name
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", "italian"),
        ).fetchone()
    assert dict(stored) == {
        "icon": "🍝",
        "abbreviation": "ITA",
        "name": "Italian",
    }

    rejected = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🍝",
            "abbreviation": "ITA",
            "category_name": "Tuscan",
            "active": True,
        },
        category_id="italian",
        user_id="user-a",
    )
    assert rejected["status"] == 422
    assert rejected["errors"]["name"] == (
        "Built-in cuisine category names cannot be changed."
    )


def test_legacy_combined_and_plain_rows_resolve_structured_fields_safely(
    cuisine_workspace,
):
    legacy_rows = (
        (
            "user-combined",
            "custom_united_kingdom",
            "🇬🇧 United Kingdom",
            "united kingdom",
        ),
        (
            "user-plain",
            "custom_united_kingdom",
            "United Kingdom",
            "united kingdom",
        ),
    )
    for user_id, category_id, name, normalized_name in legacy_rows:
        with master_data.recipe_master_connection(user_id=user_id) as connection:
            cuisines._seed_registry(connection, user_id)
            timestamp = master_data.utc_now_iso()
            connection.execute(
                """
                INSERT INTO workspace_cuisine_categories (
                    user_id, id, name, normalized_name, aliases_json,
                    is_seeded, is_active, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '[]', 0, 1, 10, ?, ?)
                """,
                (
                    user_id,
                    category_id,
                    name,
                    normalized_name,
                    timestamp,
                    timestamp,
                ),
            )

        category = next(
            item
            for item in cuisines.cuisine_category_registry_payload(user_id)[
                "categories"
            ]
            if item["id"] == category_id
        )
        assert category["icon"] == "flag:gb"
        assert category["abbreviation"] == "GB"
        assert category["category_name"] == "United Kingdom"
        assert category["display_label"] == "🇬🇧 United Kingdom"
        assert category["aliases"] == ["United Kingdom"]


def test_duplicate_and_invalid_cuisine_abbreviations_are_rejected(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🍲",
            "abbreviation": "LEV",
            "category_name": "Levantine",
        },
        user_id="user-a",
    )
    assert created["ok"] is True

    duplicate = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🫓",
            "abbreviation": "lev",
            "category_name": "Eastern Mediterranean",
        },
        user_id="user-a",
    )
    assert duplicate["status"] == 422
    assert duplicate["errors"]["abbreviation"] == (
        "A cuisine category with that abbreviation already exists."
    )

    invalid_values = {
        "A": "Use at least 2 characters.",
        "TOO-LONG9": "Use 8 characters or fewer.",
        "M E": "Use letters and numbers only.",
    }
    for abbreviation, message in invalid_values.items():
        result = cuisines.save_workspace_cuisine_category(
            {
                "icon": "",
                "abbreviation": abbreviation,
                "category_name": f"Test {abbreviation}",
            },
            user_id="user-a",
        )
        assert result["status"] == 422
        assert result["errors"]["abbreviation"] == message


def test_abbreviation_does_not_steal_a_legacy_category_name_or_block_edits(
    cuisine_workspace,
):
    category_id = "custom_legacy_us"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        cuisines._seed_registry(connection, "user-a")
        timestamp = master_data.utc_now_iso()
        connection.execute(
            """
            INSERT INTO workspace_cuisine_categories (
                user_id, id, name, normalized_name, aliases_json, is_seeded,
                is_active, sort_order, created_at, updated_at
            ) VALUES (?, ?, 'US', 'us', '[]', 0, 1, 10, ?, ?)
            """,
            ("user-a", category_id, timestamp, timestamp),
        )
    write_recipe_output(
        "user-a",
        "https://example.test/legacy-us",
        {"cuisine": "US", "cuisine_tags": ["US"]},
    )

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    legacy = category_named(registry, "US")
    assert legacy["id"] == category_id
    assert legacy["recipe_count"] == 1
    assert category_named(registry, "🇺🇸 American")["recipe_count"] == 0

    updated = cuisines.save_workspace_cuisine_category(
        {"icon": "🗺️", "active": False},
        category_id=category_id,
        user_id="user-a",
    )
    assert updated["ok"] is True
    updated_category = next(
        item
        for item in updated["registry"]["categories"]
        if item["id"] == category_id
    )
    assert updated_category["active"] is False
    assert updated_category["category_name"] == "US"


def test_display_label_collision_is_rejected_on_the_icon_field(
    cuisine_workspace,
):
    first = cuisines.save_workspace_cuisine_category(
        {
            "icon": "",
            "abbreviation": "AC",
            "category_name": "Alpha Cuisine",
        },
        user_id="user-a",
    )
    assert first["ok"] is True

    collision = cuisines.save_workspace_cuisine_category(
        {
            "icon": "Alpha",
            "abbreviation": "CU",
            "category_name": "Cuisine",
        },
        user_id="user-a",
    )

    assert collision["status"] == 422
    assert collision["errors"]["icon"] == (
        "That icon and category name match another cuisine category."
    )


def test_unchanged_duplicate_legacy_abbreviation_does_not_block_other_edits(
    cuisine_workspace,
):
    timestamp = master_data.utc_now_iso()
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        cuisines._seed_registry(connection, "user-a")
        for category_id, name in (
            ("custom_legacy_british", "British"),
            ("custom_legacy_united_kingdom", "United Kingdom"),
        ):
            connection.execute(
                """
                INSERT INTO workspace_cuisine_categories (
                    user_id, id, name, normalized_name, aliases_json,
                    is_seeded, is_active, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '[]', 0, 1, 10, ?, ?)
                """,
                (
                    "user-a",
                    category_id,
                    name,
                    cuisines.cuisine_category_key(name),
                    timestamp,
                    timestamp,
                ),
            )

    updated = cuisines.save_workspace_cuisine_category(
        {
            "icon": "🏰",
            "abbreviation": "GB",
            "category_name": "United Kingdom",
            "active": False,
        },
        category_id="custom_legacy_united_kingdom",
        user_id="user-a",
    )

    assert updated["ok"] is True
    assert updated["display_label"] == "🏰 United Kingdom"
    assert updated["abbreviation"] == "GB"
    updated_category = next(
        item
        for item in updated["registry"]["categories"]
        if item["id"] == "custom_legacy_united_kingdom"
    )
    assert updated_category["active"] is False


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


def test_legacy_plain_national_cuisine_adds_presentation_without_rewriting_data(
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
    assert saved["category_name"] == "United Kingdom"
    assert saved["migration"] == {"recipe_records": 0, "cookbook_records": 0}

    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe_payload["cuisine"] == "United Kingdom"
    assert recipe_payload["cuisine_tags"] == [
        "United Kingdom",
        "🇬🇧 United Kingdom",
        "Italian",
    ]
    cookbook_payload = json.loads(cookbook_path.read_text(encoding="utf-8"))
    assert cookbook_payload["cookbooks"][0]["recipes"][0]["cuisine"] == (
        "United Kingdom"
    )

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    category = category_named(registry, "🇬🇧 United Kingdom")
    assert category["aliases"] == ["United Kingdom"]
    assert category["recipe_count"] == 1
    assert sum(item["id"] == category_id for item in registry["categories"]) == 1


def test_icon_only_edit_updates_display_without_rewriting_recipe_values(
    cuisine_workspace,
):
    created = cuisines.save_workspace_cuisine_category(
        {"name": "United Kingdom", "active": True},
        user_id="user-a",
    )
    category_id = created["category_id"]
    recipe_path = write_recipe_output(
        "user-a",
        "https://example.test/icon-only-cuisine-edit",
        {
            "recipe_title": "British plate",
            "cuisine": "United Kingdom",
            "cuisine_tags": ["United Kingdom", "Italian"],
        },
    )

    updated = cuisines.save_workspace_cuisine_category(
        {"icon": "🏰"},
        category_id=category_id,
        user_id="user-a",
    )

    assert updated["ok"] is True
    assert updated["category_name"] == "United Kingdom"
    assert updated["display_label"] == "🏰 United Kingdom"
    assert updated["migration"] == {"recipe_records": 0, "cookbook_records": 0}
    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe_payload["cuisine"] == "United Kingdom"
    assert recipe_payload["cuisine_tags"] == ["United Kingdom", "Italian"]

    registry = cuisines.cuisine_category_registry_payload(
        "user-a",
        include_usage=True,
    )
    category = category_named(registry, "🏰 United Kingdom")
    assert category["category_name"] == "United Kingdom"
    assert "🇬🇧 United Kingdom" in category["aliases"]
    assert category["recipe_count"] == 1


def test_icon_only_legacy_flag_normalization_does_not_rewrite_assignments(
    cuisine_workspace,
):
    category_id = "custom_legacy_british_isles"
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        cuisines._seed_registry(connection, "user-a")
        timestamp = master_data.utc_now_iso()
        connection.execute(
            """
            INSERT INTO workspace_cuisine_categories (
                user_id, id, icon, abbreviation, name, normalized_name,
                aliases_json, is_seeded, is_active, sort_order, created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, '[]', 0, 1, 10, ?, ?)
            """,
            (
                "user-a",
                category_id,
                "🇬🇧",
                "GBR",
                "British Isles",
                "british isles",
                timestamp,
                timestamp,
            ),
        )
    recipe_path = write_recipe_output(
        "user-a",
        "https://example.test/legacy-flag-token-normalization",
        {
            "recipe_title": "British plate",
            "cuisine": "🇬🇧 British Isles",
            "cuisine_tags": ["🇬🇧 British Isles", "Italian"],
        },
    )

    updated = cuisines.save_workspace_cuisine_category(
        {"icon": "FLAG:GB"},
        category_id=category_id,
        user_id="user-a",
    )

    assert updated["ok"] is True
    assert updated["icon"] == "flag:gb"
    assert updated["display_label"] == "🇬🇧 British Isles"
    assert updated["migration"] == {"recipe_records": 0, "cookbook_records": 0}
    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe_payload["cuisine"] == "🇬🇧 British Isles"
    assert recipe_payload["cuisine_tags"] == ["🇬🇧 British Isles", "Italian"]
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        stored = connection.execute(
            """
            SELECT icon, name
              FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            ("user-a", category_id),
        ).fetchone()
    assert dict(stored) == {
        "icon": "flag:gb",
        "name": "British Isles",
    }


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


def test_rename_leaves_ambiguous_legacy_alias_assignments_unchanged(
    cuisine_workspace,
):
    timestamp = master_data.utc_now_iso()
    with master_data.recipe_master_connection(user_id="user-a") as connection:
        cuisines._seed_registry(connection, "user-a")
        for category_id, name in (
            ("custom_first", "First Cuisine"),
            ("custom_second", "Second Cuisine"),
        ):
            connection.execute(
                """
                INSERT INTO workspace_cuisine_categories (
                    user_id, id, name, normalized_name, aliases_json,
                    is_seeded, is_active, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 1, 10, ?, ?)
                """,
                (
                    "user-a",
                    category_id,
                    name,
                    cuisines.cuisine_category_key(name),
                    json.dumps(["Shared Legacy"]),
                    timestamp,
                    timestamp,
                ),
            )

    ambiguous_path = write_recipe_output(
        "user-a",
        "https://example.test/ambiguous-cuisine-alias",
        {"cuisine": "Shared Legacy", "cuisine_tags": ["Shared Legacy"]},
    )
    direct_path = write_recipe_output(
        "user-a",
        "https://example.test/direct-cuisine-name",
        {"cuisine": "First Cuisine", "cuisine_tags": ["First Cuisine"]},
    )

    renamed = cuisines.save_workspace_cuisine_category(
        {"category_name": "Renamed Cuisine"},
        category_id="custom_first",
        user_id="user-a",
    )

    assert renamed["ok"] is True
    assert renamed["migration"] == {"recipe_records": 1, "cookbook_records": 0}
    ambiguous = json.loads(ambiguous_path.read_text(encoding="utf-8"))
    direct = json.loads(direct_path.read_text(encoding="utf-8"))
    assert ambiguous["cuisine"] == "Shared Legacy"
    assert ambiguous["cuisine_tags"] == ["Shared Legacy"]
    assert direct["cuisine"] == "Renamed Cuisine"
    assert direct["cuisine_tags"] == ["Renamed Cuisine"]


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
