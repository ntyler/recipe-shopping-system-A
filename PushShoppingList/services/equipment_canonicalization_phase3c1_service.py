"""Approved Phase 3C-1 high-confidence equipment canonicalization.

This module is intentionally separate from application reads and writes.  It
only operates when called with the exact approval phrase, requires every
structured-equipment feature flag to be disabled, and validates the exact
Phase 3A/3B staging boundary before starting a transaction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services.equipment_migration_apply_service import (
    LEGACY_LINK_COLUMNS,
    _json_hash,
    _readonly_connection,
    _sha256_file,
    active_output_file_manifest,
    create_verified_backup,
    discover_output_roots,
    enabled_application_feature_flags,
)
from PushShoppingList.services.equipment_normalization_service import (
    normalized_equipment_key,
)


CLI_APPROVAL_PHRASE = "PHASE3C1_APPROVED"
MIGRATION_VERSION = "equipment-requirements-phase3c1-v1"

TENANT_U = "476262025aa2477a86c6efd66c77c8b0"
TENANT_P = "6700fb164ae645e29cc592cccc101bc7"
TENANT_LOCAL = "local"

EXPECTED = {
    "legacy_equipment_rows": 211,
    "requirements_before": 4385,
    "options_before": 4798,
    "ready_requirements_before": 1802,
    "pending_requirements_before": 2583,
    "ready_options_before": 1912,
    "pending_options_before": 2886,
    "high_options": 2751,
    "high_requirements": 2448,
    "new_equipment": 150,
    "reused_equipment": 6,
    "requirements_added": 9,
    "options_added": 11,
    "requirements_after": 4394,
    "options_after": 4809,
    "ready_requirements_after": 4259,
    "pending_requirements_after": 135,
    "ready_options_after": 4674,
    "pending_options_after": 135,
    "medium_requirements_after": 126,
    "individual_requirements_after": 9,
}

# These are the only pre-existing equipment rows Phase 3C-1 may reference.
VERIFIED_REUSE_TARGETS = {
    (TENANT_U, "pot"): 2485,
    (TENANT_LOCAL, "bowl"): 659,
    (TENANT_LOCAL, "measuring spoon"): 94,
    ("qa-editor", "chef s knife"): 6961,
    (TENANT_P, "bowl"): 2875,
    (TENANT_LOCAL, "shallow dish"): 1479,
}

STRUCTURAL_TARGETS = {
    (TENANT_U, "dutch oven"),
    (TENANT_U, "deep fryer"),
    (TENANT_U, "wok"),
}

MEDIUM_PENDING_MASTER = {
    *((TENANT_U, key) for key in (
        "chilled appetizer plates", "plastic cup", "plastic cups", "soup pot",
    )),
    *((TENANT_P, key) for key in (
        "baking dish", "cake pan", "cookie cutter", "heavy pot", "jar",
        "masher", "measuring cup", "pan", "pitcher", "saucepan", "skillet",
    )),
    (TENANT_LOCAL, "measuring spoon"),
}
INDIVIDUAL_PENDING_MASTER = {
    *((TENANT_U, key) for key in (
        "ice cream maker bowl", "lid", "loaf cutter", "rice paper sheets",
        "tea bag holder",
    )),
    (TENANT_LOCAL, "zsxdc"),
}
HIGH_PARSER_OPTIONS = {
    (TENANT_P, "bowl"),
    (TENANT_LOCAL, "bowl"),
    (TENANT_LOCAL, "shallow dishes"),
    (TENANT_LOCAL, "ice"),
}
MEDIUM_PARSER_OPTIONS = {
    (TENANT_LOCAL, "brush"),
    (TENANT_LOCAL, "glass"),
    (TENANT_LOCAL, "glasses"),
    (TENANT_LOCAL, "pan"),
}
INDIVIDUAL_PARSER_OPTIONS = {(TENANT_LOCAL, "lid")}

TARGET_KEY_OVERRIDES = {
    "16 ounce serving cup": "serving cup",
    "16 ounce serving glass": "serving glass",
    "2 large serving bowls": "serving bowl",
    "3 shallow bowls": "shallow bowl",
    "4 large ramen": "ramen bowl",
    "4 large ramen bowls": "ramen bowl",
    "4 large soup bowls": "soup bowl",
    "4 ramen bowls": "ramen bowl",
    "4 serving bowls": "serving bowl",
    "4 tall 16 ounce glasses": "serving glass",
    "4 tall beverage glasses": "serving glass",
    "4 tall glasses": "serving glass",
    "baking sheet lined": "baking sheet",
    "bamboo sushi rolling mat": "sushi mat",
    "bamboo sushi rolling sheet": "sushi mat",
    "bowl of ice water": "bowl",
    "bowl of water": "bowl",
    "bowls": "bowl",
    "cast iron skillet": "skillet",
    "clean kitchen towel": "kitchen towel",
    "cups": "measuring cup",
    "dry skillet": "skillet",
    "forks": "fork",
    "frying thermometer": "deep fry thermometer",
    "heavy frying pan": "frying pan",
    "heavy pot": "pot",
    "heavy pot dutch oven": "pot",
    "heavy saucepan": "saucepan",
    "heavy skillet": "skillet",
    "heavy skillet wok": "skillet",
    "instant read": "instant read thermometer",
    "knives": "knife",
    "mesh strainer": "fine mesh strainer",
    "microwave safe bowl": "bowl",
    "nonstick": "skillet",
    "nonstick skillet": "skillet",
    "paper towel lined plate": "plate",
    "paper towel lined tray": "tray",
    "plate lined": "plate",
    "plates": "plate",
    "pot if using dried noodles": "pot",
    "ramen bowls": "ramen bowl",
    "rolling mat": "sushi mat",
    "saută pan": "saute pan",
    "serving glasses": "serving glass",
    "shallow bowls": "shallow bowl",
    "shallow dishes": "shallow dish",
    "shallow saute pan": "saute pan",
    "soup bowls": "soup bowl",
    "spider": "spider strainer",
    "sushi rolling mat": "sushi mat",
    "thin spatula": "spatula",
    "two skewers": "skewer",
    "udon bowls": "udon bowl",
    "very sharp knife": "knife",
    "wide spatula": "spatula",
    "wire rack set over a sheet pan": "wire rack",
    "wok spatula": "wok turner",
}

TARGET_DISPLAY_NAMES = {
    "chef s knife": "Chef's knife",
    "deep fry thermometer": "Deep-fry thermometer",
    "fine mesh strainer": "Fine-mesh strainer",
    "instant read thermometer": "Instant-read thermometer",
    "ramen bowl": "Ramen bowl",
    "saute pan": "Sauté pan",
    "serving bowl": "Serving bowl",
    "serving cup": "Serving cup",
    "serving glass": "Serving glass",
    "shallow bowl": "Shallow bowl",
    "shallow dish": "Shallow dish",
    "soup bowl": "Soup bowl",
    "spider strainer": "Spider strainer",
    "sushi mat": "Sushi mat",
    "udon bowl": "Udon bowl",
    "wok turner": "Wok turner",
}

RECLASSIFICATIONS = {
    "baking paper": ("supply", "Parchment paper", "parchment paper"),
    "cheesecloth": ("supply", "Cheesecloth", "cheesecloth"),
    "coffee filter paper": ("supply", "Coffee filter paper", "coffee filter paper"),
    "foil": ("supply", "Aluminum foil", "aluminum foil"),
    "foil sheet": ("supply", "Aluminum foil", "aluminum foil"),
    "foil sheets": ("supply", "Aluminum foil", "aluminum foil"),
    "spice bag": ("supply", "Spice bag", "spice bag"),
    "tortilla wrap": ("ingredient", "Tortilla", "tortilla"),
    "burner": ("facility", "Stove", "stove"),
    "gas burner": ("facility", "Stove", "stove"),
    "open flame burner": ("facility", "Stove", "stove"),
    "stovetop": ("facility", "Stove", "stove"),
}

ATTRIBUTE_OVERRIDES = {
    "16 ounce serving cup": {"capacity": "16 ounces"},
    "16 ounce serving glass": {"capacity": "16 ounces"},
    "2 large serving bowls": {"quantity": 2, "size": "large"},
    "3 shallow bowls": {"quantity": 3, "purpose": "breading"},
    "4 large ramen": {"quantity": 4, "size": "large"},
    "4 large ramen bowls": {"quantity": 4, "size": "large"},
    "4 large soup bowls": {"quantity": 4, "size": "large"},
    "4 ramen bowls": {"quantity": 4},
    "4 serving bowls": {"quantity": 4},
    "4 tall 16 ounce glasses": {"quantity": 4, "shape": "tall", "capacity": "16 ounces"},
    "4 tall beverage glasses": {"quantity": 4, "shape": "tall"},
    "4 tall glasses": {"quantity": 4, "shape": "tall"},
    "baking sheet lined": {"lining": "parchment paper"},
    "bamboo sushi rolling mat": {"material": "bamboo"},
    "bamboo sushi rolling sheet": {"material": "bamboo"},
    "bowl of ice water": {"contents": "ice water"},
    "bowl of water": {"contents": "water"},
    "cast iron skillet": {"material": "cast iron"},
    "clean kitchen towel": {"condition": "clean"},
    "dry skillet": {"condition": "dry"},
    "heavy frying pan": {"quality": "heavy"},
    "heavy pot": {"quality": "heavy"},
    "heavy pot dutch oven": {"quality": "heavy"},
    "heavy saucepan": {"quality": "heavy"},
    "heavy skillet": {"quality": "heavy"},
    "heavy skillet wok": {"quality": "heavy"},
    "nonstick": {"coating": "nonstick"},
    "nonstick skillet": {"coating": "nonstick"},
    "paper towel lined plate": {"lining": "paper towels"},
    "paper towel lined tray": {"lining": "paper towels"},
    "plate lined": {"lining": "paper towels"},
    "pot if using dried noodles": {"condition": "if using dried noodles"},
    "thin spatula": {"shape": "thin"},
    "two skewers": {"quantity": 2},
    "very sharp knife": {"sharpness": "very sharp"},
    "wide spatula": {"shape": "wide"},
    "wire rack set over a sheet pan": {"placement": "set over a sheet pan"},
}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rows_hash(connection, sql, parameters=()):
    return _json_hash([list(row) for row in connection.execute(sql, parameters).fetchall()])


def _table_counts(connection):
    return {
        "equipment": int(connection.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]),
        "requirements": int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_requirements"
        ).fetchone()[0]),
        "options": int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_options"
        ).fetchone()[0]),
        "ready_requirements": int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE review_status = 'ready'"
        ).fetchone()[0]),
        "pending_requirements": int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE review_status = 'pending'"
        ).fetchone()[0]),
        "ready_options": int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_options WHERE review_status = 'ready'"
        ).fetchone()[0]),
        "pending_options": int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_options WHERE review_status <> 'ready'"
        ).fetchone()[0]),
        "pending_reviews": int(connection.execute(
            "SELECT COUNT(*) FROM equipment_normalization_reviews WHERE status = 'pending'"
        ).fetchone()[0]),
        "aliases": int(connection.execute("SELECT COUNT(*) FROM equipment_aliases").fetchone()[0]),
    }


def _baseline_equipment_rows(connection):
    columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(equipment)")]
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM equipment ORDER BY id"
    ).fetchall()
    return columns, {int(row[0]): list(row) for row in rows}


def _legacy_link_fingerprint(connection):
    return {
        "count": int(connection.execute("SELECT COUNT(*) FROM recipe_equipment").fetchone()[0]),
        "sha256": _rows_hash(
            connection,
            f"SELECT {', '.join(LEGACY_LINK_COLUMNS)} FROM recipe_equipment ORDER BY id",
        ),
    }


def _staged_fingerprint(connection):
    tables = (
        "equipment", "equipment_aliases", "recipe_equipment_requirements",
        "recipe_equipment_options", "equipment_normalization_reviews",
        "equipment_requirement_migration_runs", "equipment_requirement_migration_map",
        "recipe_equipment",
    )
    result = {}
    for table in tables:
        columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        result[table] = {
            "count": int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]),
            "sha256": _rows_hash(
                connection,
                f'SELECT {", ".join(columns)} FROM "{table}" ORDER BY id',
            ),
        }
    return result


def _phase3a_source_hash(connection):
    row = connection.execute(
        """
        SELECT source_hash
          FROM equipment_requirement_migration_runs
         WHERE mode = 'stage' AND status = 'complete'
         ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not row or not str(row[0] or ""):
        raise RuntimeError("A completed Phase 3A staging run is required.")
    return str(row[0])


