"""Compatibility helpers for recipe ingredient requirements and grouped options.

The persisted recipe format continues to use the existing ingredient row plus
its flat ``substitutions`` collection.  These helpers expose that data as
requirements/options without introducing a second ingredient store.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy


OPTION_TYPES = {"original", "recipe_choice", "substitution", "custom"}
GROUP_ONLY_ITEM_FIELDS = {
    "substitutions",
    "substitution_options",
    "alternatives",
    "ingredient_requirement_id",
    "default_option_id",
    "original_option_id",
    "original_option_label",
    "original_is_default",
    "selection_required",
    "alternative_id",
    "group_id",
    "substitution_group_id",
    "alternative_order",
    "alternative_component_order",
    "alternative_label",
    "option_type",
    "recipe_authored",
    "is_default",
    "preferred",
}


class IngredientOptionSelectionRequired(ValueError):
    def __init__(self, requirements):
        self.requirements = requirements
        count = len(requirements)
        super().__init__(
            f"Choose an ingredient option for {count} requirement"
            f"{'' if count == 1 else 's'} before adding this recipe to the shopping list."
        )


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def truthy(value):
    if isinstance(value, bool):
        return value
    return clean_text(value).lower() in {"1", "true", "yes", "y", "on"}


def ingredient_name(item):
    if not isinstance(item, dict):
        return clean_text(item)
    return clean_text(
        item.get("ingredient")
        or item.get("name")
        or item.get("purchasable_item")
        or item.get("buy_as")
        or item.get("original_text")
    )


def shopping_item_name(item):
    if not isinstance(item, dict):
        return clean_text(item)
    return clean_text(
        item.get("purchasable_item")
        or item.get("buy_as")
        or item.get("ingredient")
        or item.get("name")
        or item.get("original_text")
    )


def stable_identifier(prefix, *values):
    payload = "|".join(clean_text(value).lower() for value in values)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def requirement_id(item, index=0):
    item = item if isinstance(item, dict) else {}
    return clean_text(
        item.get("ingredient_requirement_id")
        or item.get("recipe_ingredient_id")
        or item.get("row_id")
        or item.get("id")
    ) or stable_identifier(
        "requirement",
        index,
        item.get("original_text"),
        item.get("ingredient"),
        item.get("quantity"),
        item.get("unit"),
    )


def original_option_id(item, index=0):
    return f"original:{requirement_id(item, index)}"


def substitution_rows(item):
    item = item if isinstance(item, dict) else {}
    value = (
        item.get("substitutions")
        or item.get("substitution_options")
        or item.get("alternatives")
        or []
    )
    if isinstance(value, str):
        value = [part for part in re.split(r"[\r\n;]+", value) if clean_text(part)]
    if not isinstance(value, list):
        value = [value] if value else []

    rows = []
    for alternative_index, option in enumerate(value):
        if not isinstance(option, dict):
            name = clean_text(option)
            if name:
                rows.append({"ingredient": name, "_legacy_index": alternative_index})
            continue

        components = next(
            (
                option.get(field)
                for field in ("ingredients", "components", "replacements")
                if isinstance(option.get(field), list)
            ),
            None,
        )
        if components is None:
            rows.append({**option, "_legacy_index": alternative_index})
            continue

        shared = {
            key: value
            for key, value in option.items()
            if key not in {"ingredients", "components", "replacements"}
        }
        group_id = clean_text(
            option.get("alternative_id")
            or option.get("group_id")
            or option.get("id")
            or option.get("substitution_id")
        )
        for component_index, component in enumerate(components):
            component = component if isinstance(component, dict) else {"ingredient": component}
            row = {
                **shared,
                **component,
                "_legacy_index": alternative_index,
                "alternative_component_order": component.get(
                    "alternative_component_order",
                    component_index,
                ),
            }
            if group_id:
                row["alternative_id"] = clean_text(
                    component.get("alternative_id") or group_id
                )
            rows.append(row)
    return [row for row in rows if ingredient_name(row)]


def alternative_option_type(rows):
    explicit = clean_text(
        next(
            (
                row.get("option_type")
                for row in rows
                if clean_text(row.get("option_type")) in OPTION_TYPES
            ),
            "",
        )
    )
    if explicit:
        return explicit
    if any(truthy(row.get("recipe_authored")) for row in rows):
        return "recipe_choice"
    if rows and all(not truthy(row.get("inferred", True)) for row in rows):
        return "recipe_choice"
    group_id = clean_text(rows[0].get("alternative_id") if rows else "")
    if group_id.startswith("inline-form-"):
        return "recipe_choice"
    return "substitution"


def grouped_substitution_rows(item, index=0):
    item = item if isinstance(item, dict) else {}
    parent_id = requirement_id(item, index)
    groups = []
    by_id = {}

    for row_index, source_row in enumerate(substitution_rows(item)):
        row = deepcopy(source_row)
        group_id = clean_text(
            row.get("alternative_id")
            or row.get("group_id")
            or row.get("substitution_group_id")
        )
        if not group_id:
            group_id = stable_identifier(
                "alternative",
                parent_id,
                row.get("_legacy_index", row_index),
                ingredient_name(row),
            )
        group = by_id.get(group_id)
        if group is None:
            group = {
                "id": group_id,
                "rows": [],
                "first_index": row_index,
                "sort_order": row.get("alternative_order", row_index),
            }
            by_id[group_id] = group
            groups.append(group)
        row["alternative_id"] = group_id
        row.pop("_legacy_index", None)
        group["rows"].append(row)

    def numeric_order(value, fallback):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    groups.sort(
        key=lambda group: (
            numeric_order(group.get("sort_order"), group["first_index"]),
            group["first_index"],
        )
    )
    for group_index, group in enumerate(groups):
        indexed_rows = list(enumerate(group["rows"]))
        indexed_rows.sort(
            key=lambda pair: numeric_order(
                pair[1].get("alternative_component_order"),
                pair[0],
            )
        )
        group["rows"] = [row for _, row in indexed_rows]
        group["option_type"] = alternative_option_type(group["rows"])
        group["is_default"] = bool(
            clean_text(item.get("default_option_id")) == group["id"]
            or any(
                truthy(row.get("is_default")) or truthy(row.get("preferred"))
                for row in group["rows"]
            )
        )
        group["label"] = clean_text(
            next(
                (
                    row.get("alternative_label")
                    for row in group["rows"]
                    if clean_text(row.get("alternative_label"))
                ),
                "",
            )
        ) or " + ".join(ingredient_name(row) for row in group["rows"])
    return groups


def option_item(item):
    return {
        key: deepcopy(value)
        for key, value in (item if isinstance(item, dict) else {"ingredient": item}).items()
        if not str(key).startswith("_") and key not in GROUP_ONLY_ITEM_FIELDS
    }


def ingredient_requirement(item, index=0):
    item = item if isinstance(item, dict) else {"ingredient": item}
    item = deepcopy(item)
    req_id = requirement_id(item, index)
    original_id = original_option_id(item, index)
    groups = grouped_substitution_rows(item, index)
    explicit_original_group = next(
        (group for group in groups if group["option_type"] == "original"),
        None,
    )
    default_option_id = clean_text(item.get("default_option_id"))
    if not default_option_id:
        default_group = next((group for group in groups if group["is_default"]), None)
        default_option_id = default_group["id"] if default_group else ""
    if truthy(item.get("original_is_default")):
        default_option_id = (
            explicit_original_group["id"]
            if explicit_original_group
            else original_id
        )
    elif (
        explicit_original_group
        and (not default_option_id or default_option_id == original_id)
    ):
        default_option_id = explicit_original_group["id"]

    original_label = clean_text(item.get("original_option_label")) or "Original"
    options = []
    # A normal legacy ingredient row is itself the original option.  A grouped
    # requirement can instead persist an explicit ``option_type=original``
    # substitution group.  That shape supports default options made from two or
    # more ingredients while keeping the top-level row as a non-purchasable
    # summary/container.
    if not explicit_original_group:
        options.append({
            "id": original_id,
            "label": original_label,
            "option_type": "original",
            "is_default": default_option_id == original_id,
            "sort_order": 0,
            "items": [option_item(item)],
        })
    for group in groups:
        options.append({
            "id": group["id"],
            "label": group["label"],
            "option_type": group["option_type"],
            "is_default": default_option_id == group["id"],
            "sort_order": group["sort_order"],
            "items": [option_item(row) for row in group["rows"]],
        })

    return {
        "id": req_id,
        "label": clean_text(item.get("requirement_label") or ingredient_name(item)),
        "source_text": clean_text(item.get("source_text") or item.get("original_text")),
        "default_option_id": default_option_id or None,
        "selection_required": len(options) > 1,
        "sort_order": index,
        "options": options,
    }


def ingredient_requirements(recipe_or_ingredients):
    if isinstance(recipe_or_ingredients, dict):
        ingredients = recipe_or_ingredients.get("ingredients", [])
    else:
        ingredients = recipe_or_ingredients
    if not isinstance(ingredients, list):
        return []
    return [
        ingredient_requirement(item, index)
        for index, item in enumerate(ingredients)
        if ingredient_name(item)
    ]


def public_requirement(requirement):
    return {
        "id": requirement["id"],
        "label": requirement["label"],
        "source_text": requirement["source_text"],
        "default_option_id": requirement["default_option_id"],
        "selection_required": requirement["selection_required"],
        "options": [
            {
                "id": option["id"],
                "label": option["label"],
                "option_type": option["option_type"],
                "is_default": option["is_default"],
                "items": [
                    {
                        "ingredient": ingredient_name(item),
                        "quantity": clean_text(item.get("quantity")),
                        "unit": clean_text(item.get("unit")),
                        "preparation": clean_text(item.get("preparation")),
                    }
                    for item in option["items"]
                ],
            }
            for option in requirement["options"]
        ],
    }


def normalize_selection_map(value):
    if not isinstance(value, dict):
        return {}
    return {
        clean_text(requirement_id): clean_text(option_id)
        for requirement_id, option_id in value.items()
        if clean_text(requirement_id) and clean_text(option_id)
    }


def resolve_ingredient_requirements(
    recipe_or_ingredients,
    selections=None,
    *,
    require_all=False,
):
    selections = normalize_selection_map(selections)
    selected_items = []
    selected_options = {}
    unresolved = []

    for requirement in ingredient_requirements(recipe_or_ingredients):
        option_id = selections.get(requirement["id"]) or requirement["default_option_id"]
        if not requirement["selection_required"]:
            option_id = option_id or requirement["options"][0]["id"]
        option = next(
            (candidate for candidate in requirement["options"] if candidate["id"] == option_id),
            None,
        )
        if option is None:
            unresolved.append(public_requirement(requirement))
            continue
        selected_options[requirement["id"]] = option["id"]
        selected_items.extend(deepcopy(option["items"]))

    if require_all and unresolved:
        raise IngredientOptionSelectionRequired(unresolved)

    return {
        "items": selected_items,
        "selected_options": selected_options,
        "unresolved_requirements": unresolved,
        "selection_needed": bool(unresolved),
    }


def migrate_ingredient_requirement(item, index=0):
    """Add stable group metadata while keeping the existing flat row shape."""
    if not isinstance(item, dict):
        return item

    migrated = deepcopy(item)
    req_id = requirement_id(migrated, index)
    migrated["recipe_ingredient_id"] = clean_text(
        migrated.get("recipe_ingredient_id")
    ) or req_id
    migrated["source_text"] = clean_text(
        migrated.get("source_text") or migrated.get("original_text")
    )
    groups = grouped_substitution_rows(migrated, index)
    flat_rows = []
    for group_index, group in enumerate(groups):
        for component_index, row in enumerate(group["rows"]):
            row = deepcopy(row)
            row.update({
                "alternative_id": group["id"],
                "alternative_order": group.get("sort_order", group_index),
                "alternative_component_order": component_index,
                "alternative_label": clean_text(
                    row.get("alternative_label") or group["label"]
                ),
                "option_type": clean_text(
                    row.get("option_type") or group["option_type"]
                ),
                "recipe_authored": (
                    truthy(row.get("recipe_authored"))
                    or group["option_type"] == "recipe_choice"
                ),
                "is_default": group["is_default"],
            })
            if group["is_default"]:
                row["preferred"] = True
            flat_rows.append(row)
    migrated["substitutions"] = flat_rows
    explicit_original_group = next(
        (group for group in groups if group["option_type"] == "original"),
        None,
    )
    migrated["selection_required"] = (
        len(groups) > 1 if explicit_original_group else bool(flat_rows)
    )
    default_option_id = clean_text(migrated.get("default_option_id"))
    if (
        explicit_original_group
        and (
            not default_option_id
            or default_option_id == original_option_id(migrated, index)
        )
    ):
        default_option_id = explicit_original_group["id"]
    elif not default_option_id:
        default_group = next((group for group in groups if group["is_default"]), None)
        default_option_id = (
            default_group["id"]
            if default_group
            else explicit_original_group["id"]
            if explicit_original_group
            else ""
        )
    migrated["default_option_id"] = default_option_id
    return migrated


def migrate_recipe_ingredient_options(recipe_data):
    if not isinstance(recipe_data, dict):
        return recipe_data
    migrated = deepcopy(recipe_data)
    ingredients = migrated.get("ingredients")
    if isinstance(ingredients, list):
        migrated["ingredients"] = [
            migrate_ingredient_requirement(item, index)
            for index, item in enumerate(ingredients)
        ]
    return migrated


def amount_label(item):
    item = item if isinstance(item, dict) else {}
    quantity = clean_text(item.get("quantity"))
    unit = clean_text(item.get("unit"))
    return " ".join(part for part in (quantity, unit) if part)


def option_item_label(item):
    amount = amount_label(item)
    name = ingredient_name(item)
    preparation = clean_text(item.get("preparation"))
    value = " ".join(part for part in (amount, name) if part)
    if preparation:
        value = f"{value}, {preparation}" if value else preparation
    return value


def pdf_requirement_rows(item, index=0):
    requirement = ingredient_requirement(item, index)
    options = requirement["options"]
    original = options[0]
    original_item = original["items"][0]
    alternatives = options[1:]
    if not alternatives:
        return [{
            "kind": "ingredient",
            "amount": amount_label(original_item),
            "ingredient": ingredient_name(original_item),
            "preparation": clean_text(original_item.get("preparation")),
        }]

    recipe_choices = all(option["option_type"] == "recipe_choice" for option in alternatives)
    same_ingredient = all(
        len(option["items"]) == 1
        and ingredient_name(option["items"][0]).lower() == ingredient_name(original_item).lower()
        for option in alternatives
    )
    if recipe_choices and same_ingredient:
        preparations = [
            clean_text(original_item.get("preparation")),
            *[
                clean_text(option["items"][0].get("preparation"))
                for option in alternatives
            ],
        ]
        preparations = [value for value in preparations if value]
        if preparations:
            return [{
                "kind": "ingredient",
                "amount": amount_label(original_item),
                "ingredient": ingredient_name(original_item),
                "preparation": " or ".join(preparations),
            }]

    rows = [{
        "kind": "ingredient",
        "amount": amount_label(original_item),
        "ingredient": ingredient_name(original_item),
        "preparation": clean_text(original_item.get("preparation")),
    }]
    for option_index, option in enumerate(alternatives):
        rows.append({
            "kind": "alternative",
            "amount": "",
            "ingredient": " + ".join(
                option_item_label(option_item)
                for option_item in option["items"]
                if option_item_label(option_item)
            ),
            "preparation": "",
            "label": "Alternative" if option_index == 0 else f"Alternative {option_index + 1}",
        })
    return rows
