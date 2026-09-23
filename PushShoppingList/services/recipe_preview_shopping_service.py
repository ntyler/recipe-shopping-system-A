"""Add the displayed draft to a shopping instance without saving the recipe."""

from copy import deepcopy

from PushShoppingList.services import recipe_ingredient_service as ingredient_store
from PushShoppingList.services import recipe_quantity_service as quantities
from PushShoppingList.services import shopping_list_service as shopping
from PushShoppingList.services.ingredient_option_service import shopping_item_name
from PushShoppingList.services.recipe_url_service import add_recipe_urls, normalize_recipe_url_key


def add_preview_to_shopping_list(payload):
    # Lazy import avoids the editor/quantity services' existing import cycle.
    from PushShoppingList.services import recipe_edit_service
    from PushShoppingList.services.recipe_preview_service import prepare_recipe_preview

    if not isinstance(payload, dict):
        raise ValueError("Recipe preview details are invalid.")
    preview, _scaled = prepare_recipe_preview(payload)
    options = preview["options"]
    base_payload = deepcopy(payload)
    base_payload["options"] = {**options, "scale": 1}
    _base_preview, base_recipe = prepare_recipe_preview(base_payload)
    url = str(payload.get("original_url") or payload.get("url") or "").strip()
    if not url:
        raise ValueError("Recipe URL is required.")
    base_recipe["source_url"] = url
    saved_recipe = recipe_edit_service.load_recipe_output(url)
    names = [shopping_item_name(item) for item in base_recipe.get("ingredients", [])]
    names = [name for name in names if name]
    if not names:
        raise ValueError("This recipe has no ingredients to add.")

    # This is an optional shopping-instance snapshot, not an editor save. The
    # normal recipe save/restore paths rebuild this record and retire it.
    with shopping.SHOPPING_LIST_LOCK:
        records = ingredient_store.load_recipe_ingredients()
        key = normalize_recipe_url_key(url)
        existing = records.get(key, {})
        previous_names = existing.get("ingredients", [])
        record = ingredient_store.recipe_ingredients_record(
            url, names, saved_recipe, existing=existing,
        )
        scale = options["scale"]
        scaled = quantities.calculate_scaled_values_locally(base_recipe, scale)
        record.update({
            "quantity": scale,
            "scaled_servings": scaled.get("servings"),
            "scaled_ingredients": scaled.get("ingredients", {}),
            "scaling_model": quantities.RECIPE_SCALING_MODEL,
            "ingredient_details": ingredient_store.ingredient_detail_records(
                ingredients=names, recipe_metadata=base_recipe,
            ),
            "shopping_preview_recipe": deepcopy(base_recipe),
        })
        result = shopping.add_items(names)
        records[key] = record
        ingredient_store.save_recipe_ingredients(records)
        shopping.save_recipe_option_selections(url, preview["ingredient_option_selections"])
        add_recipe_urls([url])
        ingredient_store.remove_unused_ingredients_from_shopping_list(previous_names, records)

    return {
        "ok": True,
        "added": result["added"],
        "ingredient_count": len(names),
        "quantity": scale,
        "servings": scaled.get("servings"),
        "recipe_url": url,
        "ingredient_option_selections": preview["ingredient_option_selections"],
    }