def _completed_run(connection, run_key):
    row = connection.execute(
        """
        SELECT id, summary_json, completed_at
          FROM equipment_requirement_migration_runs
         WHERE run_key = ? AND status = 'complete'
        """,
        (run_key,),
    ).fetchone()
    if not row:
        return None
    summary = json.loads(row[1] or "{}")
    summary.update({
        "migration_run_id": int(row[0]),
        "completed_at": str(row[2] or ""),
        "idempotent_noop": True,
    })
    return summary


def _is_high_option(row):
    pair = (str(row["user_id"]), str(row["canonical_key"]))
    if row["review_status"] == "pending_master":
        return pair not in MEDIUM_PENDING_MASTER | INDIVIDUAL_PENDING_MASTER
    return row["review_status"] == "needs_review" and pair in HIGH_PARSER_OPTIONS


def _holdout_class(row):
    pair = (str(row["user_id"]), str(row["canonical_key"]))
    if pair in INDIVIDUAL_PENDING_MASTER | INDIVIDUAL_PARSER_OPTIONS:
        return "individual"
    if pair in MEDIUM_PENDING_MASTER | MEDIUM_PARSER_OPTIONS:
        return "medium"
    return ""


def _target_key(row):
    key = str(row["canonical_key"])
    if key == "spoons":
        if row["user_id"] == TENANT_U:
            return (
                "measuring spoon"
                if "measuring cups and spoons" in str(row["requirement_source"]).casefold()
                else "spoon"
            )
        return "measuring spoon"
    return TARGET_KEY_OVERRIDES.get(key, key)


