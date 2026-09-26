"""Meal shopping uses saved portions, choices and isolated contribution records."""

from copy import deepcopy
import json

import pytest

from PushShoppingList.routes import main_routes
from PushShoppingList.services import meal_plan_service as plans
from PushShoppingList.services import meal_plan_shopping_service as service
from PushShoppingList.services import shopping_list_service as shopping
from PushShoppingList.services import storage_service
from test_meal_prep_batches import scoped_client, sign_in


RECIPE = {"recipe_title": "Soup", "servings": "4", "ingredients": [
    {"ingredient": "flour", "quantity": "1", "unit": "cup"},
    {"ingredient": "milk", "quantity": "2", "unit": "cup"},
]}


@pytest.fixture
def isolated_shopping(tmp_path, monkeypatch):
    from PushShoppingList.services import product_selection_service as products
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    monkeypatch.setattr(plans, "MEAL_PLAN_FILE", tmp_path / "meal_plan.json")
    monkeypatch.setattr(service, "SHOPPING_PLAN_FILE", tmp_path / "meal_plan_shopping.json")
    monkeypatch.setattr(shopping, "SHOPPING_LIST_FILE", tmp_path / "shopping_list.txt")
    monkeypatch.setattr(service, "load_saved_recipe_output", lambda url: deepcopy(RECIPE))
    monkeypatch.setattr(service, "load_item_state", lambda: {})
    monkeypatch.setattr(service, "load_pantry_inventory", lambda: {"items": []})
    monkeypatch.setattr(products, "load_item_state", lambda: {})
    monkeypatch.setattr(products, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(products, "recipe_url_rows", lambda: [])
    return tmp_path


def seed_batch(servings=12, ingredient_data=None, recipe_url="recipe://soup"):
    return plans.add_meal_prep_batch({"recipe_url": recipe_url, "recipe_name": "Soup", "batch_servings": servings}, [
        {"date": "2026-09-28", "meal_type": "lunch", "planned_servings": 4},
        {"date": "2026-09-30", "meal_type": "dinner", "planned_servings": 4},
        {"date": "2026-10-05", "meal_type": "lunch", "planned_servings": 4},
    ], ingredient_data or {"ingredients": deepcopy(RECIPE["ingredients"])})


def add_review(review, **destination):
    return service.add_meal_plan_shopping({"selection": review["selection"], "review_token": review["review_token"], **destination})


def quantities(items):
    return {item["name"]: item["quantity"] for item in items}


def test_week_and_overlapping_selections_shop_full_batch_once(isolated_shopping):
    batch, meals = seed_batch()
    before = plans.MEAL_PLAN_FILE.read_bytes()
    review = service.review_meal_plan_shopping({"week_start": "2026-09-30"})
    assert review["selection"] == {"week_start": "2026-09-28"}
    assert len(review["sources"]) == 1
    assert review["sources"][0]["servings"] == 12
    assert quantities(review["items"]) == {"flour": "3 cup", "milk": "6 cup"}
    assert "other weeks" in review["warnings"][0]
    duplicate_selection = service.review_meal_plan_shopping({"batch_ids": [batch["id"], batch["id"]], "meal_ids": [meal["id"] for meal in meals]})
    assert quantities(duplicate_selection["items"]) == quantities(review["items"])
    assert plans.MEAL_PLAN_FILE.read_bytes() == before
    assert not service.SHOPPING_PLAN_FILE.exists()
    assert not shopping.SHOPPING_LIST_FILE.exists()


def test_split_family_lunch_shops_saved_shares_and_survives_reload_and_edit(isolated_shopping):
    members = [plans.add_meal_plan_member(name) for name in ('Nate', 'Gary')]
    entries = []
    for url, amounts in [('recipe://bread', (0.25, 0.5)), ('recipe://soup', (0.75, 0.5))]:
        entries.append({
            'batch': {'recipe_url': url, 'recipe_name': url, 'portion_mode': 'family'},
            'allocations': [{'date': '2026-09-25', 'meal_type': 'lunch',
                             'member_portions': [{'member_id': member['id'], 'servings': amount}
                                                 for member, amount in zip(members, amounts)]}],
            'ingredient_data': plans.meal_ingredient_snapshot(RECIPE, RECIPE['ingredients']),
        })
    batches, meals = plans.add_meal_prep_batches(entries)
    assert [batch['batch_servings'] for batch in batches] == [0.75, 1.25]
    assert sum(meal['planned_servings'] for meal in plans.load_meal_plan()['meals']) == 2
    plans.update_meal(meals[0]['id'], {'prep_notes': 'Pack together'})
    review = service.review_meal_plan_shopping({'batch_ids': [batch['id'] for batch in batches]})
    assert sorted(source['servings'] for source in review['sources']) == [0.75, 1.25]
    assert quantities(review['items']) == {'flour': '1/2 cup', 'milk': '1 cup'}


def test_batch_yield_includes_unallocated_portions_and_distinct_meals_sum(isolated_shopping):
    batch, meals = seed_batch(16)
    single = plans.add_meal({"date": "2026-09-29", "meal_type": "breakfast", "recipe_url": "recipe://other", "recipe_name": "Other", "planned_servings": 2, "ingredients": [RECIPE["ingredients"][0]]})
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]], "meal_ids": [single["id"]]})
    assert quantities(review["items"]) == {"flour": "4 1/2 cup", "milk": "8 cup"}
    assert len(review["sources"]) == 2


