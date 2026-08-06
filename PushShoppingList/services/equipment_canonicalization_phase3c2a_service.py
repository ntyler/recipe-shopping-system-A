"""Approved Phase 3C-2A automatic equipment canonicalization batch.

This migration-only module applies exactly the 124 decisions approved from the
Phase 3C-2 report.  It is deliberately disconnected from application reads and
writes, requires an exact approval phrase, verifies a fresh backup, and keeps
the eleven owner-decision requirements untouched.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services.equipment_canonicalization_phase3c1_service import (
    _baseline_equipment_rows,
    _canonical_json,
    _infer_section,
    _legacy_link_fingerprint,
    _phase3a_source_hash,
    _staged_fingerprint,
    _table_counts,
    _utc_now_iso,
)
from PushShoppingList.services.equipment_migration_apply_service import (
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


CLI_APPROVAL_PHRASE = "PHASE3C2A_APPROVED"
MIGRATION_VERSION = "equipment-requirements-phase3c2a-v1"

TENANT_U = "476262025aa2477a86c6efd66c77c8b0"
TENANT_P = "6700fb164ae645e29cc592cccc101bc7"
TENANT_LOCAL = "local"

EXPECTED = {
    "equipment_before": 361,
    "aliases_before": 182,
    "requirements_before": 4394,
    "options_before": 4809,
    "ready_requirements_before": 4259,
    "pending_requirements_before": 135,
    "ready_options_before": 4674,
    "pending_options_before": 135,
    "pending_reviews_before": 135,
    "automatic_requirements": 124,
    "automatic_options": 124,
    "holdout_requirements": 11,
    "holdout_options": 11,
    "new_equipment": 7,
    "reused_equipment": 11,
    "aliases_inserted": 26,
    "attributes_enhanced": 22,
    "equipment_after": 368,
    "aliases_after": 208,
    "requirements_after": 4394,
    "options_after": 4809,
    "ready_requirements_after": 4383,
    "pending_requirements_after": 11,
    "ready_options_after": 4798,
    "pending_options_after": 11,
    "pending_reviews_after": 11,
}

# Hashes are over sorted [logical requirement id, logical option id] pairs from
# the approved Phase 3C-2 report.  They make identifier drift a hard stop even
# when aggregate counts still happen to match.
EXPECTED_AUTOMATIC_IDENTIFIER_SHA256 = (
    "44DB81058B56EC2155FACD57FFED479D234AAA12B91E5B5AB2D2AB8762CE624D"
)
EXPECTED_HOLDOUT_IDENTIFIER_SHA256 = (
    "FB34E8F342567FFAA22E5F7C33EC828DF82AF7CB9E90E0E65ADA0C8DAA1B4085"
)


@dataclass(frozen=True)
class TargetSpec:
    user_id: str
    canonical_key: str
    canonical_name: str
    equipment_id: int | None = None


TARGET_SPECS = {
    (TENANT_U, "chilled appetizer plates"): TargetSpec(
        TENANT_U, "serving plate", "Serving plate", 8147
    ),
    (TENANT_U, "plastic cup"): TargetSpec(
        TENANT_U, "serving cup", "Serving cup", 8144
    ),
    (TENANT_U, "plastic cups"): TargetSpec(
        TENANT_U, "serving cup", "Serving cup", 8144
    ),
    (TENANT_U, "soup pot"): TargetSpec(
        TENANT_U, "stockpot", "Stockpot", 8164
    ),
    (TENANT_P, "baking dish"): TargetSpec(
        TENANT_P, "baking dish", "Baking dish", 3033
    ),
    (TENANT_P, "cake pan"): TargetSpec(TENANT_P, "cake pan", "Cake pan"),
    (TENANT_P, "cookie cutter"): TargetSpec(
        TENANT_P, "cookie cutter", "Cookie cutter"
    ),
    (TENANT_P, "heavy pot"): TargetSpec(TENANT_P, "pot", "Pot", 2606),
    (TENANT_P, "jar"): TargetSpec(TENANT_P, "jar", "Jar"),
    (TENANT_P, "masher"): TargetSpec(
        TENANT_P, "potato masher", "Potato masher", 8201
    ),
    (TENANT_P, "measuring cup"): TargetSpec(
        TENANT_P, "measuring cup", "Measuring cup", 3013
    ),
    (TENANT_P, "pan"): TargetSpec(TENANT_P, "frying pan", "Frying pan", 4),
    (TENANT_P, "pitcher"): TargetSpec(TENANT_P, "pitcher", "Pitcher", 2965),
    (TENANT_P, "saucepan"): TargetSpec(TENANT_P, "saucepan", "Saucepan"),
    (TENANT_P, "skillet"): TargetSpec(TENANT_P, "skillet", "Skillet"),
    (TENANT_LOCAL, "brush"): TargetSpec(
        TENANT_LOCAL, "pastry brush", "Pastry brush"
    ),
    (TENANT_LOCAL, "glass"): TargetSpec(
        TENANT_LOCAL, "drinking glass", "Drinking glass"
    ),
    (TENANT_LOCAL, "glasses"): TargetSpec(
        TENANT_LOCAL, "drinking glass", "Drinking glass"
    ),
    (TENANT_LOCAL, "pan"): TargetSpec(TENANT_LOCAL, "pan", "Pan", 655),
    (TENANT_LOCAL, "measuring spoon"): TargetSpec(
        TENANT_LOCAL, "measuring spoon", "Measuring spoon", 94
    ),
}

EXPECTED_REUSE_NORMALIZED_NAMES = {
    8147: "serving plate",
    8144: "serving cup",
    8164: "stockpot",
    3033: "9-inch round baking dish",
    2606: "pot",
    8201: "potato masher",
    3013: "measuring cups",
    4: "frying pan",
    2965: "large pitcher",
    94: "measuring spoons",
    655: "pan",
}

ATTRIBUTE_OVERRIDES_BY_PENDING_KEY = {
    (TENANT_U, "chilled appetizer plates"): {
        "temperature": "chilled", "purpose": "appetizer",
    },
    (TENANT_U, "plastic cup"): {"material": "plastic"},
    (TENANT_U, "plastic cups"): {"material": "plastic"},
    (TENANT_U, "soup pot"): {"purpose": "soup/broth"},
    (TENANT_P, "cookie cutter"): {"shape": "round", "diameter": "~3 in"},
    (TENANT_P, "heavy pot"): {"quality": "heavy"},
    (TENANT_LOCAL, "brush"): {"purpose": "apply oil"},
    (TENANT_LOCAL, "glass"): {"vessel_type": "drinking"},
    (TENANT_LOCAL, "glasses"): {"vessel_type": "drinking"},
}


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
    summary = json.loads(row["summary_json"] or "{}")
    summary.update({
        "migration_run_id": int(row["id"]),
        "completed_at": str(row["completed_at"] or ""),
        "idempotent_noop": True,
    })
    return summary


def _phase3c1_completed(connection):
    row = connection.execute(
        """
        SELECT id, run_key
          FROM equipment_requirement_migration_runs
         WHERE mode = 'canonicalize_high' AND status = 'complete'
         ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        raise RuntimeError("A completed Phase 3C-1 run is required.")
    return {"id": int(row["id"]), "run_key": str(row["run_key"])}