def _reclassification(row):
    key = str(row["canonical_key"])
    if row["user_id"] == TENANT_LOCAL and key == "ice":
        return "ingredient", "Ice", "ice"
    if row["user_id"] == TENANT_U:
        return RECLASSIFICATIONS.get(key)
    return None


def _preferred_name(key, rows):
    if key in TARGET_DISPLAY_NAMES:
        return TARGET_DISPLAY_NAMES[key]
    candidates = Counter()
    for row in rows:
        name = str(row["canonical_name"] or "").strip()
        if normalized_equipment_key(name) == key:
            candidates[name] += 1
    if candidates:
        return sorted(candidates, key=lambda name: (-candidates[name], name.casefold(), name))[0]
    return " ".join(part.capitalize() if index == 0 else part for index, part in enumerate(key.split()))


def _infer_section(key):
    if any(token in key for token in (
        "bowl", "mixing glass", "mixing spoon", "whisk",
    )):
        return "MIXING BOWLS"
    if any(token in key for token in (
        "oven", "blender", "processor", "microwave", "cooker", "toaster",
        "ice cream maker", "deep fryer", "grill", "takoyaki maker",
    )):
        return "APPLIANCES"
    if any(token in key for token in (
        "pan", "pot", "skillet", "wok", "saucepan", "stockpot", "kettle",
        "steamer", "baking dish", "dutch oven",
    )):
        return "COOKWARE"
    if any(token in key for token in (
        "baking sheet", "wire rack", "muffin tin", "cake", "cookie scoop",
    )):
        return "BAKEWARE"
    if any(token in key for token in (
        "measuring", "thermometer", "timer", "scale",
    )):
        return "MEASURING"
    if any(token in key for token in (
        "serving", "plate", "dish", "tray", "jar", "bottle", "container",
        "pitcher", "jug", "teapot", "teacup", "mug", "tumbler", "glass",
    )):
        return "SERVING & STORAGE"
    if any(token in key for token in (
        "knife", "board", "strainer", "sieve", "colander", "spatula",
        "turner", "spoon", "fork", "tongs", "ladle", "peeler", "grater",
        "skewer", "mat", "brush", "scoop", "opener", "masher", "rack",
        "cutter", "rolling pin", "juicer", "squeezer", "mallet", "spinner",
    )):
        return "PREP TOOLS"
    return "MISC"


