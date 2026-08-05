import json
import sqlite3
from copy import deepcopy
from pathlib import Path

from PushShoppingList.services import recipe_ingredient_requirement_service as repository
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services import storage_service


FIXTURES = Path(__file__).parent / "fixtures"
CORN_FIXTURE = FIXTURES / "corn_spoon_bread_requirements.json"
LIVE_MASTER_DB = Path(master_data.RECIPE_MASTER_DB_PATH).resolve()


def configure_isolated_repository(monkeypatch, tmp_path):
    db_path = (tmp_path / "isolated-recipe-master.sqlite3").resolve()
    assert db_path != LIVE_MASTER_DB
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(db_path))
    return db_path


def load_corn_fixture():
    return json.loads(CORN_FIXTURE.read_text(encoding="utf-8"))


def requirement_by_id(requirements, requirement_id):
    return next(row for row in requirements if row["id"] == requirement_id)


def option_by_id(requirement, option_id):
    return next(row for row in requirement["options"] if row["id"] == option_id)


def repository_round_trip_recipe():
    return {
        "source_url": "https://example.test/requirement-round-trip/",
        "recipe_title": "Requirement Round Trip",
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-flour",
                "ingredient": "Flour",
                "quantity": "2",
                "unit": "cups",
                "original_text": "2 cups flour",
                "future_requirement_metadata": {
                    "source": "synthetic-fixture",
                    "confidence_vector": [0.25, 0.75],
                },
                "metadata": {
                    "legacy_wrapper": True,
                    "nested_confidence": 0.88,
                },
            },
            {
                "recipe_ingredient_id": "requirement-butter",
                "ingredient": "Butter",
                "quantity": "1",
                "unit": "tablespoon",
                "original_text": "1 tablespoon butter",
                "default_option_id": "alternative-margarine",
                "substitutions": [
                    {
                        "alternative_id": "alternative-margarine",
                        "alternative_order": 4,
                        "alternative_label": "Margarine",
                        "option_type": "substitution",
                        "ingredient": "Margarine",
                        "quantity": "1",
                        "unit": "tablespoon",
                        "future_classifier": {
                            "model": "fixture-v1",
                            "scores": {"match": 0.91},
                        },
                    }
                ],
            },
            {
                "recipe_ingredient_id": "requirement-buttermilk",
                "ingredient": "Buttermilk",
                "quantity": "1",
                "unit": "cup",
                "original_text": "1 cup buttermilk",
                "default_option_id": "alternative-milk-lemon",
                "substitutions": [
                    {
                        "alternative_id": "alternative-milk-lemon",
                        "alternative_order": 2,
                        "alternative_label": "Milk and lemon juice",
                        "option_type": "substitution",
                        "group_provenance": {"author": "fixture"},
                        "ingredients": [
                            {
                                "ingredient": "Milk",
                                "quantity": "1",
                                "unit": "cup",
                                "component_marker": "first",
                            },
                            {
                                "ingredient": "Lemon juice",
                                "quantity": "1",
                                "unit": "tablespoon",
                                "component_marker": "second",
                            },
                        ],
                    }
                ],
            },
        ],
    }


def table_counts(connection):
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "recipe_ingredient_requirements",
            "recipe_ingredient_options",
            "recipe_ingredient_option_items",
        )
    }


def test_requirement_schema_is_idempotent_indexed_and_foreign_keyed(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)

    master_data.ensure_recipe_master_schema()
    master_data.ensure_recipe_master_schema()

    with master_data.recipe_master_connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "recipe_ingredient_requirements",
            "recipe_ingredient_options",
            "recipe_ingredient_option_items",
        } <= tables

        requirement_indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(recipe_ingredient_requirements)"
            )
        }
        option_indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(recipe_ingredient_options)"
            )
        }
        item_indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(recipe_ingredient_option_items)"
            )
        }
        assert "idx_recipe_ingredient_requirements_user_recipe_order" in requirement_indexes
        assert "idx_recipe_ingredient_options_requirement_order" in option_indexes
        assert "idx_recipe_ingredient_option_items_option_order" in item_indexes

        option_foreign_keys = [
            dict(row)
            for row in connection.execute(
                "PRAGMA foreign_key_list(recipe_ingredient_options)"
            )
        ]
        item_foreign_keys = [
            dict(row)
            for row in connection.execute(
                "PRAGMA foreign_key_list(recipe_ingredient_option_items)"
            )
        ]
        assert any(
            row["table"] == "recipe_ingredient_requirements"
            and row["from"] == "requirement_id"
            and row["on_delete"] == "CASCADE"
            for row in option_foreign_keys
        )
        assert any(
            row["table"] == "recipe_ingredient_options"
            and row["from"] == "option_id"
            and row["on_delete"] == "CASCADE"
            for row in item_foreign_keys
        )
        assert any(
            row["table"] == "ingredients"
            and row["from"] == "ingredient_id"
            and row["on_delete"] == "SET NULL"
            for row in item_foreign_keys
        )


