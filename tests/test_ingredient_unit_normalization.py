import json
import sqlite3
from pathlib import Path

import pytest

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services.ingredient_unit_service import CANONICAL_UNITS
from PushShoppingList.services.ingredient_unit_service import canonical_unit
from PushShoppingList.services.ingredient_unit_service import display_unit
from PushShoppingList.services.ingredient_unit_service import normalize_ingredient_unit_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import parse_structured_ingredient_line


@pytest.mark.parametrize(
    ("aliases", "canonical"),
    [
        (("tsp", "tsps", "teaspoons"), "teaspoon"),
        (("tbsp", "tbs", "tbsps", "tablespoons"), "tablespoon"),
        (("c", "cups"), "cup"),
        (("fl oz", "fluid oz", "fluid ounces"), "fluid ounce"),
        (("oz", "ounces"), "ounce"),
        (("lb", "lbs", "pounds"), "pound"),
        (("g", "grams"), "gram"),
        (("kg", "kilograms"), "kilogram"),
        (("ml", "milliliters"), "milliliter"),
        (("l", "litre", "litres"), "liter"),
        (("pt", "pints"), "pint"),
        (("qt", "quarts"), "quart"),
        (("gal", "gallons"), "gallon"),
        (("pc", "pcs", "pieces"), "piece"),
        (("pkg", "packages"), "package"),
        (("cans",), "can"),
        (("jars",), "jar"),
        (("bottles",), "bottle"),
        (("cloves",), "clove"),
        (("slices",), "slice"),
        (("sprigs",), "sprig"),
        (("bunches",), "bunch"),
        (("heads",), "head"),
        (("leaves",), "leaf"),
        (("pinches",), "pinch"),
        (("dashes",), "dash"),
        (("drops",), "drop"),
        (("taste",), "to taste"),
        (("needed",), "as needed"),
    ],
)
def test_required_aliases_resolve_to_canonical_singular_units(aliases, canonical):
    for alias in aliases:
        assert canonical_unit(alias)["name"] == canonical


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("medium onion", {"quantity": "1", "unit": "piece", "ingredient": "onion", "size": "medium"}),
        ("1 large can tomatoes", {"quantity": "1", "unit": "can", "ingredient": "tomatoes", "size": "large"}),
        ("2 small yellow peppers", {"quantity": "2", "unit": "piece", "ingredient": "yellow pepper", "size": "small"}),
        ("salt to taste", {"quantity": "", "unit": "to taste", "ingredient": "salt", "preparation": ""}),
        ("1 cup chopped onion", {"quantity": "1", "unit": "cup", "ingredient": "onion", "preparation": "chopped"}),
        ("1 medium pepper", {"quantity": "1", "unit": "piece", "ingredient": "pepper", "size": "medium"}),
    ],
)
def test_field_placement_examples_are_deterministic(source, expected):
    row = parse_structured_ingredient_line(source)
    row["original_text"] = source
    normalize_ingredient_unit_fields(row)
    for key, value in expected.items():
        assert row.get(key, "") == value


def test_forbidden_and_unknown_unit_values_never_become_canonical_units(caplog):
    size = normalize_ingredient_unit_fields({"quantity": "1", "unit": "large", "ingredient": "onion"})
    assert size["unit"] == "piece"
    assert size["size"] == "large"

    prep = normalize_ingredient_unit_fields({"quantity": "1", "unit": "diced", "ingredient": "onion"})
    assert prep["unit"] == ""
    assert prep["preparation"] == "diced"

    ingredient = normalize_ingredient_unit_fields({"quantity": "1", "unit": "onion", "ingredient": ""})
    assert ingredient["ingredient"] == "onion"
    assert ingredient["unit"] == "piece"

    unknown = normalize_ingredient_unit_fields({"quantity": "1", "unit": "heaping", "ingredient": "sugar"})
    assert unknown["unit"] == ""
    assert unknown["unit_raw"] == "heaping"
    assert unknown["unit_review_required"] is True
    assert unknown["unit_review_value"] == "heaping"
    assert "requires review" in caplog.text

    cleared = normalize_ingredient_unit_fields({
        "quantity": "1",
        "unit": "",
        "unit_raw": "tbsp",
        "unit_review_required": "false",
        "ingredient": "sugar",
    })
    assert cleared["unit"] == ""


