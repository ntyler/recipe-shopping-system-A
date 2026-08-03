import json

from PushShoppingList.scripts.migrate_recipe_fraction_text import (
    migrate_recipe_fraction_text,
    normalize_json_fraction_values,
)
from PushShoppingList.services.ingredient_unit_service import (
    normalize_fraction_text,
    normalize_ingredient_unit_fields,
    normalize_recipe_fraction_fields,
)
from PushShoppingList.services.recipe_extract_service import (
    clean_recipe_text,
    normalize_extracted_ingredient_fields,
)


def test_fraction_text_normalizer_uses_plain_and_mixed_slash_fractions():
    assert normalize_fraction_text("½ cup") == "1/2 cup"
    assert normalize_fraction_text("1½ cups") == "1 1/2 cups"
    assert normalize_fraction_text("2 ¾ cups") == "2 3/4 cups"
    assert normalize_fraction_text("⅓ to ⅔ cup") == "1/3 to 2/3 cup"
    assert normalize_fraction_text("⅐ ⅑ ⅒ ⅕ ⅖ ⅗ ⅘ ⅙ ⅚") == (
        "1/7 1/9 1/10 1/5 2/5 3/5 4/5 1/6 5/6"
    )


def test_import_normalization_cleans_ingredient_and_instruction_fraction_text():
    recipe = {
        "ingredients": [{
            "original_text": "1½ cups flour",
            "quantity": "1½",
            "recipe_qty": "1½",
            "ingredient": "flour",
            "substitutions": [{"ingredient": "almond flour", "quantity": "¾"}],
        }],
        "instructions": [{"instruction": "Add ½ cup water.", "text": "Add ½ cup water."}],
    }

    normalize_extracted_ingredient_fields(recipe)

    ingredient = recipe["ingredients"][0]
    assert ingredient["original_text"] == "1 1/2 cups flour"
    assert ingredient["quantity"] == "1 1/2"
    assert ingredient["recipe_qty"] == "1 1/2"
    assert ingredient["base_quantity"] == "1 1/2"
    assert ingredient["substitutions"][0]["quantity"] == "3/4"
    assert recipe["instructions"][0]["instruction"] == "Add 1/2 cup water."


def test_editor_unit_normalization_cleans_legacy_fraction_fields():
    ingredient = {
        "ingredient": "sugar",
        "original_text": "¾ cup sugar",
        "quantity": "¾",
        "quantity_text": "¾",
        "unit": "cup",
    }

    normalize_ingredient_unit_fields(ingredient)

    assert ingredient["original_text"] == "3/4 cup sugar"
    assert ingredient["quantity"] == "3/4"
    assert ingredient["quantity_text"] == "3/4"
    assert ingredient["base_quantity"] == "3/4"


def test_recipe_fraction_normalizer_cleans_scaled_and_instruction_fields():
    recipe = {
        "servings": "4½",
        "scaled_ingredients": {"sugar": {"quantity": "½", "display": "½ cup"}},
        "ingredient_details": [{"ingredient": "sugar", "quantity": "½"}],
        "instructions": ["Stir in ⅔ cup water."],
    }

    normalize_recipe_fraction_fields(recipe)

    assert recipe["servings"] == "4 1/2"
    assert recipe["scaled_ingredients"]["sugar"]["quantity"] == "1/2"
    assert recipe["scaled_ingredients"]["sugar"]["display"] == "1/2 cup"
    assert recipe["ingredient_details"][0]["quantity"] == "1/2"
    assert recipe["instructions"] == ["Stir in 2/3 cup water."]


def test_clean_recipe_text_converts_fraction_mojibake_to_slash_fraction():
    assert clean_recipe_text("Â½ cup sugar") == "1/2 cup sugar"


def test_json_fraction_migration_skips_urls_and_creates_backups(tmp_path):
    recipe_path = tmp_path / "users" / "abc" / "recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(
        json.dumps({
            "source_url": "https://example.test/½-cup",
            "ingredients": [{"quantity": "½", "original_text": "½ cup milk"}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    dry_run = migrate_recipe_fraction_text(tmp_path)
    assert dry_run["files_changed"] == 1
    assert dry_run["strings_changed"] == 2
    assert "½" in recipe_path.read_text(encoding="utf-8")

    applied = migrate_recipe_fraction_text(tmp_path, apply_changes=True)
    migrated = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert applied["ok"] is True
    assert migrated["source_url"] == "https://example.test/½-cup"
    assert migrated["ingredients"][0]["quantity"] == "1/2"
    assert migrated["ingredients"][0]["original_text"] == "1/2 cup milk"
    backup_root = applied["backup_root"]
    assert backup_root
    assert (tmp_path / ".fraction-normalization-backups").is_dir()


def test_json_fraction_value_normalizer_preserves_non_string_values():
    data, changed = normalize_json_fraction_values({"quantity": 0.5, "text": "½"})
    assert data == {"quantity": 0.5, "text": "1/2"}
    assert changed == 1
