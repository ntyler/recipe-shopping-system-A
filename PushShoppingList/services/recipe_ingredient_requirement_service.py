"""Normalized persistence for recipe ingredient requirements and options.

SQLite is the authoritative store for the requirement/option hierarchy.  The
legacy top-level ingredient plus flat ``substitutions`` shape remains the
compatibility representation used by the existing editor and JSON files.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import g
from flask import has_request_context

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services.ingredient_option_service import (
    GROUP_ONLY_ITEM_FIELDS,
    clean_text,
    grouped_substitution_rows,
    ingredient_name,
    ingredient_requirement,
    original_option_id,
    substitution_rows,
    truthy,
)


REQUIREMENT_RELATIONAL_FIELDS = {
    "id",
    "row_id",
    "ingredient_requirement_id",
    "recipe_ingredient_id",
    "requirement_label",
    "source_text",
    "default_option_id",
    "selection_required",
    "sort_order",
    "substitutions",
    "substitution_options",
    "alternatives",
}

ITEM_RELATIONAL_FIELDS = {
    "ingredient_id",
    "master_ingredient_id",
    "master_name",
    "ingredient",
    "name",
    "raw_name",
    "normalized_name",
    "master_normalized_name",
    "canonical_ingredient",
    "form",
    "quantity",
    "recipe_qty",
    "unit",
    "unit_id",
    "unit_raw",
    "size",
    "preparation",
    "notes",
    "unit_review_required",
    "unit_review_value",
    "unit_custom",
    "buy_as",
    "purchasable_item",
    "store_section",
    "store_section_source",
    "store_section_confidence",
    "store_section_user_confirmed",
    "classifier_version",
    "store_section_reason",
    "store_section_rule",
    "original_recipe_text",
    "original_text",
    "section",
    "ingredient_type",
    "optional",
    "sort_order",
}


_REQUEST_REQUIREMENT_CONNECTION = "_recipe_ingredient_requirement_connection"
_REQUEST_CONNECTION_UNSET = object()

INTERNAL_METADATA_KEY = "_normalized_requirement_compatibility"
INTERNAL_COMPONENT_METADATA_KEY = "_normalized_option_item_compatibility"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _json_object(value):
    if isinstance(value, dict):
        return deepcopy(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_dump(value):
    return json.dumps(
        value if isinstance(value, dict) else {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _order(value, fallback=0):
    if isinstance(value, bool):
        return int(fallback)
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return int(fallback)


def _preserved_text(value):
    """Trim outer whitespace without altering authored internal spacing."""
    return str(value if value is not None else "").strip()


def _recipe_source_hash(recipe_data):
    ingredients = (
        recipe_data.get("ingredients", [])
        if isinstance(recipe_data, dict)
        else []
    )
    serialized = json.dumps(
        ingredients,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _substitution_value(item):
    if not isinstance(item, dict):
        return []
    for field in ("substitutions", "substitution_options", "alternatives"):
        if field in item:
            return item.get(field)
    return []


def _malformed_alternative_records(item, requirement_id, requirement_index):
    """Return raw alternative fragments the compatibility parser cannot model."""
    value = _substitution_value(item)
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    malformed = []

    for alternative_index, option in enumerate(values):
        if isinstance(option, str):
            if clean_text(option):
                continue
            malformed.append({
                "requirement_id": requirement_id,
                "requirement_index": requirement_index,
                "alternative_index": alternative_index,
                "reason": "empty alternative text",
                "value": deepcopy(option),
            })
            continue
        if not isinstance(option, dict):
            malformed.append({
                "requirement_id": requirement_id,
                "requirement_index": requirement_index,
                "alternative_index": alternative_index,
                "reason": "alternative is not an object or non-empty string",
                "value": deepcopy(option),
            })
            continue

        component_field = next(
            (
                field
                for field in ("ingredients", "components", "replacements")
                if isinstance(option.get(field), list)
            ),
            None,
        )
        if component_field is None:
            if not ingredient_name(option):
                malformed.append({
                    "requirement_id": requirement_id,
                    "requirement_index": requirement_index,
                    "alternative_index": alternative_index,
                    "reason": "alternative has no ingredient name",
                    "value": deepcopy(option),
                })
            continue

        components = option.get(component_field) or []
        shared = {
            key: deepcopy(shared_value)
            for key, shared_value in option.items()
            if key not in {"ingredients", "components", "replacements"}
        }
        if not components:
            malformed.append({
                "requirement_id": requirement_id,
                "requirement_index": requirement_index,
                "alternative_index": alternative_index,
                "reason": "grouped alternative has no components",
                "value": deepcopy(option),
            })
            continue
        for component_index, component in enumerate(components):
            component_item = (
                component
                if isinstance(component, dict)
                else {"ingredient": component}
            )
            if ingredient_name(component_item):
                continue
            preserved = {
                **shared,
                **(deepcopy(component) if isinstance(component, dict) else {
                    "ingredient": deepcopy(component)
                }),
                "alternative_component_order": component_index,
            }
            malformed.append({
                "requirement_id": requirement_id,
                "requirement_index": requirement_index,
                "alternative_index": alternative_index,
                "component_index": component_index,
                "reason": "alternative component has no ingredient name",
                "value": preserved,
            })
    return malformed


def _requirement_metadata(item, *, explicit_original, malformed):
    metadata = {
        key: deepcopy(value)
        for key, value in item.items()
        if key not in REQUIREMENT_RELATIONAL_FIELDS
        and key not in ITEM_RELATIONAL_FIELDS
        and key not in GROUP_ONLY_ITEM_FIELDS
    }
    legacy_reserved_metadata = deepcopy(metadata.get(INTERNAL_METADATA_KEY))
    metadata[INTERNAL_METADATA_KEY] = {
        "explicit_original_option": bool(explicit_original),
        "malformed_alternatives": deepcopy(malformed),
        # An explicit grouped original uses the top-level legacy row as a
        # display container rather than as an option item.  Retain that
        # container for compatibility export while the option-item columns
        # remain authoritative for purchasable quantities and units.
        "legacy_parent": (
            {
                key: deepcopy(value)
                for key, value in item.items()
                if key not in {
                    "substitutions",
                    "substitution_options",
                    "alternatives",
                }
            }
            if explicit_original
            else {
                # A synthetic original is reconstructed from its relational
                # option item. Only retain the presence of requirement-level
                # compatibility fields here; do not duplicate quantities,
                # units, or preparation in requirement metadata.
                key: None
                for key in (
                    "requirement_label",
                    "recipe_ingredient_id",
                    "source_text",
                    "default_option_id",
                    "original_is_default",
                    "selection_required",
                )
                if key in item
            }
        ),
        "legacy_substitution_fields": [
            field
            for field in ("substitutions", "substitution_options", "alternatives")
            if field in item
        ],
    }
    if INTERNAL_METADATA_KEY in item:
        metadata[INTERNAL_METADATA_KEY]["legacy_reserved_metadata"] = (
            legacy_reserved_metadata
        )
    return metadata


def _item_metadata(item):
    item = item if isinstance(item, dict) else {}
    metadata = (
        deepcopy(item.get("metadata"))
        if isinstance(item.get("metadata"), dict)
        else {}
    )
    metadata.update({
        key: deepcopy(value)
        for key, value in item.items()
        if key not in ITEM_RELATIONAL_FIELDS
        and key not in GROUP_ONLY_ITEM_FIELDS
        and key != "metadata"
        and key not in {
            "_legacy_index",
            "_legacy_group_size",
            "_legacy_present_fields",
            "_legacy_was_nested",
            INTERNAL_METADATA_KEY,
            INTERNAL_COMPONENT_METADATA_KEY,
        }
    })
    component_compatibility = item.get(INTERNAL_COMPONENT_METADATA_KEY)
    if isinstance(component_compatibility, dict):
        metadata[INTERNAL_COMPONENT_METADATA_KEY] = deepcopy(
            component_compatibility
        )
    return metadata


def requirements_from_legacy_recipe(recipe_data):
    """Convert legacy JSON ingredients into normalized domain objects.

    The return value includes diagnostics so malformed legacy fragments can be
    reported while their raw values remain preserved in requirement metadata.
    """
    ingredients = (
        recipe_data.get("ingredients")
        if isinstance(recipe_data, dict)
        else None
    )
    diagnostics = {"malformed_records": 0, "skipped_records": 0, "issues": []}
    if ingredients is None:
        ingredients = []
    if not isinstance(ingredients, list):
        diagnostics["malformed_records"] = 1
        diagnostics["skipped_records"] = 1
        diagnostics["issues"].append({
            "reason": "recipe ingredients is not a list",
            "value": deepcopy(ingredients),
        })
        return [], diagnostics

    requirements = []
    for index, source_item in enumerate(ingredients):
        if isinstance(source_item, dict):
            item = deepcopy(source_item)
        else:
            name = ingredient_name(source_item)
            if not name:
                diagnostics["malformed_records"] += 1
                diagnostics["skipped_records"] += 1
                diagnostics["issues"].append({
                    "requirement_index": index,
                    "reason": "top-level ingredient has no ingredient name",
                    "value": deepcopy(source_item),
                })
                continue
            item = {"ingredient": name}

        if not ingredient_name(item):
            diagnostics["malformed_records"] += 1
            diagnostics["skipped_records"] += 1
            diagnostics["issues"].append({
                "requirement_index": index,
                "reason": "top-level ingredient has no ingredient name",
                "value": deepcopy(source_item),
            })
            continue

        parsed = ingredient_requirement(item, index)
        req_id = clean_text(parsed.get("id"))
        groups = grouped_substitution_rows(item, index)
        explicit_original = any(
            group.get("option_type") == "original" for group in groups
        )
        malformed = _malformed_alternative_records(item, req_id, index)
        diagnostics["malformed_records"] += len(malformed)
        diagnostics["issues"].extend(deepcopy(malformed))

        group_by_id = {clean_text(group.get("id")): group for group in groups}
        options = []
        for option_index, parsed_option in enumerate(parsed.get("options") or []):
            option_id = clean_text(parsed_option.get("id"))
            option_type = clean_text(parsed_option.get("option_type")) or "substitution"
            group = group_by_id.get(option_id, {})
            group_rows = (
                group.get("rows") or []
                if isinstance(group, dict)
                else []
            )
            explicit_recipe_authored = [
                row.get("recipe_authored")
                for row in (group_rows or [])
                if "recipe_authored" in row
            ]
            recipe_authored = (
                any(truthy(value) for value in explicit_recipe_authored)
                if explicit_recipe_authored
                else option_type in {"original", "recipe_choice"}
            )
            parsed_items = []
            for component_index, parsed_item in enumerate(
                parsed_option.get("items") or []
            ):
                domain_item = (
                    deepcopy(parsed_item)
                    if isinstance(parsed_item, dict)
                    else {"ingredient": ingredient_name(parsed_item)}
                )
                source_group_row = (
                    group_rows[component_index]
                    if component_index < len(group_rows)
                    and isinstance(group_rows[component_index], dict)
                    else item
                    if option_type == "original"
                    and not explicit_original
                    and component_index == 0
                    else {}
                )
                component_compatibility = {}
                legacy_present_fields = source_group_row.get(
                    "_legacy_present_fields"
                )
                component_compatibility["legacy_present_fields"] = sorted(
                    str(field)
                    for field in (
                        legacy_present_fields
                        if isinstance(legacy_present_fields, list)
                        else source_group_row
                    )
                )
                component_compatibility["legacy_was_nested"] = bool(
                    source_group_row.get("_legacy_was_nested")
                )
                if "recipe_authored" in source_group_row:
                    component_compatibility["recipe_authored"] = deepcopy(
                        source_group_row.get("recipe_authored")
                    )
                if "raw_name" in source_group_row:
                    component_compatibility["legacy_raw_name"] = deepcopy(
                        source_group_row.get("raw_name")
                    )
                if "metadata" in source_group_row:
                    # ``metadata`` is also the normalized domain container.
                    # Remember when it was an actual legacy JSON field so the
                    # compatibility exporter can restore the wrapper instead
                    # of flattening its contents into the ingredient row.
                    component_compatibility["legacy_metadata_field"] = deepcopy(
                        source_group_row.get("metadata")
                    )
                null_fields = [
                    field
                    for field in ITEM_RELATIONAL_FIELDS
                    if field in source_group_row
                    and source_group_row.get(field) is None
                ]
                if null_fields:
                    component_compatibility["legacy_null_fields"] = sorted(
                        null_fields
                    )
                if component_compatibility:
                    domain_item[INTERNAL_COMPONENT_METADATA_KEY] = (
                        component_compatibility
                    )
                parsed_items.append(domain_item)

            option_metadata = {
                "legacy_synthetic_original": bool(
                    option_type == "original"
                    and not explicit_original
                    and option_id == original_option_id(item, index)
                )
            }
            if isinstance(group, dict) and "first_index" in group:
                option_metadata["legacy_alternative_index"] = _order(
                    group.get("first_index"),
                    option_index,
                )
            options.append({
                "id": option_id,
                "label": clean_text(parsed_option.get("label")) or option_id,
                "option_type": option_type,
                "recipe_authored": bool(recipe_authored),
                "sort_order": _order(parsed_option.get("sort_order"), option_index),
                "metadata": option_metadata,
                "items": parsed_items,
            })

        metadata = _requirement_metadata(
            item,
            explicit_original=explicit_original,
            malformed=malformed,
        )
        default_option_id = clean_text(parsed.get("default_option_id")) or None
        valid_option_ids = {
            clean_text(option.get("id"))
            for option in options
            if clean_text(option.get("id"))
        }
        if default_option_id and default_option_id not in valid_option_ids:
            invalid_default_issue = {
                "requirement_id": req_id,
                "requirement_index": index,
                "reason": "default option does not identify a valid alternative",
                "value": default_option_id,
            }
            diagnostics["malformed_records"] += 1
            diagnostics["issues"].append(deepcopy(invalid_default_issue))
            metadata[INTERNAL_METADATA_KEY]["invalid_default_option_id"] = (
                default_option_id
            )
            default_option_id = None
        if default_option_id is None and len(options) == 1:
            # A simple ingredient has one explicit original option in SQL, so
            # that option is also an explicit, reliable relational default.
            default_option_id = options[0]["id"]

        requirements.append({
            "id": req_id,
            "label": clean_text(parsed.get("label")) or ingredient_name(item),
            "source_text": _preserved_text(
                item.get("source_text") or item.get("original_text")
            ),
            "default_option_id": default_option_id,
            "selection_required": bool(parsed.get("selection_required")),
            "sort_order": index,
            "metadata": metadata,
            "options": options,
        })

    return requirements, diagnostics


def _legacy_item_from_domain(item):
    # This accepts both repository-loaded items (whose ancillary values live
    # in ``metadata``) and freshly converted domain items (which can still
    # carry legacy ancillary fields at the top level).
    metadata = _item_metadata(item)
    component_compatibility = _json_object(
        metadata.pop(INTERNAL_COMPONENT_METADATA_KEY, None)
    )
    result = deepcopy(metadata)
    ingredient_value = clean_text(
        item.get("ingredient")
        or item.get("master_name")
        or item.get("normalized_name")
        or item.get("raw_name")
    )
    result.update({
        "ingredient_id": (
            str(item.get("ingredient_id"))
            if item.get("ingredient_id") not in (None, "")
            else ""
        ),
        "ingredient": ingredient_value,
        "raw_name": clean_text(item.get("raw_name")) or ingredient_value,
        "normalized_name": clean_text(item.get("normalized_name")),
        "master_normalized_name": clean_text(item.get("normalized_name")),
        "canonical_ingredient": clean_text(item.get("canonical_ingredient")),
        "form": clean_text(item.get("form")),
        "quantity": clean_text(item.get("quantity")),
        "recipe_qty": clean_text(item.get("quantity")),
        "unit": clean_text(item.get("unit")),
        "unit_id": clean_text(item.get("unit_id")),
        "unit_raw": clean_text(item.get("unit_raw")),
        "size": clean_text(item.get("size")),
        "preparation": clean_text(item.get("preparation")),
        "notes": clean_text(item.get("notes")),
        "unit_review_required": bool(item.get("unit_review_required")),
        "unit_review_value": clean_text(item.get("unit_review_value")),
        "unit_custom": bool(item.get("unit_custom")),
        "buy_as": clean_text(item.get("buy_as")),
        "purchasable_item": clean_text(item.get("purchasable_item")),
        "store_section": clean_text(item.get("store_section")),
        "store_section_source": clean_text(item.get("store_section_source")),
        "store_section_confidence": item.get("store_section_confidence", 0),
        "store_section_user_confirmed": bool(
            item.get("store_section_user_confirmed")
        ),
        "classifier_version": clean_text(item.get("classifier_version")),
        "store_section_reason": clean_text(item.get("store_section_reason")),
        "store_section_rule": clean_text(item.get("store_section_rule")),
        "original_text": _preserved_text(item.get("original_recipe_text")),
        "section": clean_text(
            item.get("ingredient_type")
            or item.get("section")
        ) or ("optional" if item.get("optional") else "main"),
        "optional": bool(item.get("optional")),
    })
    if "legacy_raw_name" in component_compatibility:
        result["raw_name"] = deepcopy(
            component_compatibility.get("legacy_raw_name")
        )
    legacy_null_fields = component_compatibility.get("legacy_null_fields")
    if isinstance(legacy_null_fields, list):
        output_field = {
            "original_recipe_text": "original_text",
        }
        for field in legacy_null_fields:
            target_field = output_field.get(field, field)
            if target_field in result and result.get(target_field) in (
                None,
                "",
                False,
                0,
            ):
                result[target_field] = None
    legacy_present_fields = component_compatibility.get("legacy_present_fields")
    if isinstance(legacy_present_fields, list):
        present = {str(field) for field in legacy_present_fields}
        if (
            "unit" in present
            and "unit_raw" not in present
            and clean_text(item.get("unit_raw"))
        ):
            # Legacy JSON used one display field for both canonical units and
            # raw size/count words (for example ``medium``). SQLite keeps the
            # canonical value in ``unit`` and that authored spelling in the
            # dedicated ``unit_raw`` column; the compatibility cache should
            # continue displaying the authored spelling.
            result["unit"] = clean_text(item.get("unit_raw"))
        output_sources = {
            "ingredient_id": {"ingredient_id", "master_ingredient_id"},
            "raw_name": {"raw_name"},
            "normalized_name": {"normalized_name"},
            "master_normalized_name": {"master_normalized_name"},
            "canonical_ingredient": {"canonical_ingredient"},
            "form": {"form"},
            "quantity": {"quantity"},
            "recipe_qty": {"recipe_qty"},
            "unit": {"unit"},
            "unit_id": {"unit_id"},
            "unit_raw": {"unit_raw"},
            "size": {"size"},
            "preparation": {"preparation"},
            "notes": {"notes"},
            "unit_review_required": {"unit_review_required"},
            "unit_review_value": {"unit_review_value"},
            "unit_custom": {"unit_custom"},
            "buy_as": {"buy_as"},
            "purchasable_item": {"purchasable_item"},
            "store_section": {"store_section"},
            "store_section_source": {"store_section_source"},
            "store_section_confidence": {"store_section_confidence"},
            "store_section_user_confirmed": {"store_section_user_confirmed"},
            "classifier_version": {"classifier_version"},
            "store_section_reason": {"store_section_reason"},
            "store_section_rule": {"store_section_rule"},
            "original_text": {"original_text", "original_recipe_text"},
            "section": {"section", "ingredient_type", "type"},
            "optional": {"optional"},
        }
        for output_field, source_fields in output_sources.items():
            if not present.intersection(source_fields):
                result.pop(output_field, None)
        if "legacy_metadata_field" in component_compatibility:
            legacy_metadata = deepcopy(
                component_compatibility.get("legacy_metadata_field")
            )
            if isinstance(legacy_metadata, dict):
                # Keys that existed only inside the wrapper should not also
                # appear at the row's top level. Preserve true top-level key
                # collisions in both locations.
                for key in legacy_metadata:
                    if str(key) not in present:
                        result.pop(key, None)
            result["metadata"] = legacy_metadata
    return result


def legacy_ingredients_from_requirements(requirements):
    """Export normalized domain objects to the current flat JSON shape."""
    legacy = []
    for requirement_index, requirement in enumerate(requirements or []):
        if not isinstance(requirement, dict):
            continue
        req_id = clean_text(requirement.get("id"))
        req_metadata = _json_object(requirement.get("metadata"))
        compatibility = _json_object(req_metadata.pop(INTERNAL_METADATA_KEY, {}))
        legacy_parent = _json_object(compatibility.get("legacy_parent"))
        options = [
            option
            for option in (requirement.get("options") or [])
            if isinstance(option, dict)
        ]
        original = next(
            (option for option in options if option.get("option_type") == "original"),
            options[0] if options else None,
        )
        synthetic_original = bool(
            original
            and _json_object(original.get("metadata")).get(
                "legacy_synthetic_original"
            )
        )

        if synthetic_original and original and original.get("items"):
            parent = _legacy_item_from_domain(original["items"][0])
            substitution_options = [
                option for option in options if option is not original
            ]
        else:
            parent = deepcopy(legacy_parent) if legacy_parent else {}
            parent.update(deepcopy(req_metadata))
            parent["ingredient"] = clean_text(requirement.get("label"))
            substitution_options = options
        if "legacy_reserved_metadata" in compatibility:
            parent[INTERNAL_METADATA_KEY] = deepcopy(
                compatibility.get("legacy_reserved_metadata")
            )

        requirement_label = clean_text(requirement.get("label"))
        if (
            "requirement_label" in legacy_parent
            or requirement_label != clean_text(parent.get("ingredient"))
        ):
            parent["requirement_label"] = requirement_label

        if "recipe_ingredient_id" in legacy_parent:
            parent["recipe_ingredient_id"] = req_id
        else:
            parent.pop("recipe_ingredient_id", None)
        if "source_text" in legacy_parent:
            parent["source_text"] = _preserved_text(
                requirement.get("source_text")
            )
        else:
            parent.pop("source_text", None)
        relational_default = clean_text(requirement.get("default_option_id"))
        if (
            "default_option_id" in legacy_parent
            or (relational_default and len(options) > 1)
        ):
            parent["default_option_id"] = clean_text(
                requirement.get("default_option_id")
            )
        else:
            parent.pop("default_option_id", None)
        if (
            "selection_required" in legacy_parent
            or len(options) > 1
            or bool(requirement.get("selection_required"))
        ):
            parent["selection_required"] = bool(
                requirement.get("selection_required")
            )
        else:
            parent.pop("selection_required", None)
        if "original_is_default" in legacy_parent:
            parent["original_is_default"] = bool(
                original
                and clean_text(original.get("id")) == relational_default
            )
        else:
            parent.pop("original_is_default", None)

        substitutions = []
        for option_index, option in enumerate(substitution_options):
            option_id = clean_text(option.get("id"))
            option_label = clean_text(option.get("label"))
            option_type = clean_text(option.get("option_type")) or "substitution"
            option_order = _order(option.get("sort_order"), option_index)
            is_default = option_id == clean_text(requirement.get("default_option_id"))
            for component_index, item in enumerate(option.get("items") or []):
                row = _legacy_item_from_domain(item)
                item_metadata = _json_object(item.get("metadata"))
                component_compatibility = _json_object(
                    item_metadata.get(INTERNAL_COMPONENT_METADATA_KEY)
                )
                component_recipe_authored = (
                    truthy(component_compatibility.get("recipe_authored"))
                    if "recipe_authored" in component_compatibility
                    else bool(option.get("recipe_authored"))
                )
                row.update({
                    "alternative_id": option_id,
                    "alternative_order": option_order,
                    "alternative_component_order": component_index,
                    "alternative_label": option_label,
                    "option_type": option_type,
                    "recipe_authored": component_recipe_authored,
                    "is_default": is_default,
                    "preferred": is_default,
                })
                legacy_present_fields = component_compatibility.get(
                    "legacy_present_fields"
                )
                if (
                    isinstance(legacy_present_fields, list)
                    and not component_compatibility.get("legacy_was_nested")
                ):
                    present = {str(field) for field in legacy_present_fields}
                    for compatibility_field in (
                        "alternative_id",
                        "alternative_order",
                        "alternative_component_order",
                        "alternative_label",
                        "option_type",
                        "recipe_authored",
                        "is_default",
                        "preferred",
                    ):
                        if compatibility_field not in present:
                            row.pop(compatibility_field, None)
                substitutions.append(row)

        # Invalid legacy fragments cannot become relational option items, but
        # they remain auditable and are re-emitted instead of disappearing.
        for malformed in compatibility.get("malformed_alternatives") or []:
            if isinstance(malformed, dict) and "value" in malformed:
                substitutions.append(deepcopy(malformed["value"]))

        if substitutions or compatibility.get("legacy_substitution_fields"):
            parent["substitutions"] = substitutions
        else:
            parent.pop("substitutions", None)
        legacy.append(parent)
    return legacy


def _normalized_option_item(connection, user_id, item, sort_order):
    item = item if isinstance(item, dict) else {"ingredient": ingredient_name(item)}
    candidate_rows = master_data.ingredient_rows_from_sources(
        recipe_data={"ingredients": [deepcopy(item)]},
        user_id=user_id,
        connection=connection,
    )
    row = candidate_rows[0] if candidate_rows else {}
    display_name = ingredient_name(item)
    ingredient_id = None

    if row:
        ingredient_result = master_data.update_ingredient_master_record_from_recipe_row(
            connection,
            user_id,
            row,
        )
        if not ingredient_result:
            ingredient_result = master_data.upsert_master_record(
                connection,
                "ingredients",
                user_id,
                row["name"],
                image_url=row.get("image_url", ""),
                image_path=row.get("image_path", ""),
                store_section=row.get("store_section", ""),
                store_section_metadata=row,
            )
        ingredient_id = (
            int(ingredient_result["id"])
            if ingredient_result and ingredient_result.get("id")
            else None
        )

    unit_id = clean_text(row.get("unit_id") or item.get("unit_id")) or None
    if unit_id:
        valid_unit = connection.execute(
            "SELECT 1 FROM canonical_units WHERE id = ?",
            (unit_id,),
        ).fetchone()
        if not valid_unit:
            unit_id = None

    return {
        "ingredient_id": ingredient_id,
        # Keep the authored ingredient display name in a dedicated relational
        # value.  A legacy extractor's fuller ``raw_name`` is retained in
        # compatibility metadata and restored on JSON export.
        "raw_name": display_name,
        "normalized_name": clean_text(
            row.get("normalized_name")
            or item.get("master_normalized_name")
            or item.get("normalized_name")
        ) or master_data.normalized_master_name(display_name),
        "canonical_ingredient": clean_text(
            row.get("canonical_ingredient") or item.get("canonical_ingredient")
        ),
        "form": clean_text(row.get("form") or item.get("form")),
        "quantity": clean_text(row.get("quantity") or item.get("quantity") or item.get("recipe_qty")),
        "unit": clean_text(row.get("unit") or item.get("unit")),
        "unit_id": unit_id,
        "unit_raw": clean_text(row.get("unit_raw") or item.get("unit_raw")),
        "size": clean_text(row.get("size") or item.get("size")),
        "preparation": clean_text(row.get("preparation") or item.get("preparation")),
        "notes": clean_text(row.get("notes") or item.get("notes")),
        "unit_review_required": bool(row.get("unit_review_required") or truthy(item.get("unit_review_required"))),
        "unit_review_value": clean_text(row.get("unit_review_value") or item.get("unit_review_value")),
        "unit_custom": bool(row.get("unit_custom") or truthy(item.get("unit_custom"))),
        "buy_as": clean_text(row.get("buy_as") or item.get("buy_as") or item.get("purchase_group")),
        "purchasable_item": clean_text(item.get("purchasable_item")),
        # Store sections are recipe-authored data even when older JSON did not
        # yet carry the explicit ``store_section_custom`` flag. Classification
        # may still update the master catalog, but it must not overwrite the
        # recipe option item's saved section.
        "store_section": clean_text(
            item.get("store_section") or row.get("store_section")
        ),
        "store_section_source": clean_text(row.get("store_section_source") or item.get("store_section_source")),
        "store_section_confidence": master_data.ingredient_store_section_confidence(
            row.get("store_section_confidence", item.get("store_section_confidence"))
        ),
        "store_section_user_confirmed": bool(
            row.get("store_section_user_confirmed")
            or truthy(item.get("store_section_user_confirmed"))
        ),
        "classifier_version": clean_text(row.get("classifier_version") or item.get("classifier_version")),
        "store_section_reason": clean_text(row.get("store_section_reason") or item.get("store_section_reason")),
        "store_section_rule": clean_text(row.get("store_section_rule") or item.get("store_section_rule")),
        "original_recipe_text": _preserved_text(
            item.get("original_recipe_text")
            or item.get("original_text")
            or row.get("original_recipe_text")
        ),
        "ingredient_type": clean_text(
            row.get("ingredient_type")
            or item.get("section")
            or item.get("ingredient_type")
            or item.get("type")
        ) or (
            "optional"
            if bool(row.get("optional") or truthy(item.get("optional")))
            else "main"
        ),
        "optional": bool(row.get("optional") or truthy(item.get("optional"))),
        "sort_order": int(sort_order),
        "metadata_json": _json_dump(_item_metadata(item)),
    }


def _delete_recipe_hierarchy(connection, user_id, recipe_id):
    connection.execute(
        "DELETE FROM recipe_ingredient_requirements WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id),
    )
    connection.execute(
        "DELETE FROM recipe_ingredient_requirement_sync WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id),
    )


def _save_requirements_with_connection(
    connection,
    recipe_url,
    recipe_data,
    requirements,
    *,
    user_id,
    previous_recipe_url=None,
    sync_compatibility=True,
    force_store_sections_from_recipe=False,
):
    recipe_id = master_data.recipe_id_for_url(recipe_url)
    previous_recipe_id = master_data.recipe_id_for_url(previous_recipe_url)
    if previous_recipe_id and previous_recipe_id != recipe_id:
        from PushShoppingList.services import recipe_equipment_requirement_service

        if recipe_equipment_requirement_service.structured_equipment_dual_write_enabled(
            user_id
        ):
            recipe_equipment_requirement_service.move_structured_recipe_identity(
                connection, user_id, previous_recipe_id, recipe_id
            )
        _delete_recipe_hierarchy(connection, user_id, previous_recipe_id)
        connection.execute(
            "DELETE FROM recipe_ingredients WHERE user_id = ? AND recipe_id = ?",
            (user_id, previous_recipe_id),
        )
        connection.execute(
            "DELETE FROM recipe_equipment WHERE user_id = ? AND recipe_id = ?",
            (user_id, previous_recipe_id),
        )

    _delete_recipe_hierarchy(connection, user_id, recipe_id)
    requirement_count = 0
    option_count = 0
    item_count = 0

    for requirement_index, requirement in enumerate(requirements):
        requirement_id = clean_text(requirement.get("id"))
        if not requirement_id:
            raise ValueError("Every ingredient requirement needs a stable id.")
        options = [
            option
            for option in (requirement.get("options") or [])
            if isinstance(option, dict)
        ]
        option_ids = {clean_text(option.get("id")) for option in options}
        default_option_id = clean_text(requirement.get("default_option_id")) or None
        if default_option_id and default_option_id not in option_ids:
            raise ValueError(
                f"Default option {default_option_id!r} is not part of requirement {requirement_id!r}."
            )
        cursor = connection.execute(
            """
            INSERT INTO recipe_ingredient_requirements (
                requirement_id, user_id, recipe_id, label, source_text,
                default_option_id, selection_required, sort_order,
                metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requirement_id,
                user_id,
                recipe_id,
                clean_text(requirement.get("label")),
                _preserved_text(requirement.get("source_text")),
                default_option_id,
                1 if requirement.get("selection_required") else 0,
                _order(requirement.get("sort_order"), requirement_index),
                _json_dump(requirement.get("metadata")),
                _utc_now_iso(),
                _utc_now_iso(),
            ),
        )
        requirement_row_id = int(cursor.lastrowid)
        requirement_count += 1

        for option_index, option in enumerate(options):
            option_id = clean_text(option.get("id"))
            if not option_id:
                raise ValueError(
                    f"Every option in requirement {requirement_id!r} needs a stable id."
                )
            option_type = clean_text(option.get("option_type")) or "substitution"
            if option_type not in {"original", "recipe_choice", "substitution", "custom"}:
                raise ValueError(f"Unsupported ingredient option type: {option_type!r}.")
            option_cursor = connection.execute(
                """
                INSERT INTO recipe_ingredient_options (
                    option_id, requirement_id, label, option_type,
                    recipe_authored, sort_order, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    option_id,
                    requirement_row_id,
                    clean_text(option.get("label")) or option_id,
                    option_type,
                    1 if option.get("recipe_authored") else 0,
                    _order(option.get("sort_order"), option_index),
                    _json_dump(option.get("metadata")),
                    _utc_now_iso(),
                    _utc_now_iso(),
                ),
            )
            option_row_id = int(option_cursor.lastrowid)
            option_count += 1

            for component_index, item in enumerate(option.get("items") or []):
                normalized = _normalized_option_item(
                    connection,
                    user_id,
                    item,
                    component_index,
                )
                connection.execute(
                    """
                    INSERT INTO recipe_ingredient_option_items (
                        option_id, ingredient_id, raw_name, normalized_name,
                        canonical_ingredient, form, quantity, unit, unit_id,
                        unit_raw, size, preparation, notes,
                        unit_review_required, unit_review_value, unit_custom,
                        buy_as, purchasable_item, store_section,
                        store_section_source, store_section_confidence,
                        store_section_user_confirmed, classifier_version,
                        store_section_reason, store_section_rule,
                        original_recipe_text, ingredient_type, optional, sort_order,
                        metadata_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        option_row_id,
                        normalized["ingredient_id"],
                        normalized["raw_name"],
                        normalized["normalized_name"],
                        normalized["canonical_ingredient"],
                        normalized["form"],
                        normalized["quantity"],
                        normalized["unit"],
                        normalized["unit_id"],
                        normalized["unit_raw"],
                        normalized["size"],
                        normalized["preparation"],
                        normalized["notes"],
                        1 if normalized["unit_review_required"] else 0,
                        normalized["unit_review_value"],
                        1 if normalized["unit_custom"] else 0,
                        normalized["buy_as"],
                        normalized["purchasable_item"],
                        normalized["store_section"],
                        normalized["store_section_source"],
                        normalized["store_section_confidence"],
                        1 if normalized["store_section_user_confirmed"] else 0,
                        normalized["classifier_version"],
                        normalized["store_section_reason"],
                        normalized["store_section_rule"],
                        normalized["original_recipe_text"],
                        normalized["ingredient_type"],
                        1 if normalized["optional"] else 0,
                        normalized["sort_order"],
                        normalized["metadata_json"],
                        _utc_now_iso(),
                        _utc_now_iso(),
                    ),
                )
                item_count += 1

    connection.execute(
        """
        INSERT INTO recipe_ingredient_requirement_sync (
            user_id, recipe_id, source_hash, requirement_count, synced_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, recipe_id) DO UPDATE SET
            source_hash = excluded.source_hash,
            requirement_count = excluded.requirement_count,
            synced_at = excluded.synced_at
        """,
        (
            user_id,
            recipe_id,
            _recipe_source_hash(recipe_data),
            requirement_count,
            _utc_now_iso(),
        ),
    )

    compatibility_result = {}
    if sync_compatibility:
        compatibility_sync = getattr(
            master_data,
            "_sync_recipe_master_records_with_connection",
            None,
        )
        if not callable(compatibility_sync):
            raise RuntimeError(
                "The recipe master compatibility transaction helper is unavailable."
            )
        compatibility_result = compatibility_sync(
            connection,
            recipe_url,
            ingredients=None,
            recipe_data=recipe_data,
            user_id=user_id,
            force_store_sections_from_recipe=force_store_sections_from_recipe,
        )

    return {
        "ok": True,
        "user_id": user_id,
        "recipe_id": recipe_id,
        "requirement_count": requirement_count,
        "option_count": option_count,
        "option_item_count": item_count,
        "ingredient_count": int(compatibility_result.get("ingredient_count") or 0),
        "equipment_count": int(compatibility_result.get("equipment_count") or 0),
    }