def test_explicit_custom_unit_is_preserved_without_weakening_unknown_unit_review():
    custom = normalize_ingredient_unit_fields({
        "ingredient": "protein powder",
        "quantity": "1",
        "unit": "scoop",
        "unit_custom": True,
    })
    assert custom["unit"] == "scoop"
    assert custom["unit_id"] == ""
    assert custom["unit_custom"] is True
    assert custom["unit_review_required"] is False
    assert custom["unit_review_value"] == ""

    unknown = normalize_ingredient_unit_fields({
        "ingredient": "protein powder",
        "quantity": "1",
        "unit": "scoop",
    }, log_unrecognized=False)
    assert unknown["unit"] == ""
    assert unknown["unit_custom"] is False
    assert unknown["unit_review_required"] is True
    assert unknown["unit_review_value"] == "scoop"


def test_shared_post_extraction_normalizer_covers_aliases_and_review_flags():
    recipe = {
        "ingredients": [
            {"original_text": "2 tbsp sugar", "ingredient": "sugar", "quantity": "2", "unit": "tbsp"},
            {"original_text": "1 heaping scoop protein powder", "ingredient": "protein powder", "quantity": "1", "unit": "scoop"},
        ]
    }
    normalize_extracted_ingredient_fields(recipe, source_text="2 tbsp sugar\n1 heaping scoop protein powder")
    assert recipe["ingredients"][0]["unit"] == "tablespoon"
    assert recipe["ingredients"][0]["unit_id"] == "volume_tablespoon"
    assert recipe["ingredients"][1]["unit"] == ""
    assert recipe["ingredients"][1]["unit_review_required"] is True


def test_units_are_pluralized_only_for_display():
    assert display_unit("cup", "1") == "cup"
    assert display_unit("cup", "2") == "cups"
    assert display_unit("leaf", "2") == "leaves"
    assert display_unit("dash", "2") == "dashes"
    assert display_unit("to taste", "") == "to taste"


def _create_legacy_master_schema(connection):
    connection.executescript(
        """
        CREATE TABLE ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            store_section TEXT NOT NULL DEFAULT 'MISC',
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            equipment_section TEXT NOT NULL DEFAULT 'MISC',
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        CREATE TABLE recipe_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            ingredient_id INTEGER NOT NULL,
            quantity TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            buy_as TEXT NOT NULL DEFAULT '',
            store_section TEXT NOT NULL DEFAULT '',
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE recipe_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL,
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO ingredients (
            id, user_id, name, normalized_name, created_at, updated_at
        ) VALUES (1, 'user-a', 'Sugar', 'sugar', 'now', 'now');
        INSERT INTO recipe_ingredients (
            user_id, recipe_id, ingredient_id, quantity, unit, original_recipe_text
        ) VALUES ('user-a', 'recipe-a', 1, '2', 'tbsp', '2 tbsp sugar');
        """
    )


def test_master_schema_seeds_registry_and_migrates_legacy_rows_with_report():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _create_legacy_master_schema(connection)

    master_data.ensure_recipe_master_schema(connection)

    assert connection.execute("SELECT COUNT(*) FROM canonical_units").fetchone()[0] == len(CANONICAL_UNITS)
    recipe_ingredient_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(recipe_ingredients)").fetchall()
    }
    assert "unit_custom" in recipe_ingredient_columns
    assert connection.execute("SELECT COUNT(*) FROM unit_aliases WHERE alias = 'tbsp'").fetchone()[0] == 1
    row = connection.execute(
        "SELECT unit, unit_id, unit_raw, unit_review_required FROM recipe_ingredients"
    ).fetchone()
    assert dict(row) == {
        "unit": "tablespoon",
        "unit_id": "volume_tablespoon",
        "unit_raw": "tbsp",
        "unit_review_required": 0,
    }
    report = json.loads(connection.execute(
        "SELECT report_json FROM unit_normalization_reports WHERE migration_name = ?",
        (master_data.UNIT_NORMALIZATION_MIGRATION_NAME,),
    ).fetchone()[0])
    assert report["rows_scanned"] == 1
    assert report["aliases_replaced"] == 1