def test_repository_round_trips_simple_single_and_nested_options_with_metadata(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    recipe = repository_round_trip_recipe()
    recipe_url = recipe["source_url"]

    result = repository.save_recipe_ingredient_requirements(
        recipe_url,
        recipe,
        user_id="user-a",
        sync_compatibility=False,
    )

    assert result["requirement_count"] == 3
    assert result["option_count"] == 5
    assert result["option_item_count"] == 6
    assert result["malformed_records"] == 0
    requirements = repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id="user-a",
    )

    flour = requirement_by_id(requirements, "requirement-flour")
    assert flour["default_option_id"] == "original:requirement-flour"
    assert flour["selection_required"] is False
    assert [option["option_type"] for option in flour["options"]] == ["original"]
    assert flour["metadata"]["future_requirement_metadata"] == {
        "source": "synthetic-fixture",
        "confidence_vector": [0.25, 0.75],
    }
    assert flour["options"][0]["items"][0]["metadata"][
        "future_requirement_metadata"
    ] == flour["metadata"]["future_requirement_metadata"]

    butter = requirement_by_id(requirements, "requirement-butter")
    assert butter["default_option_id"] == "alternative-margarine"
    assert [option["id"] for option in butter["options"]] == [
        "original:requirement-butter",
        "alternative-margarine",
    ]
    margarine = option_by_id(butter, "alternative-margarine")
    assert margarine["option_type"] == "substitution"
    assert [item["ingredient"] for item in margarine["items"]] == ["Margarine"]
    assert margarine["items"][0]["metadata"]["future_classifier"] == {
        "model": "fixture-v1",
        "scores": {"match": 0.91},
    }

    buttermilk = requirement_by_id(requirements, "requirement-buttermilk")
    replacement = option_by_id(buttermilk, "alternative-milk-lemon")
    assert replacement["sort_order"] == 2
    assert [item["ingredient"] for item in replacement["items"]] == [
        "Milk",
        "Lemon juice",
    ]
    assert [item["sort_order"] for item in replacement["items"]] == [0, 1]
    assert [
        item["metadata"]["component_marker"] for item in replacement["items"]
    ] == ["first", "second"]
    assert all(
        item["metadata"]["group_provenance"] == {"author": "fixture"}
        for item in replacement["items"]
    )

    legacy = repository.legacy_ingredients_from_requirements(requirements)
    legacy_by_id = {row["recipe_ingredient_id"]: row for row in legacy}
    assert legacy_by_id["requirement-flour"]["future_requirement_metadata"] == {
        "source": "synthetic-fixture",
        "confidence_vector": [0.25, 0.75],
    }
    assert legacy_by_id["requirement-flour"]["metadata"] == {
        "legacy_wrapper": True,
        "nested_confidence": 0.88,
    }
    assert "legacy_wrapper" not in legacy_by_id["requirement-flour"]
    nested_rows = legacy_by_id["requirement-buttermilk"]["substitutions"]
    assert {row["alternative_id"] for row in nested_rows} == {
        "alternative-milk-lemon"
    }
    assert [row["alternative_component_order"] for row in nested_rows] == [0, 1]