def save_normalized_recipe_ingredient_requirements(
    recipe_url,
    requirements,
    *,
    recipe_data=None,
    user_id=None,
    previous_recipe_url=None,
    connection=None,
    sync_compatibility=True,
    force_store_sections_from_recipe=False,
):
    """Atomically save an already-normalized requirement domain hierarchy."""
    recipe_url = clean_text(recipe_url)
    user_id = master_data.scoped_recipe_user_id(user_id)
    if not recipe_url or not user_id:
        raise ValueError("Recipe URL and user id are required.")
    if not isinstance(requirements, list):
        raise ValueError("Ingredient requirements must be a list.")

    requirements = deepcopy(requirements)
    recipe_data = deepcopy(recipe_data) if isinstance(recipe_data, dict) else {}
    recipe_data.setdefault("source_url", recipe_url)
    if not isinstance(recipe_data.get("ingredients"), list):
        recipe_data["ingredients"] = legacy_ingredients_from_requirements(
            requirements
        )

    if connection is not None:
        return _save_requirements_with_connection(
            connection,
            recipe_url,
            recipe_data,
            requirements,
            user_id=user_id,
            previous_recipe_url=previous_recipe_url,
            sync_compatibility=sync_compatibility,
            force_store_sections_from_recipe=force_store_sections_from_recipe,
        )
    with master_data.recipe_master_connection(user_id=user_id) as managed_connection:
        return _save_requirements_with_connection(
            managed_connection,
            recipe_url,
            recipe_data,
            requirements,
            user_id=user_id,
            previous_recipe_url=previous_recipe_url,
            sync_compatibility=sync_compatibility,
            force_store_sections_from_recipe=force_store_sections_from_recipe,
        )