def test_saved_json_backfill_preserves_quantities_and_records_review(tmp_path):
    data_root = tmp_path / "data"
    output_root = data_root / "output"
    output_root.mkdir(parents=True)
    payload = {
        "recipe": {
            "ingredients": [
                {"quantity": "2", "unit": "oz", "ingredient": "cheese"},
                {"quantity": "1", "unit": "scoop", "ingredient": "protein powder"},
            ]
        }
    }
    path = data_root / "recipe_ingredients.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    summary = master_data.normalize_saved_recipe_units(data_root)
    updated = json.loads(path.read_text(encoding="utf-8"))["recipe"]["ingredients"]
    assert summary["files_updated"] == 1
    assert updated[0]["quantity"] == "2"
    assert updated[0]["unit"] == "ounce"
    assert updated[1]["unit"] == ""
    assert updated[1]["unit_raw"] == "scoop"
    assert updated[1]["unit_review_required"] is True


def test_editor_uses_registry_backed_combobox_and_separate_metadata_fields():
    app_js = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    app_css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    template = Path("PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(encoding="utf-8")

    assert 'id="ingredientUnitConfig"' in template
    assert 'role", "combobox"' in app_js
    assert 'aria-autocomplete", "list"' in app_js
    assert 'aria-haspopup", "listbox"' in app_js
    assert 'list="recipeIngredientUnitOptions"' in app_js
    assert "function ensureRecipeIngredientUnitMenu()" in app_js
    assert "function openRecipeIngredientUnitPicker(input, options = {})" in app_js
    assert 'menu.id = "recipeIngredientUnitMenu";' in app_js
    assert 'menu.setAttribute("role", "listbox");' in app_js
    assert 'role="option"' in app_js
    assert "function chooseRecipeIngredientUnit(button)" in app_js
    assert "function handleRecipeIngredientUnitKeydown(event, input)" in app_js
    assert 'RECIPE_INGREDIENT_CUSTOM_UNITS_KEY = "recipeIngredientCustomUnits"' in app_js
    assert "function addRecipeIngredientCustomUnit(button)" in app_js
    assert "function storeRecipeIngredientCustomUnitNames(values)" in app_js
    assert "function replaceRecipeIngredientCustomUnitName(previousValue, nextValue)" in app_js
    assert "function editRecipeIngredientCustomUnit(button)" in app_js
    assert 'data-unit-action="add-custom"' in app_js
    assert 'data-unit-action="edit-custom"' in app_js
    assert 'aria-label="Edit custom unit ${escapeAttribute(value)}"' in app_js
    assert "Open ingredient rows using it will be cleared." in app_js
    assert 'document.querySelectorAll(\'.recipe-edit-ingredient-row [data-field="unit"]\')' in app_js
    assert "Add custom unit…" in app_js
    assert 'input.setAttribute("aria-controls", "recipeIngredientUnitMenu")' in app_js
    assert 'input.setAttribute("aria-expanded", "false")' in app_js
    assert 'input.removeAttribute("list")' in app_js
    assert 'input.addEventListener("click", () => openRecipeIngredientUnitPicker(input, { showAll: true }))' in app_js
    assert 'input.addEventListener("keydown", event => handleRecipeIngredientUnitKeydown(event, input))' in app_js
    assert 'typeof input.showPicker !== "function"' not in app_js
    assert ".recipe-edit-row-menu.recipe-edit-unit-menu" in app_css
    assert ".recipe-edit-unit-option.is-selected" in app_css
    assert ".recipe-edit-unit-option.is-active" in app_css
    assert ".recipe-edit-unit-add-option" in app_css
    assert ".recipe-edit-unit-custom-row" in app_css
    assert ".recipe-edit-unit-edit-button" in app_css
    assert 'data-field="unit_id"' in app_js
    assert 'data-field="unit_raw"' in app_js
    assert 'data-field="unit_custom"' in app_js
    assert 'data-field="size"' in app_js
    assert 'data-field="preparation"' in app_js
    assert 'data-field="notes"' in app_js