def _merge_attributes(row):
    try:
        value = json.loads(row["attributes_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        value = {}
    value = value if isinstance(value, dict) else {}
    value.update(ATTRIBUTE_OVERRIDES.get(str(row["canonical_key"]), {}))
    return value


def build_phase3c1_plan(connection):
    """Build and validate the exact approved plan without mutating the database."""
    counts = _table_counts(connection)
    expected_before = {
        "equipment": EXPECTED["legacy_equipment_rows"],
        "requirements": EXPECTED["requirements_before"],
        "options": EXPECTED["options_before"],
        "ready_requirements": EXPECTED["ready_requirements_before"],
        "pending_requirements": EXPECTED["pending_requirements_before"],
        "ready_options": EXPECTED["ready_options_before"],
        "pending_options": EXPECTED["pending_options_before"],
        "pending_reviews": EXPECTED["pending_requirements_before"],
    }
    mismatches = {
        key: {"expected": value, "actual": counts.get(key)}
        for key, value in expected_before.items() if counts.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"Phase 3C-1 staging boundary mismatch: {mismatches}")

    rows = connection.execute(
        """
        SELECT o.*, r.requirement_id AS logical_requirement_id,
               r.user_id AS requirement_user_id, r.recipe_id,
               r.source_text AS requirement_source, r.review_status AS requirement_status,
               r.optional, r.quantity AS requirement_quantity,
               r.sort_order AS requirement_sort_order,
               r.connector AS requirement_connector
          FROM recipe_equipment_options AS o
          JOIN recipe_equipment_requirements AS r ON r.id = o.requirement_id
         WHERE o.review_status <> 'ready'
         ORDER BY o.id
        """
    ).fetchall()
    high_rows = [row for row in rows if _is_high_option(row)]
    if len(high_rows) != EXPECTED["high_options"]:
        raise RuntimeError(
            f"Expected {EXPECTED['high_options']} high-confidence options; found {len(high_rows)}."
        )

    high_option_ids = {int(row["id"]) for row in high_rows}
    high_requirement_ids = set()
    for requirement_id in {int(row["requirement_id"]) for row in high_rows}:
        unresolved = connection.execute(
            "SELECT id FROM recipe_equipment_options WHERE requirement_id = ? AND review_status <> 'ready'",
            (requirement_id,),
        ).fetchall()
        if all(int(option[0]) in high_option_ids for option in unresolved):
            high_requirement_ids.add(requirement_id)
    if len(high_requirement_ids) != EXPECTED["high_requirements"]:
        raise RuntimeError(
            f"Expected {EXPECTED['high_requirements']} high-confidence requirements; "
            f"found {len(high_requirement_ids)}."
        )

    equipment_targets = defaultdict(list)
    reclassified = []
    for row in high_rows:
        classification = _reclassification(row)
        if classification:
            reclassified.append((row, classification))
        else:
            equipment_targets[(str(row["user_id"]), _target_key(row))].append(row)
    # The two approved malformed OR repairs add no new target beyond these keys,
    # but asserting them here documents their inclusion in the target universe.
    for target in STRUCTURAL_TARGETS:
        equipment_targets.setdefault(target, [])

    reused = set(equipment_targets) & set(VERIFIED_REUSE_TARGETS)
    new_targets = set(equipment_targets) - reused
    if len(reused) != EXPECTED["reused_equipment"] or reused != set(VERIFIED_REUSE_TARGETS):
        raise RuntimeError(f"Verified reuse target mismatch: {sorted(reused)}")
    if len(new_targets) != EXPECTED["new_equipment"]:
        raise RuntimeError(
            f"Expected {EXPECTED['new_equipment']} new canonical targets; found {len(new_targets)}."
        )

    holdout_requirements = defaultdict(set)
    for row in rows:
        holdout = _holdout_class(row)
        if holdout:
            holdout_requirements[holdout].add(int(row["requirement_id"]))
    if len(holdout_requirements["medium"]) != EXPECTED["medium_requirements_after"]:
        raise RuntimeError("The medium-confidence holdout boundary changed.")
    if len(holdout_requirements["individual"]) != EXPECTED["individual_requirements_after"]:
        raise RuntimeError("The individual-decision holdout boundary changed.")

    target_names = {
        target: _preferred_name(target[1], target_rows)
        for target, target_rows in equipment_targets.items()
    }
    return {
        "counts_before": counts,
        "high_rows": high_rows,
        "high_option_ids": high_option_ids,
        "high_requirement_ids": high_requirement_ids,
        "equipment_targets": dict(equipment_targets),
        "target_names": target_names,
        "new_targets": new_targets,
        "reused_targets": reused,
        "reclassified": reclassified,
        "holdout_requirements": dict(holdout_requirements),
    }


def _verify_reuse_targets(connection):
    found = {}
    for target, equipment_id in VERIFIED_REUSE_TARGETS.items():
        row = connection.execute(
            "SELECT id, user_id, name FROM equipment WHERE id = ? AND user_id = ?",
            (equipment_id, target[0]),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Verified same-tenant target is missing: {target} -> {equipment_id}")
        found[target] = int(row["id"])
    return found


def _insert_new_targets(connection, plan, now):
    target_ids = _verify_reuse_targets(connection)
    inserted_ids = []
    for user_id, key in sorted(plan["new_targets"]):
        name = plan["target_names"][(user_id, key)]
        collision = connection.execute(
            "SELECT id FROM equipment WHERE user_id = ? AND normalized_name = ?",
            (user_id, key),
        ).fetchone()
        if collision:
            raise RuntimeError(
                f"Unapproved existing target collision for {(user_id, key)}: {int(collision[0])}"
            )
        cursor = connection.execute(
            """
            INSERT INTO equipment (
                user_id, name, normalized_name, image_url, image_path,
                created_at, updated_at, equipment_section, display_name_override,
                canonical_name, canonical_key, description, status,
                image_provenance_json, merged_into_id
            ) VALUES (?, ?, ?, '', '', ?, ?, ?, '', ?, ?, '', 'active', ?, NULL)
            """,
            (
                user_id, name, key, now, now, _infer_section(key), name, key,
                _canonical_json({"copied": False, "source": "phase3c1_canonicalization"}),
            ),
        )
        equipment_id = int(cursor.lastrowid)
        target_ids[(user_id, key)] = equipment_id
        inserted_ids.append(equipment_id)
    if len(inserted_ids) != EXPECTED["new_equipment"]:
        raise RuntimeError("Canonical equipment insertion count mismatch.")
    return target_ids, inserted_ids


def _update_high_options(connection, plan, target_ids, now):
    before_after = []
    counts = Counter()
    for row in plan["high_rows"]:
        before = dict(row)
        classification = _reclassification(row)
        attributes = _merge_attributes(row)
        if classification:
            option_kind, canonical_name, canonical_key = classification
            equipment_id = None
            match_type = "phase3c1_reclassification"
            counts[f"{option_kind}_reclassifications"] += 1
        else:
            canonical_key = _target_key(row)
            canonical_name = plan["target_names"][(str(row["user_id"]), canonical_key)]
            equipment_id = target_ids[(str(row["user_id"]), canonical_key)]
            option_kind = "equipment"
            match_type = (
                "phase3c1_verified_same_tenant"
                if (str(row["user_id"]), canonical_key) in VERIFIED_REUSE_TARGETS
                else "phase3c1_canonical_created"
            )
            counts["equipment_options"] += 1
        connection.execute(
            """
            UPDATE recipe_equipment_options
               SET equipment_id = ?, canonical_name = ?, canonical_key = ?,
                   option_kind = ?, attributes_json = ?, matched_alias_id = NULL,
                   match_type = ?, match_confidence = 0.99,
                   review_status = 'ready', updated_at = ?
             WHERE id = ? AND review_status <> 'ready'
            """,
            (
                equipment_id, canonical_name, canonical_key, option_kind,
                _canonical_json(attributes), match_type, now, int(row["id"]),
            ),
        )
        quantity = attributes.get("quantity")
        if quantity and not str(row["requirement_quantity"] or ""):
            connection.execute(
                "UPDATE recipe_equipment_requirements SET quantity = ?, updated_at = ? WHERE id = ?",
                (str(quantity), now, int(row["requirement_id"])),
            )
        after = dict(connection.execute(
            "SELECT * FROM recipe_equipment_options WHERE id = ?", (int(row["id"]),)
        ).fetchone())
        before_after.append((row, before, after))
        counts["options_resolved"] += 1
    return before_after, counts


def _stable_id(prefix, *parts):
    payload = "\x1f".join(str(part) for part in parts)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _insert_derived_requirement(
    connection,
    source_requirement,
    *,
    option_kind,
    canonical_name,
    canonical_key,
    source_option_text,
    equipment_id,
    suffix,
    attributes,
    now,
):
    requirement_id = _stable_id(
        "eqr_", source_requirement["user_id"], source_requirement["recipe_id"],
        source_requirement["logical_requirement_id"], suffix,
    )
    option_id = _stable_id("eqo_", requirement_id, suffix)
    group = "phase3c1:" + str(source_requirement["logical_requirement_id"])
    connection.execute(
        """
        UPDATE recipe_equipment_requirements
           SET conjunction_group = ?, updated_at = ? WHERE id = ?
        """,
        (group, now, int(source_requirement["requirement_id"])),
    )
    cursor = connection.execute(
        """
        INSERT INTO recipe_equipment_requirements (
            requirement_id, user_id, recipe_id, source_text, optional, quantity,
            notes, sort_order, connector, conjunction_group, parse_confidence,
            review_status, parser_version, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '', '', ?, 'single', ?, 0.99, 'ready',
                  'phase3c1-approved', ?, ?, ?)
        """,
        (
            requirement_id, source_requirement["user_id"], source_requirement["recipe_id"],
            source_requirement["requirement_source"],
            int(source_requirement["optional"]), int(source_requirement["requirement_sort_order"]),
            group,
            _canonical_json({
                "derived_from_requirement_id": source_requirement["logical_requirement_id"],
                "semantics": "and", "source": "phase3c1_approved",
            }),
            now, now,
        ),
    )
    requirement_row_id = int(cursor.lastrowid)
    option_cursor = connection.execute(
        """
        INSERT INTO recipe_equipment_options (
            option_id, user_id, requirement_id, equipment_id, source_option_text,
            canonical_name, canonical_key, option_kind, attributes_json, notes,
            sort_order, matched_alias_id, match_type, match_confidence,
            review_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, NULL,
                  'phase3c1_derived_approved', 0.99, 'ready', ?, ?)
        """,
        (
            option_id, source_requirement["user_id"], requirement_row_id, equipment_id,
            source_option_text, canonical_name, canonical_key, option_kind,
            _canonical_json(attributes), now, now,
        ),
    )
    return requirement_row_id, int(option_cursor.lastrowid)


def _apply_structural_repairs(connection, plan, target_ids, now):
    added = []
    # Four compound items become Wire rack AND Baking sheet requirements.
    wire_rows = [
        row for row in plan["high_rows"]
        if row["canonical_key"] == "wire rack set over a sheet pan"
    ]
    if len(wire_rows) != 4:
        raise RuntimeError(f"Expected four wire-rack compound requirements; found {len(wire_rows)}.")
    for row in wire_rows:
        added.append(_insert_derived_requirement(
            connection, row, option_kind="equipment", canonical_name="Baking sheet",
            canonical_key="baking sheet", source_option_text="sheet pan",
            equipment_id=target_ids[(TENANT_U, "baking sheet")], suffix="sheet-pan",
            attributes={"relationship": "under wire rack"}, now=now,
        ))

    # Five lining supplies are explicit AND requirements while wording stays intact.
    lined_keys = {
        "baking sheet lined": ("Parchment paper", "parchment paper", "parchment paper"),
        "paper towel lined plate": ("Paper towels", "paper towels", "paper towels"),
        "paper towel lined tray": ("Paper towels", "paper towels", "paper towels"),
        "plate lined": ("Paper towels", "paper towels", "paper towels"),
    }
    lined_rows = [row for row in plan["high_rows"] if row["canonical_key"] in lined_keys]
    if len(lined_rows) != 5:
        raise RuntimeError(f"Expected five lining requirements; found {len(lined_rows)}.")
    for row in lined_rows:
        name, key, source_option_text = lined_keys[row["canonical_key"]]
        added.append(_insert_derived_requirement(
            connection, row, option_kind="supply", canonical_name=name,
            canonical_key=key, source_option_text=source_option_text,
            equipment_id=None, suffix="lining-supply",
            attributes={"purpose": "lining"}, now=now,
        ))

    # Repair the two malformed first OR options by adding the omitted middle option.
    split_specs = (
        ("heavy pot dutch oven", "Dutch oven", "dutch oven", "Dutch oven"),
        ("heavy skillet wok", "Wok", "wok", "wok"),
    )
    split_option_ids = []
    for source_key, name, key, source_text in split_specs:
        matches = [row for row in plan["high_rows"] if row["canonical_key"] == source_key]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one malformed OR option for {source_key}; found {len(matches)}.")
        row = matches[0]
        option_id = _stable_id("eqo_", row["logical_requirement_id"], source_key, key)
        cursor = connection.execute(
            """
            INSERT INTO recipe_equipment_options (
                option_id, user_id, requirement_id, equipment_id, source_option_text,
                canonical_name, canonical_key, option_kind, attributes_json, notes,
                sort_order, matched_alias_id, match_type, match_confidence,
                review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'equipment', '{}', '', 1, NULL,
                      'phase3c1_split_approved', 0.99, 'ready', ?, ?)
            """,
            (
                option_id, row["user_id"], int(row["requirement_id"]),
                target_ids[(str(row["user_id"]), key)], source_text, name, key, now, now,
            ),
        )
        split_option_ids.append(int(cursor.lastrowid))
        connection.execute(
            """
            UPDATE recipe_equipment_options
               SET sort_order = sort_order + 1, updated_at = ?
             WHERE requirement_id = ? AND id <> ? AND sort_order >= 1
            """,
            (now, int(row["requirement_id"]), int(cursor.lastrowid)),
        )
    if len(added) != EXPECTED["requirements_added"] or (
        len(added) + len(split_option_ids) != EXPECTED["options_added"]
    ):
        raise RuntimeError("Approved structural-addition count mismatch.")
    return added, split_option_ids


def _insert_deterministic_aliases(connection, plan, target_ids, now):
    alias_targets = defaultdict(set)
    alias_names = defaultdict(Counter)
    option_alias_keys = {}
    for row in plan["high_rows"]:
        if _reclassification(row):
            continue
        target = (str(row["user_id"]), _target_key(row))
        alias_name = str(row["source_option_text"] or "").strip()
        alias_key = normalized_equipment_key(alias_name)
        if not alias_key or alias_key == target[1]:
            continue
        alias_identity = (target[0], alias_key)
        alias_targets[alias_identity].add(target_ids[target])
        alias_names[alias_identity][alias_name] += 1
        option_alias_keys[int(row["id"])] = alias_identity

    alias_ids = {}
    ambiguous = []
    conflicts = []
    inserted = 0
    reused = 0
    for alias_identity in sorted(alias_targets):
        equipment_ids = alias_targets[alias_identity]
        if len(equipment_ids) != 1:
            ambiguous.append({
                "user_id": alias_identity[0], "alias_key": alias_identity[1],
                "equipment_ids": sorted(equipment_ids),
            })
            continue
        equipment_id = next(iter(equipment_ids))
        existing = connection.execute(
            "SELECT id, equipment_id FROM equipment_aliases WHERE user_id = ? AND alias_key = ?",
            alias_identity,
        ).fetchone()
        if existing:
            if int(existing["equipment_id"]) != equipment_id:
                conflicts.append({
                    "user_id": alias_identity[0], "alias_key": alias_identity[1],
                    "existing_equipment_id": int(existing["equipment_id"]),
                    "proposed_equipment_id": equipment_id,
                })
                continue
            alias_ids[alias_identity] = int(existing["id"])
            reused += 1
            continue
        names = alias_names[alias_identity]
        alias_name = sorted(names, key=lambda name: (-names[name], name.casefold(), name))[0]
        cursor = connection.execute(
            """
            INSERT INTO equipment_aliases (
                user_id, equipment_id, alias_name, alias_key, source, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'phase3c1_approved', 'active', ?, ?)
            """,
            (alias_identity[0], equipment_id, alias_name, alias_identity[1], now, now),
        )
        alias_ids[alias_identity] = int(cursor.lastrowid)
        inserted += 1

    for option_id, alias_identity in option_alias_keys.items():
        alias_id = alias_ids.get(alias_identity)
        if alias_id:
            connection.execute(
                "UPDATE recipe_equipment_options SET matched_alias_id = ?, updated_at = ? WHERE id = ?",
                (alias_id, now, option_id),
            )
    return {
        "inserted": inserted,
        "reused": reused,
        "ambiguous_omitted": ambiguous,
        "existing_conflicts_omitted": conflicts,
    }


def _finalize_requirement_reviews(connection, original_pending_ids, now):
    connection.execute(
        """
        UPDATE recipe_equipment_requirements
           SET review_status = CASE
                 WHEN EXISTS (
                     SELECT 1 FROM recipe_equipment_options o
                      WHERE o.requirement_id = recipe_equipment_requirements.id
                        AND o.review_status <> 'ready'
                 ) THEN 'pending' ELSE 'ready' END,
               updated_at = ?
        """,
        (now,),
    )
    resolved = [
        row for row in connection.execute(
            "SELECT id, user_id, recipe_id, requirement_id FROM recipe_equipment_requirements "
            "WHERE review_status = 'ready'"
        ).fetchall()
        if int(row["id"]) in original_pending_ids
    ]
    updated_reviews = 0
    for row in resolved:
        source_record_id = f"{row['recipe_id']}#{row['requirement_id']}"
        cursor = connection.execute(
            """
            UPDATE equipment_normalization_reviews
               SET status = 'resolved', decision = 'phase3c1_high_confidence',
                   decision_note = 'Approved Phase 3C-1 high-confidence matrix decision.',
                   updated_at = ?
             WHERE user_id = ? AND source_record_id = ? AND status = 'pending'
            """,
            (now, row["user_id"], source_record_id),
        )
        updated_reviews += cursor.rowcount
    if len(resolved) != EXPECTED["high_requirements"] or updated_reviews != len(resolved):
        raise RuntimeError(
            f"Resolved-review mismatch: requirements={len(resolved)}, reviews={updated_reviews}."
        )
    return len(resolved), updated_reviews


def _audit_options(connection, run_id, before_after, derived_ids, split_ids, now):
    rows = list(before_after)
    for option_id in [option_id for _, option_id in derived_ids] + list(split_ids):
        after = dict(connection.execute(
            """
            SELECT o.*, r.recipe_id, r.requirement_id AS logical_requirement_id
              FROM recipe_equipment_options o
              JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
             WHERE o.id = ?
            """,
            (option_id,),
        ).fetchone())
        rows.append((after, {}, after))
    for source, before, after in rows:
        connection.execute(
            """
            INSERT INTO equipment_requirement_migration_map (
                migration_run_id, user_id, recipe_id, legacy_recipe_equipment_id,
                legacy_equipment_id, requirement_id, option_id, decision,
                before_json, after_json, created_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, 'phase3c1_high_confidence', ?, ?, ?)
            """,
            (
                run_id, source["user_id"], source["recipe_id"],
                source["logical_requirement_id"], after["option_id"],
                _canonical_json(before), _canonical_json(after), now,
            ),
        )
    return len(rows)


def _pending_reconciliation(connection):
    rows = connection.execute(
        """
        SELECT o.*, r.id AS requirement_row_id
          FROM recipe_equipment_options o
          JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
         WHERE o.review_status <> 'ready'
        """
    ).fetchall()
    option_counts = Counter()
    requirement_ids = defaultdict(set)
    unexpected = []
    for row in rows:
        holdout = _holdout_class(row)
        if not holdout:
            unexpected.append(int(row["id"]))
            continue
        option_counts[holdout] += 1
        requirement_ids[holdout].add(int(row["requirement_row_id"]))
    return {
        "medium_options": option_counts["medium"],
        "individual_options": option_counts["individual"],
        "medium_requirements": len(requirement_ids["medium"]),
        "individual_requirements": len(requirement_ids["individual"]),
        "unexpected_option_ids": unexpected,
    }


def apply_phase3c1_canonicalization(
    repository_root,
    *,
    db_path=None,
    output_roots=None,
    backup_base=None,
    approval_phrase="",
):
    if str(approval_phrase or "") != CLI_APPROVAL_PHRASE:
        raise PermissionError(
            f"Phase 3C-1 requires approval_phrase={CLI_APPROVAL_PHRASE!r}."
        )
    enabled_flags = enabled_application_feature_flags()
    if enabled_flags:
        raise RuntimeError(
            "Phase 3C-1 requires every structured-equipment feature flag to remain disabled: "
            + ", ".join(enabled_flags)
        )

    repository_root = Path(repository_root).resolve()
    db_path = Path(db_path or (
        repository_root / "PushShoppingList" / "user_data" / "recipe_master.sqlite3"
    )).resolve()
    output_roots = (
        [Path(path).resolve() for path in output_roots]
        if output_roots is not None else discover_output_roots(repository_root)
    )
    backup_base = Path(backup_base or (
        repository_root / "PushShoppingList" / "user_data"
        / "equipment-requirement-canonicalization-backups"
    )).resolve()

    with _readonly_connection(db_path) as read_connection:
        phase3a_source_hash = _phase3a_source_hash(read_connection)
        run_key = f"{MIGRATION_VERSION}:{phase3a_source_hash}"
        existing = _completed_run(read_connection, run_key)
        if existing:
            return existing
        if not requirements.structured_equipment_schema_available(read_connection):
            raise RuntimeError("The additive Phase 3A structured-equipment schema is unavailable.")
        plan = build_phase3c1_plan(read_connection)
        staged_before = _staged_fingerprint(read_connection)
        equipment_columns, equipment_before = _baseline_equipment_rows(read_connection)
        links_before = _legacy_link_fingerprint(read_connection)

    database_sha_before = _sha256_file(db_path)
    outputs_before = active_output_file_manifest(repository_root, output_roots)
    backup = create_verified_backup(
        repository_root,
        db_path,
        output_roots,
        backup_base=backup_base,
    )
    # The backup must contain the complete staged state, not only valid legacy rows.
    with _readonly_connection(backup["database_backup_path"]) as backup_connection:
        backup_staged = _staged_fingerprint(backup_connection)
    if backup_staged != staged_before:
        raise RuntimeError("Pre-3C backup staged-data fingerprint mismatch; no changes were applied.")
    if _sha256_file(db_path) != database_sha_before:
        raise RuntimeError("Database changed during pre-3C backup; no changes were applied.")

    connection = sqlite3.connect(db_path, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    master_data.install_recipe_master_connection_guest_write_fences(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if _staged_fingerprint(connection) != staged_before:
            raise RuntimeError("Staged data changed after backup; Phase 3C-1 was rolled back.")
        # Rebuild the plan inside the locked transaction.
        plan = build_phase3c1_plan(connection)
        now = _utc_now_iso()
        cursor = connection.execute(
            """
            INSERT INTO equipment_requirement_migration_runs (
                run_key, mode, source_hash, status, summary_json, started_at
            ) VALUES (?, 'canonicalize_high', ?, 'running', '{}', ?)
            """,
            (run_key, phase3a_source_hash, now),
        )
        run_id = int(cursor.lastrowid)
        original_pending_ids = {
            int(row[0]) for row in connection.execute(
                "SELECT id FROM recipe_equipment_requirements WHERE review_status = 'pending'"
            ).fetchall()
        }
        target_ids, inserted_equipment_ids = _insert_new_targets(connection, plan, now)
        before_after, resolution_counts = _update_high_options(
            connection, plan, target_ids, now
        )
        derived_ids, split_ids = _apply_structural_repairs(
            connection, plan, target_ids, now
        )
        alias_summary = _insert_deterministic_aliases(connection, plan, target_ids, now)
        resolved_requirements, resolved_reviews = _finalize_requirement_reviews(
            connection, original_pending_ids, now
        )
        audit_rows = _audit_options(
            connection, run_id, before_after, derived_ids, split_ids, now
        )

        counts_after = _table_counts(connection)
        expected_after = {
            "equipment": EXPECTED["legacy_equipment_rows"] + EXPECTED["new_equipment"],
            "requirements": EXPECTED["requirements_after"],
            "options": EXPECTED["options_after"],
            "ready_requirements": EXPECTED["ready_requirements_after"],
            "pending_requirements": EXPECTED["pending_requirements_after"],
            "ready_options": EXPECTED["ready_options_after"],
            "pending_options": EXPECTED["pending_options_after"],
            "pending_reviews": EXPECTED["pending_requirements_after"],
        }
        if any(counts_after.get(key) != value for key, value in expected_after.items()):
            raise RuntimeError(
                f"Post-Phase-3C-1 count mismatch: expected={expected_after}, actual={counts_after}"
            )
        pending = _pending_reconciliation(connection)
        if pending != {
            "medium_options": 126,
            "individual_options": 9,
            "medium_requirements": 126,
            "individual_requirements": 9,
            "unexpected_option_ids": [],
        }:
            raise RuntimeError(f"Pending holdout reconciliation failed: {pending}")

        current_existing = {}
        for equipment_id in equipment_before:
            row = connection.execute(
                f"SELECT {', '.join(equipment_columns)} FROM equipment WHERE id = ?",
                (equipment_id,),
            ).fetchone()
            if row:
                current_existing[equipment_id] = list(row)
        legacy_equipment_unchanged = current_existing == equipment_before
        links_after = _legacy_link_fingerprint(connection)
        if not legacy_equipment_unchanged or links_after != links_before:
            raise RuntimeError("A legacy equipment row or recipe association changed; transaction rolled back.")
        new_image_values = connection.execute(
            f"SELECT COUNT(*) FROM equipment WHERE id IN ({','.join('?' for _ in inserted_equipment_ids)}) "
            "AND (image_url <> '' OR image_path <> '')",
            inserted_equipment_ids,
        ).fetchone()[0]
        if int(new_image_values) != 0:
            raise RuntimeError("A Phase 3C-1 canonical row received an image; transaction rolled back.")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"Foreign-key reconciliation failed: {len(foreign_keys)} rows")
        if enabled_application_feature_flags():
            raise RuntimeError("A structured-equipment feature flag became enabled; transaction rolled back.")

        summary = {
            "mode": "phase3c1_high_confidence_canonicalization",
            "migration_version": MIGRATION_VERSION,
            "run_key": run_key,
            "migration_run_id": run_id,
            "source_hash": phase3a_source_hash,
            "idempotent_noop": False,
            "backup": backup,
            "counts_before": plan["counts_before"],
            "counts_after": counts_after,
            "approved_scope": {
                "requirements_resolved": resolved_requirements,
                "options_resolved": resolution_counts["options_resolved"],
                "canonical_equipment_created": len(inserted_equipment_ids),
                "verified_same_tenant_targets_reused": len(plan["reused_targets"]),
                "requirements_added": len(derived_ids),
                "options_added": len(derived_ids) + len(split_ids),
                "supply_reclassifications": resolution_counts["supply_reclassifications"],
                "facility_reclassifications": resolution_counts["facility_reclassifications"],
                "ingredient_reclassifications": resolution_counts["ingredient_reclassifications"],
            },
            "aliases": alias_summary,
            "pending_holdouts": pending,
            "audit_rows": audit_rows,
            "reviews_resolved": resolved_reviews,
            "legacy_equipment_rows_preserved": len(equipment_before),
            "legacy_equipment_rows_unchanged": legacy_equipment_unchanged,
            "legacy_recipe_associations_before": links_before,
            "legacy_recipe_associations_after": links_after,
            "legacy_recipe_associations_unchanged": links_after == links_before,
            "images_copied_or_replaced": 0,
            "feature_flags_enabled": [],
            "application_reads_modified": False,
            "cutover_performed": False,
            "completed_at": _utc_now_iso(),
        }
        connection.execute(
            """
            UPDATE equipment_requirement_migration_runs
               SET status = 'complete', summary_json = ?, completed_at = ?
             WHERE id = ?
            """,
            (_canonical_json(summary), summary["completed_at"], run_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    with _readonly_connection(db_path) as verification:
        integrity = str(verification.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_rows = len(verification.execute("PRAGMA foreign_key_check").fetchall())
        final_counts = _table_counts(verification)
        _, final_equipment_rows = _baseline_equipment_rows(verification)
        preserved = {
            equipment_id: final_equipment_rows.get(equipment_id)
            for equipment_id in equipment_before
        } == equipment_before
        final_links = _legacy_link_fingerprint(verification)
    outputs_after = active_output_file_manifest(repository_root, output_roots)
    summary["post_commit"] = {
        "database_integrity_check": integrity,
        "foreign_key_violations": foreign_key_rows,
        "counts": final_counts,
        "legacy_equipment_rows_unchanged": preserved,
        "legacy_recipe_associations_unchanged": final_links == links_before,
        "recipe_output_files_unchanged": outputs_after == outputs_before,
        "feature_flags_enabled": enabled_application_feature_flags(),
    }
    if summary["post_commit"] != {
        "database_integrity_check": "ok",
        "foreign_key_violations": 0,
        "counts": summary["counts_after"],
        "legacy_equipment_rows_unchanged": True,
        "legacy_recipe_associations_unchanged": True,
        "recipe_output_files_unchanged": True,
        "feature_flags_enabled": [],
    }:
        raise RuntimeError(f"Post-commit reconciliation failed: {summary['post_commit']}")
    return summary
