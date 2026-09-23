from copy import deepcopy

import pytest

from PushShoppingList.services import product_selection_service
from PushShoppingList.services import recipe_quantity_service
from PushShoppingList.services import shopping_list_service


def choice_recipe():
    return {
        "source_url": "https://example.test/corn-spoon-bread",
        "recipe_title": "Corn Spoon Bread",
        "servings": "8",
        "ingredients": [
            {"ingredient": "egg", "quantity": "2", "unit": "each"},
            {
                "recipe_ingredient_id": "requirement-butter",
                "ingredient": "butter",
                "quantity": "1/2",
                "unit": "cup",
                "preparation": "melted",
                "default_option_id": "butter-bundle",
                "substitutions": [
                    {
                        "alternative_id": "butter-bundle",
                        "option_type": "original",
                        "ingredient": "unsalted butter",
                        "quantity": "1/4",
                        "unit": "cup",
                    },
                    {
                        "alternative_id": "butter-bundle",
                        "option_type": "original",
                        "ingredient": "egg",
                        "preparation": "beaten",
                    },
                    {
                        "alternative_id": "butter-only",
                        "option_type": "recipe_choice",
                        "ingredient": "butter",
                        "quantity": "1/2",
                        "unit": "cup",
                    },
                ],
            },
            {
                "recipe_ingredient_id": "requirement-corn",
                "ingredient": "canned cream-style corn",
                "quantity": "14",
                "unit": "ounce",
                "default_option_id": "corn-bundle",
                "substitutions": [
                    {
                        "alternative_id": "corn-bundle",
                        "option_type": "original",
                        "ingredient": "corn",
                        "quantity": "3/4",
                        "unit": "cup",
                    },
                    {
                        "alternative_id": "corn-bundle",
                        "option_type": "original",
                        "ingredient": "cumin",
                    },
                    {
                        "alternative_id": "corn-bundle",
                        "option_type": "original",
                        "ingredient": "onion",
                        "quantity": "1/2",
                        "unit": "each",
                    },
                    {
                        "alternative_id": "corn-only",
                        "option_type": "recipe_choice",
                        "ingredient": "corn",
                        "quantity": "1",
                        "unit": "cup",
                    },
                ],
            },
        ],
    }


def test_choice_scaling_uses_component_amounts_without_source_or_invented_amounts(monkeypatch):
    recipe = choice_recipe()
    original = deepcopy(recipe)
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    monkeypatch.setattr(
        recipe_quantity_service,
        "calculate_scaled_values_with_openai",
        lambda *_args: pytest.fail("Choice quantities must use their explicit component amounts."),
    )

    result = recipe_quantity_service.calculate_scaled_recipe_values(recipe, 2)

    assert result["servings"] == "16"
    assert set(result["ingredients"]) == {"unsalted butter", "corn", "cumin", "onion"}
    assert result["ingredients"]["unsalted butter"]["quantity"] == "1/2"
    assert result["ingredients"]["corn"]["quantity"] == "1 1/2"
    assert result["ingredients"]["onion"]["quantity"] == "1"
    assert result["ingredients"]["cumin"] == {"quantity": None, "unit": None, "display": ""}
    # The name-keyed compatibility cache cannot safely represent two egg rows.
    # Quantity context below computes those amounts per row instead.
    assert "egg" not in result["ingredients"]
    assert recipe == original


def test_quantity_update_uses_the_saved_shopping_selection(monkeypatch):
    recipe = choice_recipe()
    saved = {}
    monkeypatch.setattr(recipe_quantity_service, "load_saved_recipe_output", lambda _url: recipe)
    monkeypatch.setattr(recipe_quantity_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_quantity_service, "save_recipe_ingredients", saved.update)
    monkeypatch.setattr(recipe_quantity_service, "load_recipe_option_selections", lambda _url: {
        "requirement-butter": "butter-only",
        "requirement-corn": "corn-only",
    })

    result = recipe_quantity_service.update_recipe_quantity(recipe["source_url"], 2)

    assert set(result["ingredients"]) == {"egg", "butter", "corn"}
    assert result["ingredients"]["egg"]["quantity"] == "4"
    assert result["ingredients"]["butter"]["quantity"] == "1"
    assert result["ingredients"]["corn"]["quantity"] == "2"
    assert saved[recipe["source_url"]]["scaled_ingredients"] == result["ingredients"]


