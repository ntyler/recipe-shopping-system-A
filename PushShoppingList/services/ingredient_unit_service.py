"""Canonical ingredient-unit registry and deterministic field normalization.

This module is intentionally independent of Flask and recipe extraction so every
import, editor save, migration, and display surface can share the same rules.
Quantities are never converted here; only the unit label and misplaced metadata
are normalized.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from fractions import Fraction


LOGGER = logging.getLogger(__name__)


CANONICAL_UNITS = (
    ("volume_teaspoon", "teaspoon", "volume"),
    ("volume_tablespoon", "tablespoon", "volume"),
    ("volume_fluid_ounce", "fluid ounce", "volume"),
    ("volume_cup", "cup", "volume"),
    ("volume_pint", "pint", "volume"),
    ("volume_quart", "quart", "volume"),
    ("volume_gallon", "gallon", "volume"),
    ("volume_milliliter", "milliliter", "volume"),
    ("volume_liter", "liter", "volume"),
    ("weight_ounce", "ounce", "weight"),
    ("weight_pound", "pound", "weight"),
    ("weight_gram", "gram", "weight"),
    ("weight_kilogram", "kilogram", "weight"),
    ("count_piece", "piece", "count_package"),
    ("count_clove", "clove", "count_package"),
    ("count_slice", "slice", "count_package"),
    ("count_link", "link", "count_package"),
    ("count_sprig", "sprig", "count_package"),
    ("count_stalk", "stalk", "count_package"),
    ("count_bunch", "bunch", "count_package"),
    ("count_head", "head", "count_package"),
    ("count_leaf", "leaf", "count_package"),
    ("package_package", "package", "count_package"),
    ("package_packet", "packet", "count_package"),
    ("package_can", "can", "count_package"),
    ("package_jar", "jar", "count_package"),
    ("package_bottle", "bottle", "count_package"),
    ("package_box", "box", "count_package"),
    ("package_bag", "bag", "count_package"),
    ("package_container", "container", "count_package"),
    ("optional_pinch", "pinch", "optional"),
    ("optional_dash", "dash", "optional"),
    ("optional_drop", "drop", "optional"),
    ("optional_to_taste", "to taste", "optional"),
    ("optional_as_needed", "as needed", "optional"),
)

CANONICAL_BY_ID = {
    unit_id: {"id": unit_id, "name": name, "category": category, "sort_order": index}
    for index, (unit_id, name, category) in enumerate(CANONICAL_UNITS)
}
CANONICAL_BY_NAME = {row["name"]: row for row in CANONICAL_BY_ID.values()}


def _unit_key(value):
    text = unicodedata.normalize("NFKC", str(value or "")).lower().strip()
    text = text.replace(".", "")
    text = re.sub(r"[_-]+", " ", text)
    return re.sub(r"\s+", " ", text)


_EXPLICIT_ALIASES = {
    "teaspoon": ("tsp", "tsps", "teaspoon", "teaspoons"),
    "tablespoon": ("tbsp", "tbs", "tbsps", "tablespoon", "tablespoons"),
    "cup": ("c", "cup", "cups"),
    "fluid ounce": ("fl oz", "fluid oz", "fluid ounce", "fluid ounces"),
    "ounce": ("oz", "ounce", "ounces"),
    "pound": ("lb", "lbs", "pound", "pounds"),
    "gram": ("g", "gram", "grams"),
    "kilogram": ("kg", "kilogram", "kilograms"),
    "milliliter": ("ml", "milliliter", "milliliters"),
    "liter": ("l", "liter", "liters", "litre", "litres"),
    "pint": ("pt", "pint", "pints"),
    "quart": ("qt", "quart", "quarts"),
    "gallon": ("gal", "gallon", "gallons"),
    "piece": ("pc", "pcs", "piece", "pieces"),
    "package": ("pkg", "pkgs", "package", "packages"),
    "packet": ("pkt", "pkts", "packet", "packets"),
    "can": ("can", "cans"),
    "jar": ("jar", "jars"),
    "bottle": ("bottle", "bottles"),
    "box": ("box", "boxes"),
    "bag": ("bag", "bags"),
    "container": ("container", "containers"),
    "clove": ("clove", "cloves"),
    "slice": ("slice", "slices"),
    "link": ("link", "links"),
    "sprig": ("sprig", "sprigs"),
    "stalk": ("stalk", "stalks"),
    "bunch": ("bunch", "bunches"),
    "head": ("head", "heads"),
    "leaf": ("leaf", "leaves"),
    "pinch": ("pinch", "pinches"),
    "dash": ("dash", "dashes"),
    "drop": ("drop", "drops"),
    "to taste": ("taste", "to taste"),
    "as needed": ("needed", "as needed"),
}

UNIT_ALIAS_TO_NAME = {
    _unit_key(alias): canonical
    for canonical, aliases in _EXPLICIT_ALIASES.items()
    for alias in aliases
}

SIZE_VALUES = ("extra large", "small", "medium", "large")
PREPARATION_VALUES = (
    "chopped", "diced", "minced", "sliced", "fresh", "ripe", "whole"
)
INGREDIENT_VALUES = ("pepper", "onion", "garlic")


def canonical_unit_options():
    return [dict(CANONICAL_BY_ID[unit_id]) for unit_id, _, _ in CANONICAL_UNITS]


def canonical_unit_aliases():
    return dict(UNIT_ALIAS_TO_NAME)


def unit_registry_payload():
    return {
        "units": canonical_unit_options(),
        "aliases": canonical_unit_aliases(),
    }


def canonical_unit(value):
    """Return registry metadata for a canonical name or accepted alias."""
    name = UNIT_ALIAS_TO_NAME.get(_unit_key(value))
    return dict(CANONICAL_BY_NAME[name]) if name else None


def canonical_unit_alias_pattern():
    """Regex fragment matching accepted aliases, longest first."""
    aliases = sorted(UNIT_ALIAS_TO_NAME, key=lambda item: (-len(item), item))
    return "(?:" + "|".join(re.escape(alias) + r"\.?" for alias in aliases) + ")"


def _clean_phrase(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def misplaced_unit_ingredient_details(ingredient, original_text, unit=""):
    """Describe an obvious unit/ingredient field swap, or return ``None``.

    Some inferred recipes placed values such as ``teaspoon`` in the ingredient
    field while retaining the actual grocery item in ``original_text``.  Keep
    the check deliberately narrow: the ingredient must be a known unit and the
    source text must not contain that unit at all.
    """
    ingredient_text = _clean_phrase(ingredient)
    original = _clean_phrase(original_text)
    misplaced_unit = canonical_unit(ingredient_text)
    if not misplaced_unit or not original or not re.search(r"[A-Za-z]", original):
        return None

    current_unit = canonical_unit(unit)
    if current_unit and current_unit["id"] != misplaced_unit["id"]:
        return None

    original_key = re.sub(r"[^a-z0-9]+", " ", _unit_key(original)).strip()
    matching_aliases = (
        alias
        for alias, canonical_name in UNIT_ALIAS_TO_NAME.items()
        if canonical_name == misplaced_unit["name"]
    )
    if any(re.search(rf"(?:^|\s){re.escape(alias)}(?:$|\s)", original_key) for alias in matching_aliases):
        return None

    return {
        "ingredient": ingredient_text,
        "original_text": original,
        "unit": misplaced_unit["name"],
        "unit_id": misplaced_unit["id"],
    }


def repair_misplaced_unit_ingredient(item):
    """Repair a narrowly detected unit/ingredient field swap in place."""
    if not isinstance(item, dict):
        return False

    ingredient_text = _clean_phrase(
        item.get("ingredient")
        or item.get("name")
        or item.get("parsed_name")
        or item.get("normalized_name")
    )
    original = _clean_phrase(item.get("original_text") or item.get("original_recipe_text"))
    details = misplaced_unit_ingredient_details(ingredient_text, original, item.get("unit"))
    if not details:
        return False

    misplaced_unit_id = details["unit_id"]
    item["ingredient"] = original
    for field in ("name", "parsed_name", "normalized_name"):
        value = _clean_phrase(item.get(field))
        value_unit = canonical_unit(value)
        if value and value_unit and value_unit["id"] == misplaced_unit_id:
            item[field] = original
    for field in ("purchasable_item", "buy_as", "purchase_group"):
        value = _clean_phrase(item.get(field))
        value_unit = canonical_unit(value)
        if value and value_unit and value_unit["id"] == misplaced_unit_id:
            item[field] = original

    item["unit"] = details["unit"]
    item["unit_id"] = details["unit_id"]
    item["unit_raw"] = item.get("unit_raw") or ingredient_text
    item["unit_review_required"] = False
    item["unit_review_value"] = ""
    item["unit_custom"] = False
    return True


def _append_preparation(existing, value):
    parts = [_clean_phrase(existing), _clean_phrase(value)]
    return ", ".join(dict.fromkeys(part for part in parts if part))


def _set_piece(row):
    piece = CANONICAL_BY_NAME["piece"]
    row["unit"] = piece["name"]
    row["unit_id"] = piece["id"]


def _strip_leading_metadata(row):
    ingredient = _clean_phrase(
        row.get("ingredient") or row.get("name") or row.get("parsed_name")
    )
    if not ingredient:
        return

    size_pattern = "|".join(re.escape(value) for value in SIZE_VALUES)
    size_match = re.match(rf"^(?P<size>{size_pattern})\b\s*(?P<rest>.*)$", ingredient, re.I)
    if size_match:
        row["size"] = row.get("size") or _unit_key(size_match.group("size"))
        ingredient = _clean_phrase(size_match.group("rest"))
        if not row.get("quantity"):
            row["quantity"] = "1"
            row["recipe_qty"] = row.get("recipe_qty") or "1"

        # A size may precede a package unit: "1 large can tomatoes".
        parts = ingredient.split(" ", 1)
        possible_unit = canonical_unit(parts[0]) if parts else None
        if possible_unit and possible_unit["category"] == "count_package" and len(parts) > 1:
            row["unit"] = possible_unit["name"]
            row["unit_id"] = possible_unit["id"]
            ingredient = _clean_phrase(parts[1])
        elif not row.get("unit"):
            _set_piece(row)

    prep_pattern = "|".join(re.escape(value) for value in PREPARATION_VALUES)
    prep_match = re.match(rf"^(?P<prep>{prep_pattern})\b\s*(?P<rest>.*)$", ingredient, re.I)
    if prep_match and prep_match.group("rest"):
        row["preparation"] = _append_preparation(row.get("preparation"), prep_match.group("prep").lower())
        ingredient = _clean_phrase(prep_match.group("rest"))

    if ingredient:
        ingredient = re.sub(r"\bpeppers$", "pepper", ingredient, flags=re.I)
        row["ingredient"] = ingredient
        if row.get("parsed_name"):
            row["parsed_name"] = ingredient


def normalize_ingredient_unit_fields(item, *, log_unrecognized=True):
    """Normalize unit metadata in place and return *item*.

    Unknown values remain in the recipe-specific ``unit`` field and are also
    retained in ``unit_raw``/``unit_review_value``. They never receive a
    canonical ``unit_id``; the review flag makes that distinction explicit
    without discarding what the recipe or user supplied.
    """
    if not isinstance(item, dict):
        return item

    repair_misplaced_unit_ingredient(item)
    raw_current = _clean_phrase(item.get("unit"))
    saved_raw = _clean_phrase(item.get("unit_raw") or item.get("raw_unit"))
    review_flag = item.get("unit_review_required")
    needs_review = review_flag is True or str(review_flag or "").strip().lower() in {"1", "true", "yes", "on"}
    candidate = raw_current or (
        _clean_phrase(item.get("unit_review_value")) or saved_raw
        if needs_review
        else ""
    )
    if not candidate and not any(
        _clean_phrase(item.get(field))
        for field in ("ingredient", "name", "parsed_name", "original_text", "original_recipe_text", "quantity")
    ):
        return item
    if candidate and not saved_raw:
        item["unit_raw"] = candidate
    elif saved_raw:
        item["unit_raw"] = saved_raw

    key = _unit_key(candidate)
    explicit_custom = str(item.get("unit_custom") or "").strip().lower() in {"1", "true", "yes", "on"}
    normalized = canonical_unit(candidate) if candidate else None
    preserved_custom = bool(candidate and explicit_custom and not normalized)
    item["unit_review_required"] = False
    item["unit_review_value"] = ""
    item["unit_custom"] = preserved_custom

    if preserved_custom:
        item["unit"] = candidate
        item["unit_id"] = ""
    elif key in SIZE_VALUES:
        item["size"] = item.get("size") or key
        item["unit"] = ""
        item["unit_id"] = ""
        if not item.get("quantity"):
            item["quantity"] = "1"
            item["recipe_qty"] = item.get("recipe_qty") or "1"
        _set_piece(item)
    elif key in PREPARATION_VALUES:
        item["preparation"] = _append_preparation(item.get("preparation"), key)
        item["unit"] = ""
        item["unit_id"] = ""
    elif key in INGREDIENT_VALUES:
        ingredient = _clean_phrase(item.get("ingredient") or item.get("name"))
        if not ingredient or _unit_key(ingredient) == key:
            item["ingredient"] = ingredient or key
            item["unit"] = ""
            item["unit_id"] = ""
            if item.get("quantity"):
                _set_piece(item)
        else:
            item["unit"] = ""
            item["unit_id"] = ""
            item["unit_review_required"] = True
            item["unit_review_value"] = candidate
    elif candidate:
        if normalized:
            item["unit"] = normalized["name"]
            item["unit_id"] = normalized["id"]
            item["unit_custom"] = False
        else:
            # Unit text belongs to the recipe. Normalization may decline to
            # assign a canonical ID, but it must not erase the source value.
            item["unit"] = candidate
            item["unit_id"] = ""
            item["unit_review_required"] = True
            item["unit_review_value"] = candidate
            if log_unrecognized:
                LOGGER.warning(
                    "Unrecognized ingredient unit requires review: %r (ingredient=%r)",
                    candidate,
                    item.get("ingredient") or item.get("name") or "",
                )
    else:
        item["unit"] = ""
        item["unit_id"] = ""

    ingredient = _clean_phrase(item.get("ingredient") or item.get("name") or item.get("parsed_name"))
    original = _clean_phrase(item.get("original_text") or item.get("original_recipe_text"))
    if not preserved_custom:
        optional_match = re.search(r"(?:,?\s+)(to taste|as needed)\s*$", ingredient, re.I)
        if not optional_match:
            optional_match = re.search(r"(?:,?\s+)(to taste|as needed)\s*$", original, re.I)
        if optional_match:
            optional = canonical_unit(optional_match.group(1))
            item["unit"] = optional["name"]
            item["unit_id"] = optional["id"]
            item["quantity"] = ""
            item["recipe_qty"] = ""
            item["base_quantity"] = ""
            item["unit_review_required"] = False
            item["unit_review_value"] = ""
            item["ingredient"] = re.sub(
                r"(?:,?\s+)(?:to taste|as needed)\s*$", "", ingredient, flags=re.I
            ).strip()
            item["preparation"] = re.sub(
                r"(?:^|,\s*)(?:to taste|as needed)(?:\s*,|$)", "", _clean_phrase(item.get("preparation")), flags=re.I
            ).strip(" ,")

        _strip_leading_metadata(item)

    base_unit = _clean_phrase(item.get("base_unit"))
    if base_unit:
        normalized_base = canonical_unit(base_unit)
        item["base_unit"] = normalized_base["name"] if normalized_base else item.get("unit", "")
    elif item.get("unit"):
        item["base_unit"] = item["unit"]

    if not item.get("base_quantity") and item.get("quantity"):
        item["base_quantity"] = item["quantity"]
    return item


def normalize_recipe_unit_fields(recipe_data, *, log_unrecognized=True):
    """Apply unit-only normalization to every structured ingredient collection."""
    if not isinstance(recipe_data, dict):
        return recipe_data
    collections = []
    for key in ("ingredients", "ingredient_details"):
        if isinstance(recipe_data.get(key), list):
            collections.append(recipe_data[key])
    raw = recipe_data.get("raw") if isinstance(recipe_data.get("raw"), dict) else {}
    for key in ("ingredients", "ingredient_details"):
        if isinstance(raw.get(key), list):
            collections.append(raw[key])

    seen = set()
    for rows in collections:
        if id(rows) in seen:
            continue
        seen.add(id(rows))
        for item in rows:
            if not isinstance(item, dict):
                continue
            normalize_ingredient_unit_fields(item, log_unrecognized=log_unrecognized)
            substitutions = item.get("substitutions")
            if isinstance(substitutions, list):
                for option in substitutions:
                    if isinstance(option, dict):
                        normalize_ingredient_unit_fields(option, log_unrecognized=log_unrecognized)
    return recipe_data


def display_unit(value, quantity=None):
    """Pluralize a canonical unit for rendering without changing storage."""
    unit = canonical_unit(value)
    if not unit:
        return _clean_phrase(value)
    name = unit["name"]
    quantity_text = str(quantity or "").strip().split(" OR ", 1)[0]
    quantity_text = re.split(r"\s*(?:-|to)\s*", quantity_text, maxsplit=1)[0].strip()
    try:
        if re.match(r"^\d+\s+\d+/\d+$", quantity_text):
            whole, fraction = quantity_text.split(None, 1)
            amount = Fraction(int(whole), 1) + Fraction(fraction)
        else:
            amount = Fraction(quantity_text)
        singular = amount == 1
    except (TypeError, ValueError, ZeroDivisionError):
        singular = True
    if singular or name in {"to taste", "as needed"}:
        return name
    irregular = {"leaf": "leaves", "dash": "dashes"}
    return irregular.get(name, name + ("es" if name.endswith(("s", "x", "ch")) else "s"))