def save_recipe_ingredient_requirements(
    recipe_url,
    recipe_data,
    *,
    user_id=None,
    previous_recipe_url=None,
    connection=None,
    sync_compatibility=True,
    force_store_sections_from_recipe=False,
):
    """Atomically replace one recipe's hierarchy and compatibility SQL rows."""
    recipe_url = clean_text(recipe_url)
    user_id = master_data.scoped_recipe_user_id(user_id)
    if not recipe_url or not user_id:
        raise ValueError("Recipe URL and user id are required.")
    recipe_data = deepcopy(recipe_data) if isinstance(recipe_data, dict) else {}
    requirements, diagnostics = requirements_from_legacy_recipe(recipe_data)
    if diagnostics.get("skipped_records"):
        raise ValueError(
            "Recipe ingredient requirements were not saved because one or more "
            "top-level ingredient rows could not be represented safely."
        )

    result = save_normalized_recipe_ingredient_requirements(
        recipe_url,
        requirements,
        recipe_data=recipe_data,
        user_id=user_id,
        previous_recipe_url=previous_recipe_url,
        connection=connection,
        sync_compatibility=sync_compatibility,
        force_store_sections_from_recipe=force_store_sections_from_recipe,
    )
    return {**result, **diagnostics}


def recipe_requirement_sync_status(recipe_url, user_id=None, *, connection=None):
    user_id = master_data.scoped_recipe_user_id(user_id)
    recipe_id = master_data.recipe_id_for_url(recipe_url)
    if not user_id or not recipe_id:
        return None

    def select(active_connection):
        table = active_connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("recipe_ingredient_requirement_sync",),
        ).fetchone()
        if not table:
            return None
        row = active_connection.execute(
            """
            SELECT user_id, recipe_id, source_hash, requirement_count, synced_at
              FROM recipe_ingredient_requirement_sync
             WHERE user_id = ? AND recipe_id = ?
            """,
            (user_id, recipe_id),
        ).fetchone()
        if not row:
            return None
        integrity = active_connection.execute(
            """
            SELECT COUNT(*) AS requirement_count,
                   COALESCE(SUM(
                       CASE WHEN EXISTS (
                           SELECT 1
                             FROM recipe_ingredient_options o
                            WHERE o.requirement_id = r.id
                       ) THEN 0 ELSE 1 END
                   ), 0) AS requirements_without_options
              FROM recipe_ingredient_requirements r
             WHERE r.user_id = ? AND r.recipe_id = ?
            """,
            (user_id, recipe_id),
        ).fetchone()
        if (
            int(integrity["requirement_count"] or 0)
            != int(row["requirement_count"] or 0)
            or int(integrity["requirements_without_options"] or 0) != 0
        ):
            return None
        return dict(row)

    if connection is not None:
        return select(connection)
    with _existing_requirement_connection() as managed_connection:
        return select(managed_connection) if managed_connection is not None else None