def test_explicit_original_round_trip_preserves_parent_and_component_provenance(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    recipe_url = "https://example.test/explicit-original-provenance/"
    source_ingredient = {
        "recipe_ingredient_id": "requirement-corn-blend",
        "ingredient": "fresh corn blend",
        "quantity": "1",
        "unit": "cup",
        "preparation": "fresh",
        "original_text": "1 cup fresh corn blend",
        "default_option_id": "option-original-corn-blend",
        "selection_required": True,
        "image_url": "https://images.example.test/corn-blend.webp",
        "image_prompt": "A bowl of fresh corn blend",
        "classifier_version": "parent-fixture-v2",
        "food_review": {"status": "approved", "reviewer": "fixture"},
        "parent_provenance": {"source": "recipe-editor", "confidence": 0.92},
        "substitutions": [
            {
                "alternative_id": "option-original-corn-blend",
                "alternative_order": 0,
                "alternative_component_order": 0,
                "alternative_label": "fresh corn blend",
                "option_type": "original",
                "recipe_authored": True,
                "is_default": True,
                "preferred": True,
                "ingredient": "corn",
                "quantity": "1",
                "unit": "cup",
                "preparation": "fresh",
                "optional": False,
                "original_text": "1 cup fresh corn",
                "image_prompt": "Fresh corn component",
                "classifier_payload": {"class": "produce"},
                "component_provenance": {"source": "recipe"},
            },
            {
                "alternative_id": "option-original-corn-blend",
                "alternative_order": 0,
                "alternative_component_order": 1,
                "alternative_label": "fresh corn blend",
                "option_type": "original",
                "recipe_authored": False,
                "is_default": True,
                "preferred": True,
                "ingredient": "onion",
                "optional": True,
                "original_text": "onion",
                "image_prompt": "Onion component",
                "classifier_payload": {"class": "produce"},
                "component_provenance": {"source": "recipe-editor"},
            },
            {
                "alternative_id": "option-frozen-corn",
                "alternative_order": 1,
                "alternative_component_order": 0,
                "alternative_label": "frozen corn",
                "option_type": "recipe_choice",
                "recipe_authored": True,
                "is_default": False,
                "preferred": False,
                "ingredient": "corn",
                "quantity": "1",
                "unit": "cup",
                "preparation": "frozen",
                "optional": False,
                "original_text": "1 cup frozen corn",
                "component_provenance": {"source": "inline-choice"},
            },
        ],
    }
    recipe = {
        "source_url": recipe_url,
        "recipe_title": "Explicit Original Provenance",
        "ingredients": [deepcopy(source_ingredient)],
    }

    saved = repository.save_recipe_ingredient_requirements(
        recipe_url,
        recipe,
        user_id="provenance-user",
        sync_compatibility=False,
    )
    assert saved["malformed_records"] == 0

    requirements = repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id="provenance-user",
    )
    explicit_original = option_by_id(
        requirements[0],
        "option-original-corn-blend",
    )
    assert [item["metadata"]["component_provenance"] for item in explicit_original["items"]] == [
        {"source": "recipe"},
        {"source": "recipe-editor"},
    ]

    exported = repository.legacy_ingredients_from_requirements(requirements)
    assert exported == [source_ingredient]


def test_sql_requirement_overlay_falls_back_to_an_independent_json_copy(
    monkeypatch,
    tmp_path,
):
    db_path = configure_isolated_repository(monkeypatch, tmp_path)
    recipe_url = "https://example.test/json-fallback/"
    json_recipe = {
        "source_url": recipe_url,
        "recipe_title": "JSON fallback",
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-json-onion",
                "ingredient": "JSON onion",
                "metadata": {"origin": "full-output-json"},
            }
        ],
    }

    result = repository.recipe_data_with_sql_requirements(
        recipe_url,
        json_recipe,
        user_id="unsynced-user",
    )

    assert result == json_recipe
    assert result is not json_recipe
    assert result["ingredients"] is not json_recipe["ingredients"]
    result["ingredients"][0]["metadata"]["origin"] = "mutated-copy"
    assert json_recipe["ingredients"][0]["metadata"]["origin"] == "full-output-json"
    assert not db_path.exists()


def test_recipe_output_loader_prefers_sql_requirements_over_stale_json(
    monkeypatch,
    tmp_path,
):
    from PushShoppingList.services import recipe_edit_service

    configure_isolated_repository(monkeypatch, tmp_path)
    output_root = tmp_path / "recipe-output-loader" / "output"
    output_root.mkdir(parents=True)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_root)
    recipe_url = "https://example.test/sql-preferred-loader/"
    stale_json = {
        "source_url": recipe_url,
        "recipe_title": "Keep this JSON title",
        "instructions": ["Keep this JSON instruction."],
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-stale-onion",
                "ingredient": "Stale JSON onion",
            }
        ],
    }
    sql_recipe = {
        "source_url": recipe_url,
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-sql-carrot",
                "ingredient": "SQL carrot",
                "quantity": "2",
                "unit": "count",
                "original_text": "2 SQL carrots",
            }
        ],
    }
    output_path = recipe_edit_service.recipe_output_json_path(
        recipe_url,
        output_folder=output_root,
    )
    output_path.write_text(json.dumps(stale_json, indent=2), encoding="utf-8")
    repository.save_recipe_ingredient_requirements(
        recipe_url,
        sql_recipe,
        user_id=master_data.LOCAL_USER_ID,
        sync_compatibility=False,
    )

    loaded = recipe_edit_service.load_recipe_output(recipe_url)

    assert loaded["recipe_title"] == "Keep this JSON title"
    assert loaded["instructions"] == ["Keep this JSON instruction."]
    assert [row["ingredient"] for row in loaded["ingredients"]] == ["SQL carrot"]
    assert json.loads(output_path.read_text(encoding="utf-8")) == stale_json