@pytest.mark.parametrize("bundle_egg_quantity, expected_egg_quantity, expected_egg_sources", [
    (None, "4", 1),
    ("1", "6", 2),
])
def test_shopping_quantity_context_scales_each_selected_row_once(
    monkeypatch, bundle_egg_quantity, expected_egg_quantity, expected_egg_sources
):
    recipe = choice_recipe()
    if bundle_egg_quantity:
        recipe["ingredients"][1]["substitutions"][1].update({
            "quantity": bundle_egg_quantity,
            "unit": "each",
        })
    recipe_url = recipe["source_url"]
    monkeypatch.setattr(product_selection_service, "load_item_state", lambda: {})
    monkeypatch.setattr(product_selection_service, "recipe_url_rows", lambda: [{
        "url": recipe_url,
        "quantity": 2,
    }])
    monkeypatch.setattr(product_selection_service, "load_saved_recipe_output", lambda _url: recipe)
    monkeypatch.setattr(product_selection_service, "load_recipe_option_selections", lambda _url: {})
    monkeypatch.setattr(product_selection_service, "load_recipe_ingredients", lambda: {
        recipe_url: {
            "quantity": 2,
            "scaling_model": recipe_quantity_service.RECIPE_SCALING_MODEL,
            "scaled_ingredients": {
                name: {"quantity": "99", "unit": "cup", "display": "99 cups"}
                for name in ["egg", "unsalted butter", "corn", "cumin", "onion"]
            },
        },
    })

    context = product_selection_service.load_item_quantity_context([
        "egg", "unsalted butter", "butter", "corn", "cumin", "onion", "canned cream-style corn"
    ])

    assert set(context) == {"eggs", "unsalted butter", "corn", "onion"}
    assert context["eggs"]["display"].startswith(expected_egg_quantity)
    assert len(context["eggs"]["sources"]) == expected_egg_sources
    assert context["unsalted butter"]["display"] == "1/2 cups"
    assert context["corn"]["display"] == "1 1/2 cups"
    assert context["onion"]["display"].startswith("1")


def test_shopping_quantity_context_uses_persisted_option_instead_of_default(monkeypatch):
    recipe = choice_recipe()
    monkeypatch.setattr(product_selection_service, "load_item_state", lambda: {})
    monkeypatch.setattr(product_selection_service, "recipe_url_rows", lambda: [{
        "url": recipe["source_url"], "quantity": 2,
    }])
    monkeypatch.setattr(product_selection_service, "load_saved_recipe_output", lambda _url: recipe)
    monkeypatch.setattr(product_selection_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(product_selection_service, "load_recipe_option_selections", lambda _url: {
        "requirement-butter": "butter-only", "requirement-corn": "corn-only",
    })

    context = product_selection_service.load_item_quantity_context([
        "egg", "butter", "unsalted butter", "corn", "cumin", "onion"
    ])

    assert set(context) == {"eggs", "butter", "corn"}
    assert context["butter"]["display"] == "1 cup"
    assert context["corn"]["display"] == "2 cups"


def test_shopping_finalization_reloads_only_selected_bundles(monkeypatch, tmp_path):
    recipe = choice_recipe()
    monkeypatch.setattr(shopping_list_service, "SHOPPING_LIST_FILE", tmp_path / "shopping.txt")
    monkeypatch.setattr(
        shopping_list_service, "SHOPPING_LIST_SELECTIONS_FILE", tmp_path / "selections.json"
    )

    result = shopping_list_service.finalize_recipe_items(recipe["source_url"], recipe)

    assert result["added"] == ["egg", "unsalted butter", "corn", "cumin", "onion"]
    selections = shopping_list_service.load_recipe_option_selections(recipe["source_url"])
    assert selections["requirement-butter"] == "butter-bundle"
    assert selections["requirement-corn"] == "corn-bundle"
    assert shopping_list_service.load_items() == result["added"]


def test_saving_shopping_selection_replaces_equivalent_url_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(
        shopping_list_service, "SHOPPING_LIST_SELECTIONS_FILE", tmp_path / "selections.json"
    )
    recipe_url = "https://example.test/corn-spoon-bread"
    shopping_list_service.save_recipe_selections({"recipes": {
        recipe_url + "/": {"requirement-corn": "old-option"},
        "https://example.test/another-recipe": {"another-requirement": "another-option"},
    }})

    shopping_list_service.save_recipe_option_selections(
        recipe_url, {"requirement-corn": "corn-only"}
    )

    assert shopping_list_service.load_recipe_option_selections(recipe_url + "/") == {
        "requirement-corn": "corn-only"
    }
    assert set(shopping_list_service.load_recipe_selections()["recipes"]) == {
        recipe_url, "https://example.test/another-recipe"
    }