@contextmanager
def _existing_requirement_connection():
    """Reuse one request-local read connection without leaking or widening locks."""
    db_path = master_data.recipe_master_db_path()
    if not db_path.is_file():
        if has_request_context():
            setattr(g, _REQUEST_REQUIREMENT_CONNECTION, None)
        yield None
        return

    if has_request_context():
        connection = getattr(
            g,
            _REQUEST_REQUIREMENT_CONNECTION,
            _REQUEST_CONNECTION_UNSET,
        )
        if connection is _REQUEST_CONNECTION_UNSET:
            with master_data.RECIPE_MASTER_DB_LOCK:
                connection = sqlite3.connect(
                    f"{db_path.resolve().as_uri()}?mode=ro",
                    uri=True,
                    timeout=30,
                )
                connection.row_factory = sqlite3.Row
                try:
                    connection.execute("PRAGMA query_only=ON")
                except Exception:
                    connection.close()
                    raise
                setattr(g, _REQUEST_REQUIREMENT_CONNECTION, connection)

        if connection is None:
            yield None
            return

        # Preserve the service's existing process-local serialization while
        # avoiding connection setup/teardown for every recipe in one request.
        with master_data.RECIPE_MASTER_DB_LOCK:
            yield connection
        return

    with master_data.RECIPE_MASTER_DB_LOCK:
        connection = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            connection.close()