def test_saved_snapshot_does_not_inherit_new_live_scale_and_sync_keeps_basis(isolated_shopping, monkeypatch):
    batch, _ = seed_batch()
    selection = {"batch_ids": [batch["id"]]}
    original = quantities(service.review_meal_plan_shopping(selection)["items"])
    doubled = {**RECIPE, "servings": "8", "scaling": {"selected_multiplier": 2, "base_servings": "4"},
               "ingredients": [{**row, "quantity": str(int(row["quantity"]) * 2)} for row in RECIPE["ingredients"]]}
    monkeypatch.setattr(service, "load_saved_recipe_output", lambda url: deepcopy(doubled))
    assert quantities(service.review_meal_plan_shopping(selection)["items"]) == original
    plans.sync_meal_recipe_ingredients("recipe://soup", doubled)
    assert all(meal["ingredient_base_servings"] == 4 for meal in plans.load_meal_plan()["meals"])
    assert quantities(service.review_meal_plan_shopping(selection)["items"]) == original
    # The saved basis also protects snapshots if a different yield is loaded
    # before the recipe-save synchronizer refreshes the planned ingredients.
    monkeypatch.setattr(service, "load_saved_recipe_output", lambda url: {**RECIPE, "servings": "16"})
    assert quantities(service.review_meal_plan_shopping(selection)["items"]) == original
    plans.sync_meal_recipe_ingredients("recipe://soup", {**RECIPE, "servings": "8"})
    assert all(meal["ingredient_base_servings"] == 8 for meal in plans.load_meal_plan()["meals"])
    assert quantities(service.review_meal_plan_shopping(selection)["items"]) == {"flour": "1 1/2 cup", "milk": "3 cup"}


def test_saved_bundle_components_buy_as_ranges_and_unknown_amounts(isolated_shopping):
    data = {"ingredient_option_selections": {"bundle": "alternative"}, "ingredients": [
        {"ingredient": "diced onion", "buy_as": "onion", "quantity": "1/2", "unit": "cup"},
        {"ingredient": "onion", "quantity": "1/4", "unit": "cup"},
        {"ingredient": "cumin"},
        {"ingredient": "salt", "quantity": "1-2", "unit": "teaspoon"},
    ]}
    batch, _ = seed_batch(ingredient_data=data)
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    amounts = quantities(review["items"])
    assert amounts["onion"] == "2 1/4 cup"
    assert amounts["salt"] == "3 to 6 teaspoon"
    assert amounts["cumin"] == "Amount not specified"
    assert "flour" not in amounts
    add_review(review, list_id="current")
    assert service.current_shopping_quantity_sources(shopping.load_items())["cumin"][0]["quantity"] == "Amount not specified"