def _is_approved_row(row):
    pair = (str(row["user_id"]), str(row["canonical_key"]))
    if pair not in TARGET_SPECS:
        return False
    if pair == (TENANT_LOCAL, "measuring spoon"):
        return str(row["source_option_text"] or "").strip().casefold() == "measuring spoons"
    return True


def _pending_rows(connection):
    return connection.execute(
        """
        SELECT o.*, r.requirement_id AS logical_requirement_id,
               r.user_id AS requirement_user_id, r.recipe_id,
               r.source_text AS requirement_source,
               r.connector AS requirement_connector,
               r.conjunction_group AS requirement_conjunction_group,
               r.review_status AS requirement_status
          FROM recipe_equipment_options AS o
          JOIN recipe_equipment_requirements AS r ON r.id = o.requirement_id
         WHERE r.review_status = 'pending' AND o.review_status <> 'ready'
         ORDER BY r.id, o.id
        """
    ).fetchall()


def _identifier_hash(rows):
    return _json_hash([
        [str(row["logical_requirement_id"]), str(row["option_id"])]
        for row in rows
    ])


def _parse_attributes(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _alias_plan(rows):
    targets = defaultdict(set)
    names = defaultdict(Counter)
    option_aliases = {}
    for row in rows:
        spec = TARGET_SPECS[(str(row["user_id"]), str(row["canonical_key"]))]
        alias_name = str(row["source_option_text"] or "").strip()
        alias_key = normalized_equipment_key(alias_name)
        if not alias_key or alias_key == spec.canonical_key:
            continue
        identity = (spec.user_id, alias_key)
        target_identity = (spec.user_id, spec.canonical_key)
        targets[identity].add(target_identity)
        names[identity][alias_name] += 1
        option_aliases[int(row["id"])] = identity
    ambiguous = {
        identity: sorted(values) for identity, values in targets.items() if len(values) != 1
    }
    if ambiguous:
        raise RuntimeError(f"Ambiguous Phase 3C-2A aliases: {ambiguous}")
    aliases = {}
    for identity, values in targets.items():
        candidates = names[identity]
        aliases[identity] = {
            "target_identity": next(iter(values)),
            "alias_name": sorted(
                candidates,
                key=lambda name: (-candidates[name], name.casefold(), name),
            )[0],
        }
    return aliases, option_aliases


def _holdout_fingerprint(connection, rows):
    requirement_ids = sorted({int(row["requirement_id"]) for row in rows})
    option_ids = sorted(int(row["id"]) for row in rows)
    source_ids = sorted(
        f"{row['recipe_id']}#{row['logical_requirement_id']}" for row in rows
    )

    def selected(table, ids, column="id"):
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        columns = [str(item[1]) for item in connection.execute(f"PRAGMA table_info({table})")]
        return [list(row) for row in connection.execute(
            f"SELECT {', '.join(columns)} FROM {table} "
            f"WHERE {column} IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()]

    return {
        "requirements": _json_hash(selected(
            "recipe_equipment_requirements", requirement_ids
        )),
        "options": _json_hash(selected("recipe_equipment_options", option_ids)),
        "reviews": _json_hash(selected(
            "equipment_normalization_reviews", source_ids, "source_record_id"
        )),
    }


def build_phase3c2a_plan(connection):
    """Build and validate the exact approved plan without mutating the database."""
    counts = _table_counts(connection)
    expected_before = {
        "equipment": EXPECTED["equipment_before"],
        "aliases": EXPECTED["aliases_before"],
        "requirements": EXPECTED["requirements_before"],
        "options": EXPECTED["options_before"],
        "ready_requirements": EXPECTED["ready_requirements_before"],
        "pending_requirements": EXPECTED["pending_requirements_before"],
        "ready_options": EXPECTED["ready_options_before"],
        "pending_options": EXPECTED["pending_options_before"],
        "pending_reviews": EXPECTED["pending_reviews_before"],
    }
    mismatches = {
        key: {"expected": value, "actual": counts.get(key)}
        for key, value in expected_before.items() if counts.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"Phase 3C-2A preflight count drift: {mismatches}")

    _phase3c1_completed(connection)
    rows = _pending_rows(connection)
    if any(str(row["user_id"]) != str(row["requirement_user_id"]) for row in rows):
        raise RuntimeError("A pending option crosses its requirement tenant boundary.")
    automatic_rows = [row for row in rows if _is_approved_row(row)]
    holdout_rows = [row for row in rows if not _is_approved_row(row)]
    automatic_requirement_ids = {int(row["requirement_id"]) for row in automatic_rows}
    holdout_requirement_ids = {int(row["requirement_id"]) for row in holdout_rows}
    if len(automatic_rows) != EXPECTED["automatic_options"] or (
        len(automatic_requirement_ids) != EXPECTED["automatic_requirements"]
    ):
        raise RuntimeError("The approved 124-row automatic boundary changed.")
    if len(holdout_rows) != EXPECTED["holdout_options"] or (
        len(holdout_requirement_ids) != EXPECTED["holdout_requirements"]
    ):
        raise RuntimeError("The eleven-row individual-decision boundary changed.")
    if automatic_requirement_ids & holdout_requirement_ids:
        raise RuntimeError("An approved requirement also contains an unapproved option.")
    if _identifier_hash(automatic_rows) != EXPECTED_AUTOMATIC_IDENTIFIER_SHA256:
        raise RuntimeError("Approved Phase 3C-2A identifiers drifted from the decision report.")
    if _identifier_hash(holdout_rows) != EXPECTED_HOLDOUT_IDENTIFIER_SHA256:
        raise RuntimeError("Individual-decision identifiers drifted from the decision report.")

    target_specs = {
        (spec.user_id, spec.canonical_key): spec
        for row in automatic_rows
        for spec in [TARGET_SPECS[(str(row["user_id"]), str(row["canonical_key"]))]]
    }
    reused = {identity: spec for identity, spec in target_specs.items() if spec.equipment_id}
    new = {identity: spec for identity, spec in target_specs.items() if not spec.equipment_id}
    if len(reused) != EXPECTED["reused_equipment"] or len(new) != EXPECTED["new_equipment"]:
        raise RuntimeError("The approved target boundary changed.")

    aliases, option_aliases = _alias_plan(automatic_rows)
    if len(aliases) != EXPECTED["aliases_inserted"]:
        raise RuntimeError(
            f"Expected {EXPECTED['aliases_inserted']} deterministic aliases; found {len(aliases)}."
        )
    enhanced = sum(
        bool(ATTRIBUTE_OVERRIDES_BY_PENDING_KEY.get(
            (str(row["user_id"]), str(row["canonical_key"]))
        ))
        for row in automatic_rows
    )
    if enhanced != EXPECTED["attributes_enhanced"]:
        raise RuntimeError(f"Expected 22 attribute enhancements; found {enhanced}.")

    return {
        "counts_before": counts,
        "automatic_rows": automatic_rows,
        "holdout_rows": holdout_rows,
        "target_specs": target_specs,
        "reused_targets": reused,
        "new_targets": new,
        "aliases": aliases,
        "option_aliases": option_aliases,
        "automatic_identifier_sha256": _identifier_hash(automatic_rows),
        "holdout_identifier_sha256": _identifier_hash(holdout_rows),
    }


def _verify_and_create_targets(connection, plan, now):
    target_ids = {}
    inserted = []
    for identity, spec in sorted(plan["reused_targets"].items()):
        row = connection.execute(
            """
            SELECT id, user_id, normalized_name, status, merged_into_id
              FROM equipment WHERE id = ?
            """,
            (spec.equipment_id,),
        ).fetchone()
        expected_name = EXPECTED_REUSE_NORMALIZED_NAMES.get(spec.equipment_id)
        if not row or str(row["user_id"]) != spec.user_id or (
            str(row["normalized_name"]) != expected_name
        ) or str(row["status"]) != "active" or row["merged_into_id"] is not None:
            raise RuntimeError(f"Verified same-tenant target changed: {identity}")
        target_ids[identity] = int(row["id"])

    for identity, spec in sorted(plan["new_targets"].items()):
        if normalized_equipment_key(spec.canonical_name) != spec.canonical_key:
            raise RuntimeError(f"Invalid canonical target specification: {identity}")
        collision = connection.execute(
            """
            SELECT id FROM equipment
             WHERE user_id = ? AND (normalized_name = ? OR canonical_key = ?)
            """,
            (spec.user_id, spec.canonical_key, spec.canonical_key),
        ).fetchone()
        if collision:
            raise RuntimeError(f"Unapproved canonical collision for {identity}: {int(collision[0])}")
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
                spec.user_id, spec.canonical_name, spec.canonical_key, now, now,
                _infer_section(spec.canonical_key), spec.canonical_name,
                spec.canonical_key,
                _canonical_json({"copied": False, "source": "phase3c2a_automatic"}),
            ),
        )
        target_ids[identity] = int(cursor.lastrowid)
        inserted.append(int(cursor.lastrowid))
    if len(inserted) != EXPECTED["new_equipment"]:
        raise RuntimeError("Canonical equipment insertion count mismatch.")
    return target_ids, inserted


def _insert_aliases(connection, plan, target_ids, now):
    alias_ids = {}
    for identity, alias in sorted(plan["aliases"].items()):
        existing = connection.execute(
            "SELECT id, equipment_id FROM equipment_aliases WHERE user_id = ? AND alias_key = ?",
            identity,
        ).fetchone()
        if existing:
            raise RuntimeError(
                f"Phase 3C-2A requires 26 new aliases; existing alias drifted: {identity}"
            )
        equipment_id = target_ids[alias["target_identity"]]
        cursor = connection.execute(
            """
            INSERT INTO equipment_aliases (
                user_id, equipment_id, alias_name, alias_key, source, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'phase3c2a_approved', 'active', ?, ?)
            """,
            (identity[0], equipment_id, alias["alias_name"], identity[1], now, now),
        )
        alias_ids[identity] = int(cursor.lastrowid)
    if len(alias_ids) != EXPECTED["aliases_inserted"]:
        raise RuntimeError("Alias insertion count mismatch.")
    return alias_ids


def _update_options(connection, plan, target_ids, alias_ids, now):
    changes = []
    enhanced = 0
    for row in plan["automatic_rows"]:
        pair = (str(row["user_id"]), str(row["canonical_key"]))
        spec = TARGET_SPECS[pair]
        identity = (spec.user_id, spec.canonical_key)
        values = _parse_attributes(row["attributes_json"])
        overrides = ATTRIBUTE_OVERRIDES_BY_PENDING_KEY.get(pair, {})
        if overrides:
            values.update(overrides)
            enhanced += 1
        alias_identity = plan["option_aliases"].get(int(row["id"]))
        alias_id = alias_ids.get(alias_identity) if alias_identity else None
        match_type = (
            "phase3c2a_verified_same_tenant"
            if spec.equipment_id else "phase3c2a_canonical_created"
        )
        before = dict(row)
        cursor = connection.execute(
            """
            UPDATE recipe_equipment_options
               SET equipment_id = ?, canonical_name = ?, canonical_key = ?,
                   option_kind = 'equipment', attributes_json = ?,
                   matched_alias_id = ?, match_type = ?, match_confidence = 0.99,
                   review_status = 'ready', updated_at = ?
             WHERE id = ? AND review_status <> 'ready' AND user_id = ?
            """,
            (
                target_ids[identity], spec.canonical_name, spec.canonical_key,
                _canonical_json(values), alias_id, match_type, now,
                int(row["id"]), spec.user_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Option update drifted for id {int(row['id'])}.")
        after = dict(connection.execute(
            "SELECT * FROM recipe_equipment_options WHERE id = ?", (int(row["id"]),)
        ).fetchone())
        immutable = set(before) & set(after) - {
            "equipment_id", "canonical_name", "canonical_key", "option_kind",
            "attributes_json", "matched_alias_id", "match_type", "match_confidence",
            "review_status", "updated_at", "logical_requirement_id",
            "requirement_user_id", "recipe_id", "requirement_source",
            "requirement_connector", "requirement_conjunction_group", "requirement_status",
        }
        if any(before[key] != after[key] for key in immutable):
            raise RuntimeError(f"An immutable option field changed for id {int(row['id'])}.")
        changes.append((row, before, after))
    if len(changes) != EXPECTED["automatic_options"] or (
        enhanced != EXPECTED["attributes_enhanced"]
    ):
        raise RuntimeError("Option or attribute update count mismatch.")
    return changes, enhanced


def _resolve_requirements_and_reviews(connection, plan, now):
    resolved = 0
    reviews = 0
    for row in plan["automatic_rows"]:
        remaining = int(connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_options "
            "WHERE requirement_id = ? AND review_status <> 'ready'",
            (int(row["requirement_id"]),),
        ).fetchone()[0])
        if remaining:
            raise RuntimeError(f"Requirement {int(row['requirement_id'])} remains unresolved.")
        before = dict(connection.execute(
            "SELECT * FROM recipe_equipment_requirements WHERE id = ?",
            (int(row["requirement_id"]),),
        ).fetchone())
        cursor = connection.execute(
            """
            UPDATE recipe_equipment_requirements
               SET review_status = 'ready', updated_at = ?
             WHERE id = ? AND user_id = ? AND review_status = 'pending'
            """,
            (now, int(row["requirement_id"]), str(row["user_id"])),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Requirement update drifted for id {int(row['requirement_id'])}.")
        after = dict(connection.execute(
            "SELECT * FROM recipe_equipment_requirements WHERE id = ?",
            (int(row["requirement_id"]),),
        ).fetchone())
        if any(
            before[key] != after[key]
            for key in before if key not in {"review_status", "updated_at"}
        ):
            raise RuntimeError(f"Requirement semantics changed for id {int(row['requirement_id'])}.")
        resolved += 1
        source_record_id = f"{row['recipe_id']}#{row['logical_requirement_id']}"
        review_cursor = connection.execute(
            """
            UPDATE equipment_normalization_reviews
               SET status = 'resolved', decision = 'phase3c2a_automatic',
                   decision_note = 'Approved Phase 3C-2A automatic matrix decision.',
                   updated_at = ?
             WHERE user_id = ? AND source_record_id = ? AND status = 'pending'
            """,
            (now, str(row["user_id"]), source_record_id),
        )
        if review_cursor.rowcount != 1:
            raise RuntimeError(f"Review update drifted for {source_record_id}.")
        reviews += 1
    return resolved, reviews


def _audit_changes(connection, run_id, changes, now):
    for source, before, after in changes:
        connection.execute(
            """
            INSERT INTO equipment_requirement_migration_map (
                migration_run_id, user_id, recipe_id, legacy_recipe_equipment_id,
                legacy_equipment_id, requirement_id, option_id, decision,
                before_json, after_json, created_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, 'phase3c2a_automatic', ?, ?, ?)
            """,
            (
                run_id, source["user_id"], source["recipe_id"],
                source["logical_requirement_id"], after["option_id"],
                _canonical_json(before), _canonical_json(after), now,
            ),
        )
    if len(changes) != EXPECTED["automatic_options"]:
        raise RuntimeError("Audit-row count mismatch.")
    return len(changes)


def apply_phase3c2a_canonicalization(
    repository_root,
    *,
    db_path=None,
    output_roots=None,
    backup_base=None,
    approval_phrase="",
):
    if str(approval_phrase or "") != CLI_APPROVAL_PHRASE:
        raise PermissionError(
            f"Phase 3C-2A requires approval_phrase={CLI_APPROVAL_PHRASE!r}."
        )
    flags = enabled_application_feature_flags()
    if flags:
        raise RuntimeError(
            "Phase 3C-2A requires every structured-equipment feature flag to remain disabled: "
            + ", ".join(flags)
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
    run_key = f"{MIGRATION_VERSION}:{EXPECTED_AUTOMATIC_IDENTIFIER_SHA256}"

    with _readonly_connection(db_path) as read_connection:
        existing = _completed_run(read_connection, run_key)
        if existing:
            return existing
        if not requirements.structured_equipment_schema_available(read_connection):
            raise RuntimeError("The additive structured-equipment schema is unavailable.")
        phase3a_source_hash = _phase3a_source_hash(read_connection)
        phase3c1_run = _phase3c1_completed(read_connection)
        plan = build_phase3c2a_plan(read_connection)
        staged_before = _staged_fingerprint(read_connection)
        equipment_columns, equipment_before = _baseline_equipment_rows(read_connection)
        links_before = _legacy_link_fingerprint(read_connection)
        holdout_before = _holdout_fingerprint(read_connection, plan["holdout_rows"])

    database_sha_before = _sha256_file(db_path)
    outputs_before = active_output_file_manifest(repository_root, output_roots)
    backup = create_verified_backup(
        repository_root, db_path, output_roots, backup_base=backup_base
    )
    with _readonly_connection(backup["database_backup_path"]) as backup_connection:
        if _staged_fingerprint(backup_connection) != staged_before:
            raise RuntimeError("Pre-3C-2A backup staged fingerprint mismatch; no changes applied.")
        backup_plan = build_phase3c2a_plan(backup_connection)
        if _holdout_fingerprint(backup_connection, backup_plan["holdout_rows"]) != holdout_before:
            raise RuntimeError("Pre-3C-2A backup holdout fingerprint mismatch; no changes applied.")
    if _sha256_file(db_path) != database_sha_before:
        raise RuntimeError("Database changed during pre-3C-2A backup; no changes applied.")

    connection = sqlite3.connect(db_path, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        if _staged_fingerprint(connection) != staged_before:
            raise RuntimeError("Staged data changed after backup; Phase 3C-2A rolled back.")
        plan = build_phase3c2a_plan(connection)
        if _holdout_fingerprint(connection, plan["holdout_rows"]) != holdout_before:
            raise RuntimeError("Holdout data changed after backup; Phase 3C-2A rolled back.")
        now = _utc_now_iso()
        cursor = connection.execute(
            """
            INSERT INTO equipment_requirement_migration_runs (
                run_key, mode, source_hash, status, summary_json, started_at
            ) VALUES (?, 'canonicalize_medium_auto', ?, 'running', '{}', ?)
            """,
            (run_key, EXPECTED_AUTOMATIC_IDENTIFIER_SHA256, now),
        )
        run_id = int(cursor.lastrowid)
        target_ids, inserted_equipment_ids = _verify_and_create_targets(
            connection, plan, now
        )
        alias_ids = _insert_aliases(connection, plan, target_ids, now)
        changes, enhanced = _update_options(
            connection, plan, target_ids, alias_ids, now
        )
        resolved, resolved_reviews = _resolve_requirements_and_reviews(
            connection, plan, now
        )
        audit_rows = _audit_changes(connection, run_id, changes, now)

        counts_after = _table_counts(connection)
        expected_after = {
            "equipment": EXPECTED["equipment_after"],
            "aliases": EXPECTED["aliases_after"],
            "requirements": EXPECTED["requirements_after"],
            "options": EXPECTED["options_after"],
            "ready_requirements": EXPECTED["ready_requirements_after"],
            "pending_requirements": EXPECTED["pending_requirements_after"],
            "ready_options": EXPECTED["ready_options_after"],
            "pending_options": EXPECTED["pending_options_after"],
            "pending_reviews": EXPECTED["pending_reviews_after"],
        }
        if any(counts_after.get(key) != value for key, value in expected_after.items()):
            raise RuntimeError(
                f"Post-Phase-3C-2A count mismatch: expected={expected_after}, actual={counts_after}"
            )
        pending_rows = _pending_rows(connection)
        if len(pending_rows) != EXPECTED["holdout_options"] or (
            _identifier_hash(pending_rows) != EXPECTED_HOLDOUT_IDENTIFIER_SHA256
        ):
            raise RuntimeError("The eleven approved holdouts changed; transaction rolled back.")
        if _holdout_fingerprint(connection, pending_rows) != holdout_before:
            raise RuntimeError("Holdout records changed; transaction rolled back.")

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
            raise RuntimeError("A pre-existing equipment row or recipe association changed.")
        placeholders = ",".join("?" for _ in inserted_equipment_ids)
        image_count = int(connection.execute(
            f"SELECT COUNT(*) FROM equipment WHERE id IN ({placeholders}) "
            "AND (image_url <> '' OR image_path <> '')",
            inserted_equipment_ids,
        ).fetchone()[0])
        if image_count:
            raise RuntimeError("A Phase 3C-2A canonical row received an image.")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"Foreign-key reconciliation failed: {len(foreign_keys)} rows")
        if enabled_application_feature_flags():
            raise RuntimeError("A structured-equipment feature flag became enabled.")

        summary = {
            "mode": "phase3c2a_automatic_canonicalization",
            "migration_version": MIGRATION_VERSION,
            "run_key": run_key,
            "migration_run_id": run_id,
            "phase3a_source_hash": phase3a_source_hash,
            "phase3c1_run": phase3c1_run,
            "idempotent_noop": False,
            "backup": backup,
            "counts_before": plan["counts_before"],
            "counts_after": counts_after,
            "identifier_fingerprints": {
                "automatic": plan["automatic_identifier_sha256"],
                "holdout": plan["holdout_identifier_sha256"],
            },
            "approved_scope": {
                "requirements_resolved": resolved,
                "options_resolved": len(changes),
                "reviews_resolved": resolved_reviews,
                "canonical_equipment_created": len(inserted_equipment_ids),
                "canonical_equipment_ids": inserted_equipment_ids,
                "verified_same_tenant_targets_reused": len(plan["reused_targets"]),
                "verified_same_tenant_target_ids": sorted(
                    spec.equipment_id for spec in plan["reused_targets"].values()
                ),
                "aliases_inserted": len(alias_ids),
                "alias_ids": sorted(alias_ids.values()),
                "attributes_enhanced": enhanced,
                "requirements_added": 0,
                "options_added": 0,
            },
            "holdouts": {
                "requirements": EXPECTED["holdout_requirements"],
                "options": EXPECTED["holdout_options"],
                "identifier_sha256": EXPECTED_HOLDOUT_IDENTIFIER_SHA256,
                "unchanged": True,
            },
            "audit_rows": audit_rows,
            "preexisting_equipment_rows_preserved": len(equipment_before),
            "preexisting_equipment_rows_unchanged": True,
            "legacy_recipe_associations_before": links_before,
            "legacy_recipe_associations_after": links_after,
            "legacy_recipe_associations_unchanged": True,
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
        _, final_equipment = _baseline_equipment_rows(verification)
        preexisting_preserved = {
            equipment_id: final_equipment.get(equipment_id)
            for equipment_id in equipment_before
        } == equipment_before
        final_links = _legacy_link_fingerprint(verification)
        final_pending = _pending_rows(verification)
        final_holdout_hash = _identifier_hash(final_pending)
        final_holdout_fingerprint = _holdout_fingerprint(verification, final_pending)
    outputs_after = active_output_file_manifest(repository_root, output_roots)
    summary["post_commit"] = {
        "database_integrity_check": integrity,
        "foreign_key_violations": foreign_key_rows,
        "counts": final_counts,
        "preexisting_equipment_rows_unchanged": preexisting_preserved,
        "legacy_recipe_associations_unchanged": final_links == links_before,
        "recipe_output_files_unchanged": outputs_after == outputs_before,
        "holdout_identifier_sha256": final_holdout_hash,
        "holdout_records_unchanged": final_holdout_fingerprint == holdout_before,
        "feature_flags_enabled": enabled_application_feature_flags(),
    }
    expected_post = {
        "database_integrity_check": "ok",
        "foreign_key_violations": 0,
        "counts": summary["counts_after"],
        "preexisting_equipment_rows_unchanged": True,
        "legacy_recipe_associations_unchanged": True,
        "recipe_output_files_unchanged": True,
        "holdout_identifier_sha256": EXPECTED_HOLDOUT_IDENTIFIER_SHA256,
        "holdout_records_unchanged": True,
        "feature_flags_enabled": [],
    }
    if summary["post_commit"] != expected_post:
        raise RuntimeError(f"Post-commit reconciliation failed: {summary['post_commit']}")
    return summary