def close_request_requirement_connection(_error=None):
    """Close the request-local normalized-ingredient read connection."""
    if not has_request_context():
        return
    connection = g.pop(_REQUEST_REQUIREMENT_CONNECTION, None)
    if connection is not None:
        with master_data.RECIPE_MASTER_DB_LOCK:
            connection.close()


def load_recipe_ingredient_requirements(recipe_url, user_id=None, *, connection=None):
    """Load one user-scoped normalized hierarchy, or ``None`` if unsynced."""
    user_id = master_data.scoped_recipe_user_id(user_id)
    recipe_id = master_data.recipe_id_for_url(recipe_url)
    if not user_id or not recipe_id:
        return None

    def load(active_connection):
        status = recipe_requirement_sync_status(
            recipe_url,
            user_id,
            connection=active_connection,
        )
        if status is None:
            return None
        requirement_rows = active_connection.execute(
            """
            SELECT *
              FROM recipe_ingredient_requirements
             WHERE user_id = ? AND recipe_id = ?
             ORDER BY sort_order ASC, id ASC
            """,
            (user_id, recipe_id),
        ).fetchall()
        option_rows = active_connection.execute(
            """
            SELECT o.*
              FROM recipe_ingredient_options o
              JOIN recipe_ingredient_requirements r ON r.id = o.requirement_id
             WHERE r.user_id = ? AND r.recipe_id = ?
             ORDER BY r.sort_order ASC, r.id ASC, o.sort_order ASC, o.id ASC
            """,
            (user_id, recipe_id),
        ).fetchall()
        item_rows = active_connection.execute(
            """
            SELECT i.*, m.name AS master_name
              FROM recipe_ingredient_option_items i
              JOIN recipe_ingredient_options o ON o.id = i.option_id
              JOIN recipe_ingredient_requirements r ON r.id = o.requirement_id
              LEFT JOIN ingredients m
                ON m.id = i.ingredient_id AND m.user_id = r.user_id
             WHERE r.user_id = ? AND r.recipe_id = ?
             ORDER BY r.sort_order ASC, r.id ASC, o.sort_order ASC, o.id ASC,
                      i.sort_order ASC, i.id ASC
            """,
            (user_id, recipe_id),
        ).fetchall()

        items_by_option = {}
        for row in item_rows:
            item = dict(row)
            option_row_id = int(item.pop("option_id"))
            item.pop("id", None)
            item.pop("created_at", None)
            item.pop("updated_at", None)
            metadata = _json_object(item.pop("metadata_json", "{}"))
            item["metadata"] = metadata
            item["unit_review_required"] = bool(item.get("unit_review_required"))
            item["unit_custom"] = bool(item.get("unit_custom"))
            item["store_section_user_confirmed"] = bool(
                item.get("store_section_user_confirmed")
            )
            item["optional"] = bool(item.get("optional"))
            item["ingredient"] = clean_text(
                item.get("raw_name")
                or item.get("master_name")
                or item.get("normalized_name")
            )
            items_by_option.setdefault(option_row_id, []).append(item)

        options_by_requirement = {}
        for row in option_rows:
            option = dict(row)
            option_row_id = int(option.pop("id"))
            requirement_row_id = int(option.pop("requirement_id"))
            option.pop("created_at", None)
            option.pop("updated_at", None)
            option["id"] = option.pop("option_id")
            option["recipe_authored"] = bool(option.get("recipe_authored"))
            option["metadata"] = _json_object(option.pop("metadata_json", "{}"))
            option["items"] = items_by_option.get(option_row_id, [])
            options_by_requirement.setdefault(requirement_row_id, []).append(option)

        requirements = []
        for row in requirement_rows:
            requirement = dict(row)
            requirement_row_id = int(requirement.pop("id"))
            requirement.pop("user_id", None)
            requirement.pop("recipe_id", None)
            requirement.pop("created_at", None)
            requirement.pop("updated_at", None)
            requirement["id"] = requirement.pop("requirement_id")
            requirement["selection_required"] = bool(
                requirement.get("selection_required")
            )
            requirement["metadata"] = _json_object(
                requirement.pop("metadata_json", "{}")
            )
            requirement["options"] = options_by_requirement.get(
                requirement_row_id,
                [],
            )
            requirements.append(requirement)
        return requirements

    if connection is not None:
        return load(connection)
    with _existing_requirement_connection() as managed_connection:
        return load(managed_connection) if managed_connection is not None else None