def test_shopping_resolution_prefers_sql_and_keeps_context_selection_separate(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    monkeypatch.setattr(
        shopping_list_service,
        "SHOPPING_LIST_FILE",
        tmp_path / "shopping-list.txt",
    )
    monkeypatch.setattr(
        shopping_list_service,
        "SHOPPING_LIST_SELECTIONS_FILE",
        tmp_path / "shopping-selections.json",
    )
    recipe_url = "https://example.test/sql-shopping-resolution/"
    stale_json = {
        "source_url": recipe_url,
        "ingredients": [{
            "recipe_ingredient_id": "requirement-stale",
            "ingredient": "Stale JSON ingredient",
        }],
    }
    sql_recipe = {
        "source_url": recipe_url,
        "ingredients": [{
            "recipe_ingredient_id": "requirement-milk",
            "ingredient": "Whole milk",
            "quantity": "1",
            "unit": "cup",
            "default_option_id": "alternative-oat-milk",
            "substitutions": [{
                "alternative_id": "alternative-oat-milk",
                "alternative_label": "Oat milk",
                "option_type": "substitution",
                "ingredient": "Oat milk",
                "quantity": "1",
                "unit": "cup",
                "is_default": True,
                "preferred": True,
            }],
        }],
    }
    repository.save_recipe_ingredient_requirements(
        recipe_url,
        sql_recipe,
        user_id=master_data.LOCAL_USER_ID,
        sync_compatibility=False,
    )

    contextual = shopping_list_service.finalize_recipe_items(
        recipe_url,
        stale_json,
        {"requirement-milk": "original:requirement-milk"},
    )
    assert contextual["added"] == ["Whole milk"]
    assert contextual["selected_options"] == {
        "requirement-milk": "original:requirement-milk"
    }

    requirements = repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id=master_data.LOCAL_USER_ID,
    )
    assert requirements[0]["default_option_id"] == "alternative-oat-milk"

    defaulted = shopping_list_service.finalize_recipe_items(
        recipe_url,
        stale_json,
    )
    assert defaulted["added"] == ["Oat milk"]
    assert defaulted["selected_options"] == {
        "requirement-milk": "alternative-oat-milk"
    }
    assert shopping_list_service.load_items() == ["Whole milk", "Oat milk"]