def test_unresolved_source_is_reviewable_but_blocks_add_without_partial_write(isolated_shopping):
    batch, _ = seed_batch(ingredient_data={"ingredient_selection_needed": True, "unresolved_ingredient_requirement_ids": ["missing"]})
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    assert review["can_add"] is False and review["blockers"]
    assert review["sources"][0]["record_id"] == batch["id"]
    assert review["items"] == []
    with pytest.raises(ValueError, match="Resolve or deselect"):
        add_review(review, new_list_name="Blocked")
    assert not service.SHOPPING_PLAN_FILE.exists()


def test_missing_yield_and_ambiguous_spare_bundles_block_only_their_source(isolated_shopping, monkeypatch):
    batch, meals = seed_batch(16)
    plans.update_meal_ingredient_option_selections(meals[0]["id"], {}, ingredients=[{"ingredient": "almond milk", "quantity": "1", "unit": "cup"}])
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    assert "unallocated" in review["blockers"][0]
    monkeypatch.setattr(service, "load_saved_recipe_output", lambda url: {**RECIPE, "servings": ""})
    assert "yield" in service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})["blockers"][0]


def test_pantry_suggestions_are_not_automatically_subtracted_or_mutated(isolated_shopping, monkeypatch):
    batch, _ = seed_batch()
    pantry = {"items": [
        {"id": "flour", "ingredient_name": "flour", "quantity": 1, "unit": "bag", "status": "available", "expiration_date": "2000-01-01"},
        {"id": "used", "ingredient_name": "milk", "quantity": 3, "unit": "cup", "status": "used"},
        {"id": "empty", "ingredient_name": "milk", "quantity": 0, "unit": "cup"},
        {"id": "infinite", "ingredient_name": "milk", "quantity": float("inf"), "unit": "cup"},
        {"id": "bad", "ingredient_name": "milk", "quantity": "oops", "unit": "cup"},
    ]}
    monkeypatch.setattr(service, "load_pantry_inventory", lambda: deepcopy(pantry))
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    flour = next(item for item in review["items"] if item["name"] == "flour")
    assert flour["quantity"] == "3 cup" and flour["included"] is True
    assert flour["pantry_matches"][0]["unit"] == "bag"
    assert flour["pantry_matches"][0]["condition"] == "Expired?"
    assert next(item for item in review["items"] if item["name"] == "milk")["pantry_matches"] == []
    result = add_review(review, new_list_name="Prep groceries", excluded_item_ids=[flour["id"]])
    assert quantities(result["list"]["items"]) == {"milk": "6 cup"}
    assert pantry["items"][0]["quantity"] == 1


def test_named_list_reopens_checks_idempotent_add_and_preserves_unrelated_sources(isolated_shopping):
    batch, _ = seed_batch()
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    result = add_review(review, new_list_name="This week")
    list_id = result["list"]["id"]
    item = result["list"]["items"][0]
    service.set_shopping_plan_item_checked(list_id, item["id"], True)
    again = add_review(review, list_id=list_id)
    assert quantities(again["list"]["items"]) == quantities(result["list"]["items"])
    assert again["list"]["items"][0]["checked"] is True
    other, _ = seed_batch(recipe_url="recipe://other")
    second = service.review_meal_plan_shopping({"batch_ids": [other["id"]]})
    updated = add_review(second, list_id=list_id)
    assert quantities(updated["list"]["items"]) == {"flour": "6 cup", "milk": "12 cup"}
    assert updated["list"]["items"][0]["checked"] is False
    assert service.shopping_plan_detail(list_id) == updated["list"]
    assert shopping.load_items() == []
    assert service.list_shopping_plans()[1]["item_count"] == 2


