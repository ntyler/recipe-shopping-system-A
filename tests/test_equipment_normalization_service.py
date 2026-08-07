import pytest

from PushShoppingList.services import equipment_normalization_service as normalization
from PushShoppingList.services import recipe_equipment_requirement_service as requirements


def test_alternative_equipment_becomes_one_requirement_with_options():
    parsed = normalization.parse_equipment_list(["wok or large skillet"])

    assert len(parsed) == 1
    assert parsed[0]["connector"] == "or"
    assert [option["canonical_name"] for option in parsed[0]["options"]] == [
        "Wok",
        "Skillet",
    ]
    assert parsed[0]["options"][1]["attributes"] == {"size": "large"}


def test_conjoined_equipment_becomes_independent_requirements():
    parsed = normalization.parse_equipment_list(["knife and cutting board"])

    assert len(parsed) == 2
    assert {item["conjunction_group"] for item in parsed} != {""}
    assert [item["options"][0]["canonical_name"] for item in parsed] == [
        "Knife",
        "Cutting board",
    ]


def test_instruction_context_corrects_blender_conjunction_to_alternative():
    parsed = normalization.parse_equipment_list(
        ["blender and food processor"],
        instructions=["Blend the sauce in a blender or food processor."],
    )

    assert len(parsed) == 1
    assert parsed[0]["connector"] == "or"
    assert [option["canonical_key"] for option in parsed[0]["options"]] == [
        "blender",
        "food processor",
    ]


def test_alias_equivalent_alternative_collapses_to_one_option():
    parsed = normalization.parse_equipment_list(["fryer or deep fryer"])

    assert len(parsed) == 1
    assert parsed[0]["connector"] == "single"
    assert parsed[0]["options"][0]["canonical_name"] == "Deep fryer"


def test_notes_supplies_and_attributes_are_not_canonical_identity():
    parsed = normalization.parse_equipment_list([
        "deep fryer or large pot with oil",
        "plate or parchment paper",
    ])

    first = parsed[0]
    assert first["options"][1]["canonical_name"] == "Pot"
    assert first["options"][1]["attributes"] == {"size": "large"}
    assert first["options"][1]["notes"] == "with oil"
    assert parsed[1]["options"][1]["option_kind"] == "supply"


def test_schema_and_structured_writes_require_separate_explicit_gates(monkeypatch):
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        )
        """
    )

    try:
        requirements.ensure_structured_equipment_schema(connection, authorized=True)
    except PermissionError:
        pass
    else:
        raise AssertionError("Schema creation must remain locked by default")

    monkeypatch.setenv("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED", "true")
    requirements.ensure_structured_equipment_schema(connection, authorized=True)
    assert requirements.structured_equipment_schema_available(connection)

    parsed = normalization.parse_equipment_list(["wok or large skillet"])
    try:
        requirements.replace_recipe_requirements(
            connection,
            "user-a",
            "recipe-a",
            parsed,
            authorized=True,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Structured writes must remain independently locked")

    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED", "true")
    with pytest.raises(PermissionError):
        requirements.replace_recipe_requirements(
            connection,
            "user-a",
            "recipe-a",
            parsed,
            authorized=True,
        )
    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_WRITE_TENANTS", "user-a")
    summary = requirements.replace_recipe_requirements(
        connection,
        "user-a",
        "recipe-a",
        parsed,
        authorized=True,
    )
    assert summary["requirement_count"] == 1
    assert connection.execute("SELECT COUNT(*) FROM recipe_equipment_options").fetchone()[0] == 2


def test_feature_flagged_preview_preserves_legacy_equipment(monkeypatch):
    recipe = {
        "equipment": [{"equipment": "knife and cutting board"}],
        "instructions": [],
    }

    requirements.add_structured_equipment_preview(recipe)
    assert "equipment_requirements" not in recipe

    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED", "true")
    requirements.add_structured_equipment_preview(recipe)
    assert "equipment_requirements" not in recipe

    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_WRITE_TENANTS", "user-a")
    requirements.add_structured_equipment_preview(recipe, user_id="user-a")
    assert recipe["equipment"] == [{"equipment": "knife and cutting board"}]
    assert len(recipe["equipment_requirements"]) == 2


def test_review_queue_includes_structured_or_uncertain_rows_only():
    queue = requirements.review_queue_from_master_rows([
        {"id": 1, "name": "whisk", "usage_count": 3},
        {"id": 2, "name": "wok or large skillet", "usage_count": 2},
        {"id": 3, "name": "bowl", "usage_count": 1},
    ])

    assert [item["equipment_id"] for item in queue] == [2, 3]
    assert queue[0]["summary"]["alternative_requirement_count"] == 1
    assert queue[1]["review_status"] == "needs_review"