def test_relational_amount_unit_and_preparation_drive_compatibility_export(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    recipe_url = "https://example.test/relational-columns-authoritative/"
    repository.save_recipe_ingredient_requirements(
        recipe_url,
        {
            "source_url": recipe_url,
            "ingredients": [{
                "recipe_ingredient_id": "requirement-onion",
                "ingredient": "Onion",
                "quantity": "1",
                "unit": "cup",
                "preparation": "diced",
            }],
        },
        user_id="authority-user",
        sync_compatibility=False,
    )

    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE recipe_ingredient_option_items
               SET quantity = '2', unit = 'tablespoon', unit_raw = '',
                   preparation = 'thinly sliced'
             WHERE id = (
                SELECT item.id
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement
                    ON requirement.id = option.requirement_id
                 WHERE requirement.user_id = ? AND requirement.recipe_id = ?
             )
            """,
            ("authority-user", master_data.recipe_id_for_url(recipe_url)),
        )

    exported = repository.load_legacy_ingredients_from_sql(
        recipe_url,
        user_id="authority-user",
    )
    assert exported[0]["quantity"] == "2"
    assert exported[0]["unit"] == "tablespoon"
    assert exported[0]["preparation"] == "thinly sliced"


def test_malformed_legacy_alternatives_are_reported_preserved_and_backfilled(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    data_root = tmp_path / "workspace" / "recipe-extractor" / "data"
    output_root = data_root / "output"
    output_root.mkdir(parents=True)
    recipe_url = "https://example.test/malformed-alternatives/"
    malformed_values = [
        {
            "alternative_id": "empty-component-group",
            "ingredients": [],
            "opaque_group_data": {"preserve": True},
        },
        {"unexpected_payload": {"preserve": [1, 2, 3]}},
        "",
    ]
    recipe = {
        "source_url": recipe_url,
        "recipe_title": "Malformed Alternatives",
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-broth",
                "ingredient": "Broth",
                "original_text": "1 cup broth",
                "substitutions": deepcopy(malformed_values),
            }
        ],
    }
    output_path = output_root / "malformed-alternatives.json"
    output_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")

    summary = repository.backfill_recipe_ingredient_requirements_for_user(
        "user-a",
        extractor_data_root=data_root,
        recipe_url=recipe_url,
        dry_run=False,
    )

    assert summary["recipes_scanned"] == 1
    assert summary["requirements_inserted"] == 1
    assert summary["options_inserted"] == 1
    assert summary["option_items_inserted"] == 1
    assert summary["malformed_records"] == 3
    assert summary["skipped_records"] == 0
    assert {issue["reason"] for issue in summary["issues"]} == {
        "grouped alternative has no components",
        "alternative has no ingredient name",
        "empty alternative text",
    }
    assert len(summary["backup_files"]) == 1
    assert json.loads(Path(summary["backup_files"][0]).read_text(encoding="utf-8")) == recipe

    requirements = repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id="user-a",
    )
    exported = repository.legacy_ingredients_from_requirements(requirements)
    assert exported[0]["substitutions"] == malformed_values


def test_same_recipe_and_stable_ids_are_isolated_per_user(monkeypatch, tmp_path):
    configure_isolated_repository(monkeypatch, tmp_path)
    recipe_url = "https://example.test/shared-requirement/"
    user_a_recipe = {
        "source_url": recipe_url,
        "ingredients": [
            {
                "recipe_ingredient_id": "shared-requirement-id",
                "ingredient": "Onion",
                "quantity": "1",
            }
        ],
    }
    user_b_recipe = {
        "source_url": recipe_url,
        "ingredients": [
            {
                "recipe_ingredient_id": "shared-requirement-id",
                "ingredient": "Carrot",
                "quantity": "2",
            }
        ],
    }

    repository.save_recipe_ingredient_requirements(
        recipe_url,
        user_a_recipe,
        user_id="user-a",
        sync_compatibility=False,
    )
    repository.save_recipe_ingredient_requirements(
        recipe_url,
        user_b_recipe,
        user_id="user-b",
        sync_compatibility=False,
    )

    user_a = repository.load_recipe_ingredient_requirements(recipe_url, user_id="user-a")
    user_b = repository.load_recipe_ingredient_requirements(recipe_url, user_id="user-b")
    assert user_a[0]["id"] == user_b[0]["id"] == "shared-requirement-id"
    assert user_a[0]["options"][0]["items"][0]["ingredient"] == "Onion"
    assert user_b[0]["options"][0]["items"][0]["ingredient"] == "Carrot"
    assert repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id="user-c",
    ) is None

    with master_data.recipe_master_connection() as connection:
        rows = connection.execute(
            """
            SELECT user_id, COUNT(*) AS row_count
              FROM recipe_ingredient_requirements
             GROUP BY user_id
             ORDER BY user_id
            """
        ).fetchall()
        assert [(row["user_id"], row["row_count"]) for row in rows] == [
            ("user-a", 1),
            ("user-b", 1),
        ]


def test_default_backfill_roots_isolate_local_signed_in_and_guest_scopes(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    legacy_extractor = tmp_path / "scopes" / "legacy-recipe-extractor"
    user_data_root = tmp_path / "scopes" / "users"
    guest_data_root = tmp_path / "scopes" / "guests"
    monkeypatch.setattr(storage_service, "LEGACY_EXTRACTOR_DIR", legacy_extractor)
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", user_data_root)
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", guest_data_root)

    recipe_url = "https://example.test/default-scope-routing/"
    cases = [
        (
            master_data.LOCAL_USER_ID,
            legacy_extractor / "data",
            "Local turnip",
        ),
        (
            "signed-user",
            user_data_root / "signed-user" / "recipe-extractor" / "data",
            "Signed-in parsnip",
        ),
        (
            "guest:guest-session",
            guest_data_root / "guest-session" / "recipe-extractor" / "data",
            "Guest rutabaga",
        ),
    ]

    for user_id, data_root, ingredient_name in cases:
        output_root = data_root / "output"
        output_root.mkdir(parents=True)
        recipe = {
            "source_url": recipe_url,
            "ingredients": [
                {
                    "recipe_ingredient_id": "shared-scope-requirement",
                    "ingredient": ingredient_name,
                }
            ],
        }
        (output_root / "scope-recipe.json").write_text(
            json.dumps(recipe, indent=2),
            encoding="utf-8",
        )

        summary = repository.backfill_recipe_ingredient_requirements_for_user(
            user_id,
            dry_run=False,
        )
        assert summary["source_root"] == str(data_root)
        assert summary["requirements_inserted"] == 1

    for user_id, _data_root, ingredient_name in cases:
        requirements = repository.load_recipe_ingredient_requirements(
            recipe_url,
            user_id=user_id,
        )
        assert requirements[0]["options"][0]["items"][0]["ingredient"] == ingredient_name

    with master_data.recipe_master_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM recipe_ingredient_requirements"
        ).fetchone()[0] == 3


def test_backfill_uses_full_output_json_and_records_idempotent_audit_runs(
    monkeypatch,
    tmp_path,
):
    db_path = configure_isolated_repository(monkeypatch, tmp_path)
    data_root = tmp_path / "migration-source" / "recipe-extractor" / "data"
    output_root = data_root / "output"
    output_root.mkdir(parents=True)
    recipe_url = "https://example.test/full-output-is-authoritative/"
    full_output_recipe = {
        "source_url": recipe_url,
        "recipe_title": "Full output source",
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-full-output",
                "ingredient": "Full output fennel",
                "quantity": "1",
                "unit": "bulb",
                "source_proof": "full-output-json",
            }
        ],
    }
    derived_recipe_ingredients = {
        "source_url": recipe_url,
        "ingredients": [
            {
                "recipe_ingredient_id": "requirement-derived-sentinel",
                "ingredient": "Derived sentinel must not migrate",
            },
            {
                "recipe_ingredient_id": "requirement-derived-sentinel-two",
                "ingredient": "Second derived sentinel must not migrate",
            },
        ],
    }
    output_path = output_root / "full-output-source.json"
    output_path.write_text(
        json.dumps(full_output_recipe, indent=2),
        encoding="utf-8",
    )
    (data_root / "recipe_ingredients.json").write_text(
        json.dumps(derived_recipe_ingredients, indent=2),
        encoding="utf-8",
    )

    dry_run = repository.backfill_recipe_ingredient_requirements_for_user(
        "audit-user",
        extractor_data_root=data_root,
        dry_run=True,
    )
    assert dry_run["recipes_scanned"] == 1
    assert dry_run["requirements_inserted"] == 1
    assert dry_run["options_inserted"] == 1
    assert dry_run["option_items_inserted"] == 1
    assert not db_path.exists()

    first_apply = repository.backfill_recipe_ingredient_requirements_for_user(
        "audit-user",
        extractor_data_root=data_root,
        dry_run=False,
    )
    assert first_apply["requirements_inserted"] == 1
    assert len(first_apply["backup_files"]) == 1
    assert json.loads(
        Path(first_apply["backup_files"][0]).read_text(encoding="utf-8")
    ) == full_output_recipe

    requirements = repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id="audit-user",
    )
    assert [row["id"] for row in requirements] == ["requirement-full-output"]
    assert requirements[0]["label"] == "Full output fennel"
    assert requirements[0]["metadata"]["source_proof"] == "full-output-json"

    with master_data.recipe_master_connection() as connection:
        first_counts = table_counts(connection)
        audit_rows = connection.execute(
            """
            SELECT mode, source_root, status, summary_json
              FROM recipe_ingredient_requirement_migration_runs
             WHERE user_id = ?
             ORDER BY id
            """,
            ("audit-user",),
        ).fetchall()
    assert first_counts == {
        "recipe_ingredient_requirements": 1,
        "recipe_ingredient_options": 1,
        "recipe_ingredient_option_items": 1,
    }
    assert len(audit_rows) == 1
    assert audit_rows[0]["mode"] == "apply"
    assert audit_rows[0]["source_root"] == str(data_root)
    assert audit_rows[0]["status"] == "complete"
    stored_summary = json.loads(audit_rows[0]["summary_json"])
    assert stored_summary["recipes_scanned"] == 1
    assert stored_summary["requirements_inserted"] == 1
    assert stored_summary["source_root"] == str(data_root)

    second_apply = repository.backfill_recipe_ingredient_requirements_for_user(
        "audit-user",
        extractor_data_root=data_root,
        dry_run=False,
    )
    assert second_apply["recipes_scanned"] == 1
    assert second_apply["skipped_records"] == 1
    assert second_apply["requirements_inserted"] == 0
    with master_data.recipe_master_connection() as connection:
        assert table_counts(connection) == first_counts
        assert connection.execute(
            """
            SELECT COUNT(*)
              FROM recipe_ingredient_requirement_migration_runs
             WHERE user_id = ?
            """,
            ("audit-user",),
        ).fetchone()[0] == 1

    forced_apply = repository.backfill_recipe_ingredient_requirements_for_user(
        "audit-user",
        extractor_data_root=data_root,
        dry_run=False,
        force=True,
    )
    assert forced_apply["requirements_inserted"] == 1
    assert forced_apply["options_inserted"] == 1
    assert forced_apply["option_items_inserted"] == 1
    with master_data.recipe_master_connection() as connection:
        assert table_counts(connection) == first_counts
        forced_audits = connection.execute(
            """
            SELECT status, summary_json
              FROM recipe_ingredient_requirement_migration_runs
             WHERE user_id = ?
             ORDER BY id
            """,
            ("audit-user",),
        ).fetchall()
    assert [row["status"] for row in forced_audits] == ["complete", "complete"]
    assert json.loads(forced_audits[1]["summary_json"])["requirements_inserted"] == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == full_output_recipe


def test_deleting_requirement_cascades_to_options_and_items(monkeypatch, tmp_path):
    configure_isolated_repository(monkeypatch, tmp_path)
    recipe = repository_round_trip_recipe()
    repository.save_recipe_ingredient_requirements(
        recipe["source_url"],
        recipe,
        user_id="user-a",
        sync_compatibility=False,
    )

    with master_data.recipe_master_connection() as connection:
        requirement_row = connection.execute(
            """
            SELECT id
              FROM recipe_ingredient_requirements
             WHERE user_id = ? AND requirement_id = ?
            """,
            ("user-a", "requirement-buttermilk"),
        ).fetchone()
        option_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM recipe_ingredient_options WHERE requirement_id = ?",
                (requirement_row["id"],),
            )
        ]
        placeholders = ",".join("?" for _ in option_ids)
        assert len(option_ids) == 2
        assert connection.execute(
            f"SELECT COUNT(*) FROM recipe_ingredient_option_items WHERE option_id IN ({placeholders})",
            option_ids,
        ).fetchone()[0] == 3

        connection.execute(
            "DELETE FROM recipe_ingredient_requirements WHERE id = ?",
            (requirement_row["id"],),
        )

        assert connection.execute(
            "SELECT COUNT(*) FROM recipe_ingredient_options WHERE requirement_id = ?",
            (requirement_row["id"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            f"SELECT COUNT(*) FROM recipe_ingredient_option_items WHERE option_id IN ({placeholders})",
            option_ids,
        ).fetchone()[0] == 0


def test_deleting_master_ingredient_nulls_reference_and_preserves_option_item(
    monkeypatch,
    tmp_path,
):
    configure_isolated_repository(monkeypatch, tmp_path)
    recipe_url = "https://example.test/set-null-master-ingredient/"
    repository.save_recipe_ingredient_requirements(
        recipe_url,
        {
            "source_url": recipe_url,
            "ingredients": [
                {
                    "recipe_ingredient_id": "requirement-preserved-leek",
                    "ingredient": "Preserved leek",
                    "quantity": "2",
                    "unit": "count",
                    "original_text": "2 preserved leeks",
                }
            ],
        },
        user_id="set-null-user",
        sync_compatibility=False,
    )

    with master_data.recipe_master_connection() as connection:
        before = connection.execute(
            """
            SELECT item.id, item.ingredient_id, item.option_id, item.raw_name,
                   item.quantity, item.unit
              FROM recipe_ingredient_option_items item
              JOIN recipe_ingredient_options option ON option.id = item.option_id
              JOIN recipe_ingredient_requirements requirement
                ON requirement.id = option.requirement_id
             WHERE requirement.user_id = ? AND requirement.recipe_id = ?
            """,
            ("set-null-user", master_data.recipe_id_for_url(recipe_url)),
        ).fetchone()
        assert before is not None
        assert before["ingredient_id"] is not None

        connection.execute(
            "DELETE FROM ingredients WHERE id = ?",
            (before["ingredient_id"],),
        )

        after = connection.execute(
            """
            SELECT id, ingredient_id, option_id, raw_name, quantity, unit
              FROM recipe_ingredient_option_items
             WHERE id = ?
            """,
            (before["id"],),
        ).fetchone()
        assert after is not None
        assert after["ingredient_id"] is None
        assert after["option_id"] == before["option_id"]
        assert after["raw_name"] == before["raw_name"] == "Preserved leek"
        assert after["quantity"] == before["quantity"] == "2"
        assert after["unit"] == before["unit"] == "count"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_corn_spoon_bread_backfill_is_idempotent_and_preserves_grouping(
    monkeypatch,
    tmp_path,
):
    db_path = configure_isolated_repository(monkeypatch, tmp_path)
    recipe = load_corn_fixture()
    recipe_url = recipe["source_url"]
    data_root = tmp_path / "corn-workspace" / "recipe-extractor" / "data"
    output_root = data_root / "output"
    output_root.mkdir(parents=True)
    output_path = output_root / "vegetablerecipes_com_corn-spoon-bread.json"
    output_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")

    dry_run = repository.backfill_recipe_ingredient_requirements_for_user(
        "corn-fixture-user",
        extractor_data_root=data_root,
        recipe_url=recipe_url,
        dry_run=True,
    )
    assert dry_run["recipes_scanned"] == 1
    assert dry_run["requirements_inserted"] == 10
    assert dry_run["options_inserted"] == 12
    assert dry_run["option_items_inserted"] == 15
    assert dry_run["malformed_records"] == 0
    assert not db_path.exists()

    first_apply = repository.backfill_recipe_ingredient_requirements_for_user(
        "corn-fixture-user",
        extractor_data_root=data_root,
        recipe_url=recipe_url,
        dry_run=False,
    )
    assert first_apply["requirements_inserted"] == 10
    assert first_apply["options_inserted"] == 12
    assert first_apply["option_items_inserted"] == 15
    assert json.loads(output_path.read_text(encoding="utf-8")) == recipe

    requirements = repository.load_recipe_ingredient_requirements(
        recipe_url,
        user_id="corn-fixture-user",
    )
    assert len(requirements) == 10
    assert sum(len(row["options"]) for row in requirements) == 12
    assert sum(
        len(option["items"])
        for requirement in requirements
        for option in requirement["options"]
    ) == 15
    assert "cumin" not in {row["label"] for row in requirements}
    assert "onion" not in {row["label"] for row in requirements}

    corn = requirement_by_id(requirements, "requirement-1b9b67bcc2c17d1f")
    assert corn["default_option_id"] == "251b794a-0bd2-4669-8fc9-8093e1fa5aa3"
    assert [option["id"] for option in corn["options"]] == [
        "251b794a-0bd2-4669-8fc9-8093e1fa5aa3",
        "inline-form-frozen-corn",
    ]
    assert [option["option_type"] for option in corn["options"]] == [
        "original",
        "recipe_choice",
    ]
    assert [item["ingredient"] for item in corn["options"][0]["items"]] == [
        "corn",
        "cumin",
        "onion",
    ]
    assert [item["ingredient"] for item in corn["options"][1]["items"]] == [
        "corn",
        "onion",
    ]

    butter = requirement_by_id(requirements, "requirement-e919369467e87fe1")
    assert butter["default_option_id"] == "original:requirement-e919369467e87fe1"
    assert [option["option_type"] for option in butter["options"]] == [
        "original",
        "custom",
    ]
    assert butter["options"][1]["id"] == "9eb050db-3429-48af-9ecb-65cae20d67c5"

    with master_data.recipe_master_connection() as connection:
        first_counts = table_counts(connection)
        compatibility_rows = connection.execute(
            """
            SELECT COUNT(*)
              FROM recipe_ingredients
             WHERE user_id = ? AND recipe_id = ?
            """,
            (
                "corn-fixture-user",
                master_data.recipe_id_for_url(recipe_url),
            ),
        ).fetchone()[0]
    assert first_counts == {
        "recipe_ingredient_requirements": 10,
        "recipe_ingredient_options": 12,
        "recipe_ingredient_option_items": 15,
    }
    assert compatibility_rows == 10

    second_apply = repository.backfill_recipe_ingredient_requirements_for_user(
        "corn-fixture-user",
        extractor_data_root=data_root,
        recipe_url=recipe_url,
        dry_run=False,
    )
    assert second_apply["recipes_scanned"] == 1
    assert second_apply["skipped_records"] == 1
    assert second_apply["requirements_inserted"] == 0
    assert second_apply["options_inserted"] == 0
    assert second_apply["option_items_inserted"] == 0

    forced_apply = repository.backfill_recipe_ingredient_requirements_for_user(
        "corn-fixture-user",
        extractor_data_root=data_root,
        recipe_url=recipe_url,
        dry_run=False,
        force=True,
    )
    assert forced_apply["requirements_inserted"] == 10
    assert forced_apply["options_inserted"] == 12
    assert forced_apply["option_items_inserted"] == 15
    with master_data.recipe_master_connection() as connection:
        assert table_counts(connection) == first_counts