def load_legacy_ingredients_from_sql(recipe_url, user_id=None, *, connection=None):
    requirements = load_recipe_ingredient_requirements(
        recipe_url,
        user_id,
        connection=connection,
    )
    if requirements is None:
        return None
    return legacy_ingredients_from_requirements(requirements)


def recipe_data_with_sql_requirements(recipe_url, recipe_data, user_id=None):
    """Return a copy using SQL ingredients when this recipe has been synced."""
    legacy_ingredients = load_legacy_ingredients_from_sql(recipe_url, user_id)
    if legacy_ingredients is None:
        return deepcopy(recipe_data) if isinstance(recipe_data, dict) else recipe_data
    result = deepcopy(recipe_data) if isinstance(recipe_data, dict) else {}
    result["ingredients"] = legacy_ingredients
    return result


def _read_output_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "recipe output is not a JSON object"
    return payload, ""


def _readonly_sync_exists(user_id, recipe_id):
    db_path = master_data.recipe_master_db_path()
    if not db_path.is_file():
        return False
    connection = None
    try:
        connection = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("recipe_ingredient_requirement_sync",),
        ).fetchone()
        if not table:
            return False
        row = connection.execute(
            """
            SELECT requirement_count
              FROM recipe_ingredient_requirement_sync
             WHERE user_id = ? AND recipe_id = ?
            """,
            (user_id, recipe_id),
        ).fetchone()
        if not row:
            return False
        integrity = connection.execute(
            """
            SELECT COUNT(*) AS requirement_count,
                   COALESCE(SUM(
                       CASE WHEN EXISTS (
                           SELECT 1
                             FROM recipe_ingredient_options option
                            WHERE option.requirement_id = requirement.id
                       ) THEN 0 ELSE 1 END
                   ), 0) AS requirements_without_options
              FROM recipe_ingredient_requirements requirement
             WHERE requirement.user_id = ? AND requirement.recipe_id = ?
            """,
            (user_id, recipe_id),
        ).fetchone()
        return bool(
            integrity
            and int(integrity["requirement_count"] or 0)
            == int(row["requirement_count"] or 0)
            and int(integrity["requirements_without_options"] or 0) == 0
        )
    except sqlite3.Error:
        return False
    finally:
        if connection is not None:
            connection.close()