def test_current_list_merges_names_and_repeated_batches_without_touching_other_items(isolated_shopping):
    shopping.save_items(["coffee", "flour"])
    batch, _ = seed_batch()
    before = plans.MEAL_PLAN_FILE.read_bytes()
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    add_review(review, list_id="current")
    add_review(review, list_id="current")
    assert shopping.load_items() == ["coffee", "flour", "milk"]
    sources = service.current_shopping_quantity_sources(shopping.load_items())
    assert [row["quantity"] for row in sources["flour"]] == ["3 cup"]
    assert plans.MEAL_PLAN_FILE.read_bytes() == before
    shopping.save_items(["coffee", "milk"])
    shopping.add_items(["flour"])
    assert "flour" not in service.current_shopping_quantity_sources(shopping.load_items())
    shopping.save_items([])
    assert service.current_shopping_quantity_sources(["milk"]) == {}


def test_reexcluding_current_list_item_removes_only_planner_owned_lines(isolated_shopping):
    batch, _ = seed_batch()
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    flour = next(row for row in review["items"] if row["name"] == "flour")
    add_review(review, list_id="current")
    add_review(review, list_id="current", excluded_item_ids=[flour["id"]])
    assert shopping.load_items() == ["milk"]
    shopping.save_items(["milk", "flour", "coffee"])
    add_review(review, list_id="current")
    add_review(review, list_id="current", excluded_item_ids=[flour["id"]])
    assert shopping.load_items() == ["milk", "flour", "coffee"]


def test_reexcluded_owned_item_stays_when_an_unrelated_recipe_needs_it(isolated_shopping, monkeypatch):
    from PushShoppingList.services import product_selection_service as products
    batch, _ = seed_batch()
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    add_review(review, list_id="current")
    monkeypatch.setattr(products, "recipe_url_rows", lambda: [{"url": "recipe://cake", "name": "Cake", "quantity": 1}])
    monkeypatch.setattr(products, "load_saved_recipe_output", lambda url: {"ingredients": [{"ingredient": "flour", "quantity": "2", "unit": "cup"}]})
    monkeypatch.setattr(products, "load_recipe_option_selections", lambda url: {})
    flour = next(row for row in review["items"] if row["name"] == "flour")
    add_review(review, list_id="current", excluded_item_ids=[flour["id"]])
    assert "flour" in shopping.load_items()
    assert products.load_item_quantity_context(["flour"])["flour"]["display"] == "2 cups"


def test_removal_rolls_back_names_if_contribution_retirement_fails(isolated_shopping, monkeypatch):
    shopping.save_items(["flour", "milk"])
    original = shopping.SHOPPING_LIST_FILE.read_bytes()
    monkeypatch.setattr(service, "prune_current_shopping_contributions", lambda items: (_ for _ in ()).throw(OSError("ledger unavailable")))
    with pytest.raises(OSError):
        shopping.save_items(["milk"])
    assert shopping.SHOPPING_LIST_FILE.read_bytes() == original


def test_source_merge_excludes_same_recipe_baseline_but_preserves_other_recipe_and_manual(isolated_shopping):
    existing = {"flour": [
        {"url": "recipe://soup", "quantity": "1 cup", "purchase_group_key": "flour"},
        {"url": "recipe://cake", "quantity": "2 cup", "purchase_group_key": "flour"},
        {"manual": True, "quantity": "1/2 cup"},
    ]}
    planner = {"flour": [{"url": "recipe://soup", "quantity": "3 cup", "meal_plan_source_id": "batch:x"}]}
    merged = service.merge_plan_quantity_sources(existing, planner)
    assert [row["quantity"] for row in merged["flour"]] == ["2 cup", "1/2 cup", "3 cup"]
    assert len(existing["flour"]) == 3


