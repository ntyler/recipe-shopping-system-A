"""Deterministic parsing for recipe equipment requirements.

The parser is intentionally conservative.  It preserves authored text, splits
only explicit connectors, resolves a small reviewed alias set, and sends
generic or otherwise uncertain values to review instead of fuzzy-merging them.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from copy import deepcopy


PARSER_VERSION = "equipment-requirements-v1"

TRUTHY_VALUES = {"1", "true", "yes", "y", "on"}

PROTECTED_AND_NAMES = {
    "mortar and pestle",
    "salt and pepper mill",
    "salt and pepper shaker",
}

ALIASES = {
    "baking tray": "Baking sheet",
    "sheet pan": "Baking sheet",
    "chopping board": "Cutting board",
    "fry pan": "Frying pan",
    "fryer": "Deep fryer",
    "bamboo mat": "Sushi mat",
    "bamboo sushi mat": "Sushi mat",
    "mixing bowls": "Mixing bowl",
    "serving bowls": "Serving bowl",
    "serving plates": "Serving plate",
    "soup ladle": "Ladle",
    "plate for serving": "Serving plate",
    "chef knife": "Chef's knife",
    "chef’s knife": "Chef's knife",
    "measuring cups": "Measuring cup",
    "measuring spoons": "Measuring spoon",
    "tablespoon": "Measuring spoon",
    "teaspoon": "Measuring spoon",
    "cocktail shaker": "Cocktail shaker",
    "shaker": "Cocktail shaker",
}

SUPPLY_NAMES = {
    "aluminum foil",
    "parchment paper",
    "paper towel",
    "paper towels",
    "plastic wrap",
    "straw",
    "tin foil",
}

FACILITY_NAMES = {
    "freezer",
    "soda fountain",
    "stove",
}

INGREDIENT_NAMES = {"ice", "water", "oil"}

GENERIC_REVIEW_NAMES = {
    "bowl",
    "brush",
    "dish",
    "dishes",
    "glass",
    "glasses",
    "large bowl",
    "large glass",
    "lid",
    "pan",
    "shallow dishes",
}

ATTRIBUTE_PATTERNS = (
    ("size", re.compile(r"^(extra[- ]large|large|medium|small)\s+", re.I)),
    ("size", re.compile(r"^(\d+(?:\.\d+)?(?:[- ]inch|\s*inches?|\s*in\.?))\s+", re.I)),
    ("shape", re.compile(r"^(round|square|rectangular|oval)\s+", re.I)),
    ("coating", re.compile(r"^(non[- ]stick)\s+", re.I)),
    ("quality", re.compile(r"^(fine|sharp|heatproof|freezer[- ]safe|deep)\s+", re.I)),
    ("rimmed", re.compile(r"^(rimmed)\s+", re.I)),
)


def clean_text(value):
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).strip(),
    )


def normalized_equipment_key(value):
    text = clean_text(value).casefold()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return clean_text(value).casefold() in TRUTHY_VALUES


def equipment_source_text(item):
    if isinstance(item, dict):
        for field in (
            "original_recipe_text",
            "original_text",
            "source_text",
            "equipment",
            "name",
            "text",
            "item",
        ):
            value = clean_text(item.get(field))
            if value:
                return value
        return ""
    return clean_text(item)


def instruction_texts(instructions):
    values = []
    for item in instructions if isinstance(instructions, list) else []:
        if isinstance(item, dict):
            value = clean_text(item.get("instruction") or item.get("text"))
        else:
            value = clean_text(item)
        if value:
            values.append(value)
    return values


def _stable_id(prefix, *parts):
    value = "|".join(clean_text(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def _canonical_display(value):
    value = clean_text(value)
    key = normalized_equipment_key(value)
    if key in ALIASES:
        return ALIASES[key], "alias"
    if not value:
        return "", "unresolved"
    return value[0].upper() + value[1:], "exact"


def _extract_option_details(value):
    original = clean_text(value)
    working = original
    attributes = {}
    notes = []

    parenthetical = re.search(r"\s*\(([^()]*)\)\s*$", working)
    if parenthetical:
        note = clean_text(parenthetical.group(1))
        if note:
            notes.append(note)
        working = working[: parenthetical.start()].strip()

    purpose = re.search(r"\s+for\s+(.+)$", working, flags=re.I)
    if purpose:
        notes.append(f"for {clean_text(purpose.group(1))}")
        working = working[: purpose.start()].strip()

    with_detail = re.search(r"\s+with\s+(.+)$", working, flags=re.I)
    if with_detail:
        detail = clean_text(with_detail.group(1))
        if normalized_equipment_key(detail) == "lid":
            attributes["includes_lid"] = True
        else:
            notes.append(f"with {detail}")
        working = working[: with_detail.start()].strip()

    changed = True
    while changed and working:
        changed = False
        for attribute, pattern in ATTRIBUTE_PATTERNS:
            match = pattern.search(working)
            if not match:
                continue
            value = clean_text(match.group(1)).casefold()
            if attribute == "rimmed":
                attributes["rimmed"] = True
            elif attribute == "quality" and value == "freezer-safe":
                attributes["freezer_safe"] = True
            else:
                attributes[attribute] = value
            working = working[match.end():].strip()
            changed = True
            break

    canonical_name, match_type = _canonical_display(working or original)
    canonical_key = normalized_equipment_key(canonical_name)
    if canonical_key in SUPPLY_NAMES:
        option_kind = "supply"
    elif canonical_key in FACILITY_NAMES:
        option_kind = "facility"
    elif canonical_key in INGREDIENT_NAMES:
        option_kind = "ingredient"
    elif canonical_key:
        option_kind = "equipment"
    else:
        option_kind = "unresolved"

    needs_review = (
        normalized_equipment_key(original) in GENERIC_REVIEW_NAMES
        or canonical_key in GENERIC_REVIEW_NAMES
        or option_kind in {"ingredient", "unresolved"}
    )
    confidence = 0.98 if match_type == "alias" else 0.95
    if attributes or notes:
        confidence = min(confidence, 0.9)
    if needs_review:
        confidence = min(confidence, 0.55)

    return {
        "source_option_text": original,
        "canonical_name": canonical_name,
        "canonical_key": canonical_key,
        "option_kind": option_kind,
        "attributes": attributes,
        "notes": "; ".join(notes),
        "match_type": match_type,
        "match_confidence": confidence,
        "review_status": "needs_review" if needs_review else "ready",
    }


def _split_source(source_text, connector):
    protected_key = normalized_equipment_key(source_text)
    if connector == "and" and protected_key in PROTECTED_AND_NAMES:
        return [source_text]
    return [
        clean_text(value)
        for value in re.split(rf"\s+{connector}\s+", source_text, flags=re.I)
        if clean_text(value)
    ]


def _context_corrected_connector(source_text, instructions):
    source_key = normalized_equipment_key(source_text)
    if source_key != "blender and food processor":
        return ""
    for instruction in instruction_texts(instructions):
        if "blender or food processor" in normalized_equipment_key(instruction):
            return "or"
    return ""


def parse_equipment_item(item, *, instructions=None, sort_order=0):
    """Return one or more structured requirements for one compatibility row."""
    source_text = equipment_source_text(item)
    if not source_text:
        return []
    record = item if isinstance(item, dict) else {}
    optional = truthy(record.get("optional")) or bool(
        re.search(r"(?:^|\s)[\[(]?optional[\])]?\s*$", source_text, flags=re.I)
    )
    parse_text = re.sub(
        r"(?:^|\s)[\[(]?optional[\])]?\s*$",
        "",
        source_text,
        flags=re.I,
    ).strip()

    corrected_connector = _context_corrected_connector(parse_text, instructions)
    if re.search(r"\s+or\s+", parse_text, flags=re.I) or corrected_connector == "or":
        connector = "or"
        split_text = re.sub(r"\s+and\s+", " or ", parse_text, count=1, flags=re.I) if corrected_connector else parse_text
        parts = _split_source(split_text, "or")
    elif re.search(r"\s+and\s+", parse_text, flags=re.I) and normalized_equipment_key(parse_text) not in PROTECTED_AND_NAMES:
        connector = "and"
        parts = _split_source(parse_text, "and")
    else:
        connector = "single"
        parts = [parse_text]

    parsed_options = [_extract_option_details(part) for part in parts]
    parsed_options = [option for option in parsed_options if option["canonical_key"]]
    if not parsed_options:
        parsed_options = [_extract_option_details(parse_text)]

    # Alias-equivalent alternatives describe one canonical item, not a choice.
    if connector == "or" and len({option["canonical_key"] for option in parsed_options}) == 1:
        parsed_options = [max(parsed_options, key=lambda option: option["match_confidence"])]
        connector = "single"

    source_metadata = {
        key: deepcopy(value)
        for key, value in record.items()
        if key in {
            "equipment_image_url",
            "equipment_image_path",
            "equipment_image_generated_at",
            "equipment_image_prompt",
            "image_url",
            "image_path",
        } and value not in (None, "")
    }

    groups = [[option] for option in parsed_options] if connector == "and" else [parsed_options]
    requirements = []
    for group_index, options in enumerate(groups):
        requirement_id = _stable_id(
            "eqr",
            source_text,
            str(sort_order),
            str(group_index),
        )
        normalized_options = []
        for option_index, option in enumerate(options):
            normalized_options.append({
                **option,
                "option_id": _stable_id(
                    "eqo",
                    requirement_id,
                    option["source_option_text"],
                    str(option_index),
                ),
                "sort_order": option_index,
            })

        confidence = min(option["match_confidence"] for option in normalized_options)
        if connector in {"or", "and"}:
            confidence = min(confidence, 0.92)
        review_status = (
            "needs_review"
            if any(option["review_status"] == "needs_review" for option in normalized_options)
            else "ready"
        )
        requirements.append({
            "requirement_id": requirement_id,
            "source_text": source_text,
            "optional": optional,
            "quantity": clean_text(record.get("quantity")),
            "notes": "",
            "sort_order": sort_order + group_index,
            "connector": connector,
            "conjunction_group": _stable_id("eqg", source_text, str(sort_order)) if connector == "and" else "",
            "parse_confidence": confidence,
            "review_status": review_status,
            "parser_version": PARSER_VERSION,
            "source_metadata": source_metadata,
            "options": normalized_options,
        })
    return requirements


def parse_equipment_list(value, *, instructions=None):
    if isinstance(value, str):
        value = [line for line in value.splitlines() if clean_text(line)]
    if not isinstance(value, list):
        return []
    requirements = []
    for index, item in enumerate(value):
        requirements.extend(
            parse_equipment_item(item, instructions=instructions, sort_order=index)
        )
    for index, requirement in enumerate(requirements):
        requirement["sort_order"] = index
    return requirements


def requirement_summary(requirements):
    requirements = requirements if isinstance(requirements, list) else []
    options = [
        option
        for requirement in requirements
        if isinstance(requirement, dict)
        for option in requirement.get("options", [])
        if isinstance(option, dict)
    ]
    return {
        "requirement_count": len(requirements),
        "option_count": len(options),
        "alternative_requirement_count": sum(
            1 for requirement in requirements if requirement.get("connector") == "or"
        ),
        "conjoined_requirement_count": sum(
            1 for requirement in requirements if requirement.get("connector") == "and"
        ),
        "review_requirement_count": sum(
            1 for requirement in requirements if requirement.get("review_status") == "needs_review"
        ),
        "supply_option_count": sum(1 for option in options if option.get("option_kind") == "supply"),
        "facility_option_count": sum(1 for option in options if option.get("option_kind") == "facility"),
        "ingredient_option_count": sum(1 for option in options if option.get("option_kind") == "ingredient"),
    }