def _default_data_root(user_id):
    if user_id == master_data.LOCAL_USER_ID:
        return storage_service.LEGACY_EXTRACTOR_DIR / "data"
    if user_id.startswith("guest:"):
        guest_id = storage_service.safe_user_id(user_id.split(":", 1)[1])
        return storage_service.GUEST_DATA_DIR / guest_id / "recipe-extractor" / "data"
    safe_user_id = storage_service.safe_user_id(user_id)
    return storage_service.USER_DATA_DIR / safe_user_id / "recipe-extractor" / "data"


def _backup_output_files(paths, data_root, run_stamp):
    backup_root = Path(data_root) / "requirement-migration-backups" / run_stamp
    backups = []
    for path in paths:
        backup_root.mkdir(parents=True, exist_ok=True)
        target = backup_root / Path(path).name
        shutil.copy2(path, target)
        backups.append(str(target))
    return backups


def _migration_summary(*, user_id, data_root, dry_run):
    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "user_id": user_id,
        "source_root": str(data_root),
        "recipes_scanned": 0,
        "requirements_inserted": 0,
        "options_inserted": 0,
        "option_items_inserted": 0,
        "malformed_records": 0,
        "skipped_records": 0,
        "backup_files": [],
        "issues": [],
    }


def backfill_recipe_ingredient_requirements_for_user(
    user_id,
    *,
    extractor_data_root=None,
    recipe_url=None,
    dry_run=True,
    force=False,
):
    """Dry-run or transactionally backfill one workspace from full output JSON."""
    user_id = master_data.scoped_recipe_user_id(user_id)
    data_root = Path(extractor_data_root or _default_data_root(user_id))
    output_root = data_root / "output"
    summary = _migration_summary(
        user_id=user_id,
        data_root=data_root,
        dry_run=dry_run,
    )
    wanted_recipe_id = master_data.recipe_id_for_url(recipe_url)
    candidates = []

    if not output_root.is_dir():
        summary["skipped_records"] = 1
        summary["issues"].append({
            "reason": "output directory does not exist",
            "path": str(output_root),
        })
        return summary

    for json_path in sorted(output_root.glob("*.json")):
        if json_path.name == "sorted_ingredients.json":
            continue
        payload, error = _read_output_json(json_path)
        if payload is None:
            if wanted_recipe_id:
                continue
            summary["recipes_scanned"] += 1
            summary["malformed_records"] += 1
            summary["skipped_records"] += 1
            summary["issues"].append({
                "path": str(json_path),
                "reason": error,
            })
            continue
        source_url = clean_text(payload.get("source_url"))
        recipe_id = master_data.recipe_id_for_url(source_url)
        if wanted_recipe_id and recipe_id != wanted_recipe_id:
            continue
        summary["recipes_scanned"] += 1
        if not source_url or not recipe_id:
            summary["malformed_records"] += 1
            summary["skipped_records"] += 1
            summary["issues"].append({
                "path": str(json_path),
                "reason": "recipe output has no valid source_url",
            })
            continue
        if not force and _readonly_sync_exists(user_id, recipe_id):
            summary["skipped_records"] += 1
            continue

        requirements, diagnostics = requirements_from_legacy_recipe(payload)
        summary["malformed_records"] += diagnostics["malformed_records"]
        summary["skipped_records"] += diagnostics["skipped_records"]
        for issue in diagnostics["issues"]:
            summary["issues"].append({"path": str(json_path), **issue})
        if diagnostics["skipped_records"]:
            summary["issues"].append({
                "path": str(json_path),
                "reason": (
                    "recipe was not migrated because at least one top-level "
                    "ingredient row could not be represented safely"
                ),
            })
            continue
        summary["requirements_inserted"] += len(requirements)
        summary["options_inserted"] += sum(
            len(requirement.get("options") or []) for requirement in requirements
        )
        summary["option_items_inserted"] += sum(
            len(option.get("items") or [])
            for requirement in requirements
            for option in (requirement.get("options") or [])
        )
        candidates.append((json_path, source_url, payload, requirements))

    if dry_run or not candidates:
        return summary

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    summary["backup_files"] = _backup_output_files(
        [candidate[0] for candidate in candidates],
        data_root,
        run_stamp,
    )
    started_at = _utc_now_iso()
    try:
        with master_data.recipe_master_connection(user_id=user_id) as connection:
            for _path, source_url, payload, requirements in candidates:
                _save_requirements_with_connection(
                    connection,
                    source_url,
                    payload,
                    requirements,
                    user_id=user_id,
                    sync_compatibility=True,
                )
            completed_at = _utc_now_iso()
            connection.execute(
                """
                INSERT INTO recipe_ingredient_requirement_migration_runs (
                    user_id, mode, source_root, status, summary_json,
                    started_at, completed_at
                )
                VALUES (?, 'apply', ?, 'complete', ?, ?, ?)
                """,
                (
                    user_id,
                    str(data_root),
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    started_at,
                    completed_at,
                ),
            )
    except Exception as exc:
        summary["ok"] = False
        summary["error"] = str(exc)
        try:
            with master_data.recipe_master_connection(user_id=user_id) as connection:
                connection.execute(
                    """
                    INSERT INTO recipe_ingredient_requirement_migration_runs (
                        user_id, mode, source_root, status, summary_json,
                        started_at, completed_at
                    )
                    VALUES (?, 'apply', ?, 'failed', ?, ?, ?)
                    """,
                    (
                        user_id,
                        str(data_root),
                        json.dumps(summary, ensure_ascii=False, sort_keys=True),
                        started_at,
                        _utc_now_iso(),
                    ),
                )
        except Exception:
            pass
        raise
    return summary


