from PushShoppingList.routes import main_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import product_selection_service
from PushShoppingList.services import recipe_quantity_service


def legacy_materialized_recipe():
    return {
        "source_url": "https://example.test/soup",
        "servings": "8",
        "scaling": {
            "selected_multiplier": 2,
            "base_multiplier": 1,
            "base_servings": "4",
        },
        "ingredients": [{
            "ingredient": "broth",
            "quantity": "2",
            "unit": "cups",
            "base_quantity": "1",
            "base_unit": "cup",
            "store_section": "CANNED",
        }],
    }


def test_effective_recipe_quantity_uses_exactly_one_legacy_multiplier():
    recipe = legacy_materialized_recipe()

    assert recipe_quantity_service.effective_recipe_quantity(1, recipe) == 2
    assert recipe_quantity_service.effective_recipe_quantity(2, recipe) == 2
    assert recipe_quantity_service.effective_recipe_quantity(3, recipe) == 3


def test_legacy_materialized_recipe_scales_from_base_once():
    recipe = legacy_materialized_recipe()

    scaled = recipe_quantity_service.calculate_scaled_values_locally(recipe, 2)

    assert scaled["servings"] == "8"
    assert scaled["ingredients"]["broth"] == {
        "quantity": "2",
        "unit": "cup",
        "display": "2 cups",
    }


def test_missing_legacy_base_values_are_recovered_from_the_materialized_scale():
    recipe = {
        "servings": "8",
        "scaling": {"selected_multiplier": 2},
        "ingredients": [{
            "ingredient": "broth",
            "quantity": "2",
            "unit": "cups",
        }],
    }

    assert recipe_quantity_service.recipe_base_servings(recipe) == "4"
    assert recipe_quantity_service.recipe_base_ingredient_quantity(
        recipe["ingredients"][0],
        recipe,
    ) == "1"
    scaled = recipe_quantity_service.calculate_scaled_values_locally(recipe, 2)
    assert scaled["ingredients"]["broth"]["quantity"] == "2"


def test_recipe_sections_ignore_materialized_amounts_and_stale_scaled_metadata():
    recipe = legacy_materialized_recipe()
    stale_scaled = {
        "broth": {"quantity": "4", "unit": "cups", "display": "4 cups"},
    }

    sections = main_routes.build_recipe_sections(
        recipe,
        recipe_quantity=2,
        scaled_ingredients={},
        include_images=False,
    )
    row = sections["CANNED"][0]

    assert row["base_quantity"] == "1"
    assert row["scaled_quantity"] == "2"
    assert row["quantity_display"] == "2 cups"
    assert recipe_quantity_service.scaled_recipe_metadata_matches(
        {"quantity": 2, "scaled_ingredients": stale_scaled},
        2,
    ) is False


def test_new_scaled_metadata_is_versioned_and_multiplier_specific():
    assert recipe_quantity_service.scaled_recipe_metadata_matches(
        {
            "quantity": 2,
            "scaling_model": recipe_quantity_service.RECIPE_SCALING_MODEL,
        },
        2,
    ) is True
    assert recipe_quantity_service.scaled_recipe_metadata_matches(
        {
            "quantity": 3,
            "scaling_model": recipe_quantity_service.RECIPE_SCALING_MODEL,
        },
        2,
    ) is False


def test_update_recipe_quantity_integration_persists_one_base_derived_projection(monkeypatch):
    recipe = legacy_materialized_recipe()
    saved_records = []
    monkeypatch.setattr(
        recipe_quantity_service,
        "load_saved_recipe_output",
        lambda _url: recipe,
    )
    monkeypatch.setattr(recipe_quantity_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(
        recipe_quantity_service,
        "save_recipe_ingredients",
        lambda records: saved_records.append(records),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = recipe_quantity_service.update_recipe_quantity(recipe["source_url"], 2)

    assert result["servings"] == "8"
    assert result["ingredients"]["broth"]["quantity"] == "2"
    record = next(iter(saved_records[0].values()))
    assert record["quantity"] == 2
    assert record["scaling_model"] == recipe_quantity_service.RECIPE_SCALING_MODEL
    assert record["scaled_ingredients"]["broth"]["quantity"] == "2"


def test_product_quantity_context_uses_base_amount_once(monkeypatch):
    recipe = legacy_materialized_recipe()
    recipe_url = recipe["source_url"]
    monkeypatch.setattr(product_selection_service, "load_item_state", lambda: {})
    monkeypatch.setattr(product_selection_service, "recipe_url_rows", lambda: [{
        "url": recipe_url,
        "name": "Soup",
        "quantity": 2,
    }])
    monkeypatch.setattr(
        product_selection_service,
        "load_saved_recipe_output",
        lambda _url: recipe,
    )
    monkeypatch.setattr(product_selection_service, "load_recipe_ingredients", lambda: {
        recipe_url: {
            "quantity": 2,
            "scaled_ingredients": {
                "broth": {"quantity": "4", "unit": "cups", "display": "4 cups"},
            },
        },
    })

    context = product_selection_service.load_item_quantity_context(["broth"])

    assert context["broth"]["display"] == "2 cups"
    assert context["broth"]["sources"][0]["recipe_quantity"] == 2


def test_scale_payload_migration_is_canonical_and_idempotent():
    payload = {
        "quantity": 1,
        "servings": "5",
        "scaling": {
            "selected_multiplier": 1.25,
            "base_multiplier": 1,
            "base_servings": "4",
        },
        "ingredients": [{
            "ingredient": "broth",
            "quantity": "5/8",
            "unit": "cup",
            "base_quantity": "1/2",
            "base_unit": "cup",
            "substitutions": [{
                "ingredient": "stock",
                "quantity": "1 1/4",
                "unit": "cups",
                "base_quantity": "1",
                "base_unit": "cup",
            }],
        }],
    }

    migrated = recipe_edit_service.canonicalize_recipe_scale_payload(payload)
    migrated_again = recipe_edit_service.canonicalize_recipe_scale_payload(migrated)

    assert migrated["quantity"] == 1.25
    assert migrated["servings"] == "4"
    assert migrated["scaling"]["selected_multiplier"] == 1
    assert migrated["scaling"]["base_servings"] == "4"
    assert migrated["ingredients"][0]["quantity"] == "1/2"
    assert migrated["ingredients"][0]["substitutions"][0]["quantity"] == "1"
    assert migrated_again == migrated


def test_manual_servings_edit_at_scale_one_replaces_stale_base_servings():
    migrated = recipe_edit_service.canonicalize_recipe_scale_payload({
        "quantity": 1,
        "servings": "6",
        "scaling": {
            "selected_multiplier": 1,
            "base_servings": "4",
        },
        "ingredients": [],
    })

    assert migrated["servings"] == "6"
    assert migrated["scaling"]["base_servings"] == "6"