def test_current_product_quantities_use_ledger_without_duplicate_recipe_scale(isolated_shopping, monkeypatch):
    from PushShoppingList.services import product_selection_service as products
    batch, _ = seed_batch()
    add_review(service.review_meal_plan_shopping({"batch_ids": [batch["id"]]}), list_id="current")
    monkeypatch.setattr(products, "load_item_state", lambda: {})
    monkeypatch.setattr(products, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(products, "recipe_url_rows", lambda: [{"url": "recipe://soup", "name": "Soup", "quantity": 1}, {"url": "recipe://cake", "name": "Cake", "quantity": 1}])
    monkeypatch.setattr(products, "load_saved_recipe_output", lambda url: deepcopy(RECIPE) if url == "recipe://soup" else {"servings": 4, "ingredients": [{"ingredient": "flour", "quantity": 2, "unit": "cup"}]})
    monkeypatch.setattr(products, "load_recipe_option_selections", lambda url: {})
    context = products.load_item_quantity_context(["flour", "milk"])
    assert context["flour"]["display"] == "5 cup"
    assert context["milk"]["display"] == "6 cup"
    assert sum(source.get("meal_plan_source_id") is not None for source in context["flour"]["sources"]) == 1
    monkeypatch.setattr(products, "load_item_state", lambda: {"flour": {"manual_qty": "1/2 cup"}})
    assert products.load_item_quantity_context(["flour"])["flour"]["display"] == "3 1/2 cup"


def test_shopping_view_context_matches_product_totals_and_preserves_manual_state(isolated_shopping, monkeypatch):
    batch, _ = seed_batch()
    add_review(service.review_meal_plan_shopping({"batch_ids": [batch["id"]]}), list_id="current")
    state = {}
    recipe_rows = [
        {"url": "recipe://soup", "number": 1, "sections": {"Baking": [{"name": "flour", "quantity_display": "1 cup"}]}},
        {"url": "recipe://cake", "number": 2, "sections": {"Baking": [{"name": "flour", "quantity_display": "2 cups"}]}},
    ]
    monkeypatch.setattr(main_routes, "load_items", shopping.load_items)
    monkeypatch.setattr(main_routes, "load_item_state", lambda: deepcopy(state))
    monkeypatch.setattr(main_routes, "load_store_settings", lambda: {"stores": {}, "enabled_stores": []})
    monkeypatch.setattr(main_routes, "product_choices_by_item", lambda: {})
    monkeypatch.setattr(main_routes, "recipe_url_rows", lambda: [{"url": row["url"]} for row in recipe_rows])
    monkeypatch.setattr(main_routes, "recipe_rows_context", lambda **kwargs: {"recipe_view_rows": recipe_rows, "food_rules": []})
    monkeypatch.setattr(main_routes, "build_store_view", lambda *args: [])
    context = main_routes.shopping_views_context()
    assert context["item_quantities"]["flour"] == "5 cups"
    sources = context["recipe_item_quantity_sources"]["flour"]
    assert [row["quantity"] for row in sources] == ["2 cups", "3 cup"]
    assert sources[-1]["meal_plan_source_id"] == "batch:" + batch["id"]
    state["flour"] = {"manual_qty": "1/2 cup"}
    context = main_routes.shopping_views_context()
    assert context["item_quantities"]["flour"] == "3 1/2 cups"
    assert state == {"flour": {"manual_qty": "1/2 cup"}}


def test_compatible_components_sum_and_incompatible_units_stay_explicit(isolated_shopping):
    assert service._quantity_sum(["1 cup + 2 oz", "2 cups", "3 ounces"]) == "3 cup + 5 oz"
    assert service._quantity_sum(["to taste", "to taste"]) == "to taste + to taste"


@pytest.mark.parametrize("selection", [None, [], {}, {"week_start": "no"}, {"meal_ids": "bad"}, {"batch_ids": [3]}, {"recipe_url": "recipe://soup"}, {"week_start": "2026-09-28", "meal_ids": []}, {"meal_ids": ["foreign"]}])
def test_bad_selection_never_writes(isolated_shopping, selection):
    seed_batch()
    with pytest.raises(ValueError):
        service.review_meal_plan_shopping(selection)
    assert not service.SHOPPING_PLAN_FILE.exists()


def test_stale_review_rejected_without_list_or_names_write(isolated_shopping):
    batch, meals = seed_batch()
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    plans.update_meal(meals[0]["id"], {"planned_servings": 6})
    with pytest.raises(service.ShoppingPlanError) as error:
        add_review(review, list_id="current")
    assert error.value.status == 409
    assert shopping.load_items() == [] and not service.SHOPPING_PLAN_FILE.exists()


def test_invalid_destination_and_exclusions_are_atomic(isolated_shopping):
    batch, _ = seed_batch()
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    for destination in ({}, {"list_id": "foreign"}, {"new_list_name": " "}, {"new_list_name": "a", "list_id": "current"},
                        {"new_list_name": "Good", "excluded_item_ids": ["foreign"]},
                        {"list_id": "current", "excluded_item_ids": [row["id"] for row in review["items"]]}):
        with pytest.raises(ValueError):
            add_review(review, **destination)
    assert not service.SHOPPING_PLAN_FILE.exists()
    saved = add_review(review, new_list_name="Groceries")
    before = service.SHOPPING_PLAN_FILE.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        add_review(review, new_list_name="groceries")
    with pytest.raises(ValueError):
        service.set_shopping_plan_item_checked(saved["list"]["id"], saved["list"]["items"][0]["id"], "true")
    assert service.SHOPPING_PLAN_FILE.read_bytes() == before


def test_current_list_failed_ledger_save_restores_existing_items(isolated_shopping, monkeypatch):
    batch, _ = seed_batch()
    shopping.save_items(["coffee"])
    review = service.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    monkeypatch.setattr(service, "_save", lambda value: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        add_review(review, list_id="current")
    assert shopping.load_items() == ["coffee"]


def test_routes_auth_scope_named_lists_checks_and_no_recipe_metadata_writes(scoped_client, monkeypatch):
    client = scoped_client
    monkeypatch.setattr(service, "SHOPPING_PLAN_FILE", storage_service.scoped_package_path("meal_plan_shopping.json"))
    monkeypatch.setattr(shopping, "SHOPPING_LIST_FILE", storage_service.scoped_package_path("shopping_list.txt"))
    monkeypatch.setattr(service, "load_saved_recipe_output", lambda url: deepcopy(RECIPE))
    monkeypatch.setattr(service, "load_item_state", lambda: {})
    monkeypatch.setattr(service, "load_pantry_inventory", lambda: {"items": []})
    base = "/api/meal-plan/shopping"
    assert client.post(base + "/review", json={"selection": {"week_start": "2026-09-28"}}).status_code == 403
    assert client.get(base + "/lists").status_code == 403
    sign_in(client, "alice")
    with client.application.test_request_context():
        from flask import g
        g.session_identity_validated = True
        g.authenticated_user_id = "alice"
        g.authenticated_guest_session_id = ""
        batch, _ = seed_batch()
    review = client.post(base + "/review", json={"selection": {"batch_ids": [batch["id"]]}})
    assert review.status_code == 200 and "_contributions" not in review.json
    result = client.post(base + "/add", json={"selection": review.json["selection"], "review_token": review.json["review_token"], "new_list_name": "Week groceries"})
    assert result.status_code == 201
    list_id = result.json["list"]["id"]
    item_id = result.json["list"]["items"][0]["id"]
    assert client.get(base + "/lists").json["lists"][1]["id"] == list_id
    assert client.get(base + f"/lists/{list_id}").json["list"]["items"]
    checked = client.patch(base + f"/lists/{list_id}/items/{item_id}", json={"checked": True})
    assert checked.json["list"]["items"][0]["checked"] is True
    assert client.patch(base + f"/lists/{list_id}/items/{item_id}", json={"checked": 1}).status_code == 400
    assert client.post(base + "/review?viewer_user_id=bob", json={"selection": {"batch_ids": [batch["id"]]}}).status_code == 403
    sign_in(client, "bob")
    assert client.get(base + f"/lists/{list_id}").status_code == 404
    assert client.post(base + "/review", json={"selection": {"batch_ids": [batch["id"]]}}).status_code == 404
    assert client.get(base + "/lists").json["lists"] == [{"id": "current", "name": "Current shopping list", "item_count": 0}]
    sign_in(client, "guest-shopping", guest=True)
    assert client.get(base + f"/lists/{list_id}").status_code == 404
    assert client.get(base + "/lists").status_code == 200