def iter_requirement_backfill_roots(include_legacy=True, include_guests=True):
    if include_legacy:
        legacy = storage_service.LEGACY_EXTRACTOR_DIR / "data"
        if legacy.is_dir():
            yield master_data.LOCAL_USER_ID, legacy
    if storage_service.USER_DATA_DIR.is_dir():
        for root in sorted(storage_service.USER_DATA_DIR.iterdir()):
            data_root = root / "recipe-extractor" / "data"
            if root.is_dir() and data_root.is_dir():
                yield root.name, data_root
    if include_guests and storage_service.GUEST_DATA_DIR.is_dir():
        for root in sorted(storage_service.GUEST_DATA_DIR.iterdir()):
            data_root = root / "recipe-extractor" / "data"
            if root.is_dir() and data_root.is_dir():
                yield f"guest:{root.name}", data_root


def backfill_all_recipe_ingredient_requirements(
    *,
    dry_run=True,
    force=False,
    include_legacy=True,
    include_guests=True,
):
    summaries = [
        backfill_recipe_ingredient_requirements_for_user(
            user_id,
            extractor_data_root=data_root,
            dry_run=dry_run,
            force=force,
        )
        for user_id, data_root in iter_requirement_backfill_roots(
            include_legacy=include_legacy,
            include_guests=include_guests,
        )
    ]
    return {
        "ok": all(summary.get("ok") for summary in summaries),
        "dry_run": bool(dry_run),
        "users": len(summaries),
        "recipes_scanned": sum(item["recipes_scanned"] for item in summaries),
        "requirements_inserted": sum(item["requirements_inserted"] for item in summaries),
        "options_inserted": sum(item["options_inserted"] for item in summaries),
        "option_items_inserted": sum(item["option_items_inserted"] for item in summaries),
        "malformed_records": sum(item["malformed_records"] for item in summaries),
        "skipped_records": sum(item["skipped_records"] for item in summaries),
        "summaries": summaries,
    }
