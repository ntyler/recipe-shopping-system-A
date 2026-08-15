"""Approved Phase 3C-3 owner decisions for structured recipe equipment.

The operation is deliberately migration-only.  It requires the exact approval
phrase, verifies the Phase 3C-2B holdout and recipe context, creates a verified
backup, applies the nine approvals and two review rejections in one transaction,
and leaves application reads and feature flags untouched.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services.equipment_canonicalization_phase3c1_service import (
    _baseline_equipment_rows,
    _canonical_json,
    _legacy_link_fingerprint,
    _phase3a_source_hash,
    _staged_fingerprint,
    _table_counts,
    _utc_now_iso,
)
from PushShoppingList.services.equipment_canonicalization_phase3c2a_service import (
    _completed_run,
    _holdout_fingerprint,
    _identifier_hash,
    _parse_attributes,
    _pending_rows,
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


CLI_APPROVAL_PHRASE = "PHASE3C3_APPROVED"
MIGRATION_VERSION = "equipment-requirements-phase3c3-v1"

TENANT_U = "476262025aa2477a86c6efd66c77c8b0"
TENANT_LOCAL = "local"

EXPECTED_IDENTIFIER_SHA256 = (
    "FB34E8F342567FFAA22E5F7C33EC828DF82AF7CB9E90E0E65ADA0C8DAA1B4085"
)
EXPECTED_QUARANTINE_IDENTIFIER_SHA256 = (
    "2374B0094A3CC8A2AEF303054B40DD699E1088479D35C9887ACD5577036A7868"
)
EXPECTED_RECORD_FINGERPRINT = {
    "requirements": "388C1A59F33C14B0D6EDA3187DFF5A8C549A169E2CBE0D27D6C92BBC32B27DDD",
    "options": "74BD37C708E18C223950B5BEC50FB77F262FDA2F7B2CD2F94A6EBEAF3FBC8285",
    "reviews": "938B2E659E8EC25490E1CB007B0450789B8EF032185889363B40CC38F49F0F03",
}

EXPECTED = {
    "equipment_before": 368,
    "aliases_before": 208,
    "requirements_before": 4394,
    "options_before": 4809,
    "ready_requirements_before": 4383,
    "pending_requirements_before": 11,
    "ready_options_before": 4798,
    "pending_options_before": 11,
    "pending_reviews_before": 11,
    "approved_requirements": 9,
    "approved_options": 9,
    "rejected_requirements": 2,
    "rejected_options": 2,
    "aliases_inserted": 2,
    "equipment_after": 368,
    "aliases_after": 210,
    "requirements_after": 4394,
    "options_after": 4809,
    "ready_requirements_after": 4392,
    "pending_requirements_after": 2,
    "ready_options_after": 4807,
    "pending_options_after": 2,
    "pending_reviews_after": 0,
}


@dataclass(frozen=True)
class DecisionSpec:
    case_number: int
    user_id: str
    recipe_id: str
    requirement_pk: int
    requirement_id: str
    option_pk: int
    option_id: str
    review_pk: int
    source_text: str
    source_option_text: str
    connector: str
    conjunction_group: str
    action: str
    current_option_kind: str = "equipment"
    current_canonical_key: str = ""
    current_option_status: str = "pending_master"
    current_equipment_id: int | None = None
    equipment_id: int | None = None
    canonical_name: str = ""
    canonical_key: str = ""
    option_kind: str = "equipment"
    attributes: dict | None = None
    alias_name: str = ""
    match_type: str = ""
    confidence: float = 0.0
    ingredient_reference_id: int | None = None


@dataclass(frozen=True)
class TargetExpectation:
    user_id: str
    name: str
    normalized_name: str
    canonical_name: str
    canonical_key: str


DECISIONS = (
    DecisionSpec(
        1, TENANT_U,
        "https://www.velasiancuisine.com/rs/menu_home5.action?resInput=RES4902&menu_item=menu-item-128-Vegetable_Banhmi",
        994, "eqr_bf203b66d5f24eb8", 1216, "eqo_16b207dc0a492bd9", 906,
        "loaf cutter", "loaf cutter", "single", "", "approve_recommended",
        current_canonical_key="loaf cutter", equipment_id=8112,
        canonical_name="Knife", canonical_key="knife", attributes={},
        alias_name="loaf cutter", match_type="phase3c3_owner_alias", confidence=0.91,
    ),
    DecisionSpec(
        2, TENANT_U,
        "https://www.velasiancuisine.com/rs/menu_home5.action?resInput=RES4902&menu_item=menu-item-194-Ocean_Roll",
        1206, "eqr_6a1a9ce28166cd90", 1461, "eqo_239c1c5e44928eaa", 1100,
        "Rice paper sheets", "Rice paper sheets", "single", "", "approve_recommended",
        current_canonical_key="rice paper sheets", canonical_name="Soy paper sheets",
        canonical_key="soy paper sheets", option_kind="ingredient", attributes={},
        match_type="phase3c3_owner_reclassified", confidence=0.99,
        ingredient_reference_id=6610,
    ),
    DecisionSpec(
        3, TENANT_U,
        "https://www.velasiancuisine.com/rs/menu_home5.action?resInput=RES4902&menu_item=menu-item-243-Chocolate_Ice_Cream",
        1371, "eqr_5373113d08d4e195", 1641, "eqo_fd2e4da13bbb3f0b", 1250,
        "9-inch round ice cream maker bowl and lid",
        "9-inch round ice cream maker bowl", "and", "eqg_f6d0684fbf39b84c",
        "approve_recommended", current_canonical_key="ice cream maker bowl",
        equipment_id=8104, canonical_name="Ice cream maker",
        canonical_key="ice cream maker",
        attributes={"component": "bowl", "shape": "round", "size": "9-inch"},
        alias_name="9-inch round ice cream maker bowl",
        match_type="phase3c3_owner_alias", confidence=0.88,
    ),
    DecisionSpec(
        4, TENANT_U,
        "https://www.velasiancuisine.com/rs/menu_home5.action?resInput=RES4902&menu_item=menu-item-243-Chocolate_Ice_Cream",
        1372, "eqr_60fd214b55a32204", 1642, "eqo_798ef5c0a7affa9c", 1251,
        "9-inch round ice cream maker bowl and lid", "lid", "and",
        "eqg_f6d0684fbf39b84c", "approve_recommended",
        current_canonical_key="lid", equipment_id=8104,
        canonical_name="Ice cream maker", canonical_key="ice cream maker",
        attributes={"component": "lid"},
        match_type="phase3c3_contextual_component", confidence=0.78,
    ),
    DecisionSpec(
        5, TENANT_U,
        "https://www.velasiancuisine.com/rs/menu_home5.action?resInput=RES4902&menu_item=menu-item-262-Hot_Tea",
        1434, "eqr_33adbfb8cd2841d1", 1712, "eqo_7c93c74188f47d2f", 1310,
        "Tea bag holder", "Tea bag holder", "single", "",
        "reject_keep_pending", current_canonical_key="tea bag holder",
    ),
    DecisionSpec(
        6, TENANT_U,
        "menu://menu_f17e3a2b3ca64844934d5aaa3668effa?menu_item=menu-item-11-Chicken_Gyoza",
        1736, "eqr_7dadb8415e373960", 2066, "eqo_284aa6f87a1081a5", 1561,
        "steamer or lid", "lid", "or", "", "approve_recommended",
        current_canonical_key="lid", equipment_id=8153,
        canonical_name="Skillet", canonical_key="skillet",
        attributes={"includes_lid": True, "required_component": "lid"},
        match_type="phase3c3_contextual_component", confidence=0.96,
    ),
    DecisionSpec(
        7, TENANT_U,
        "menu://menu_f17e3a2b3ca64844934d5aaa3668effa?menu_item=menu-item-212-White_Rice",
        2108, "eqr_ff904cf2c9911b50", 2442, "eqo_f1e5ed1dea6ced3e", 1891,
        "lid", "lid", "single", "", "approve_recommended",
        current_canonical_key="lid", equipment_id=8140,
        canonical_name="Saucepan", canonical_key="saucepan",
        attributes={"includes_lid": True, "required_component": "lid"},
        match_type="phase3c3_contextual_component", confidence=0.98,
    ),
    DecisionSpec(
        8, TENANT_LOCAL,
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-10-Pork_Dumpling",
        3065, "eqr_caa7ad529e7f9d13", 3441, "eqo_0a6d457eba75726b", 2449,
        "teaspoon", "teaspoon", "single", "", "approve_recommended",
        current_canonical_key="measuring spoon", equipment_id=101,
        canonical_name="Teaspoon", canonical_key="teaspoon",
        attributes={"measure_size": "teaspoon"},
        match_type="phase3c3_verified_same_tenant", confidence=0.94,
    ),
    DecisionSpec(
        9, TENANT_LOCAL,
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-222-White_Rice",
        3704, "eqr_eee174433b7e9677", 4099, "eqo_8c4eaf19004d2359", 2501,
        "lid", "lid", "single", "", "approve_recommended",
        current_canonical_key="lid", current_option_status="needs_review",
        current_equipment_id=2066, equipment_id=2066,
        canonical_name="Lid", canonical_key="lid", attributes={},
        match_type="phase3c3_verified_same_tenant", confidence=0.97,
    ),
    DecisionSpec(
        10, TENANT_LOCAL,
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-265-Coconut_Juice",
        3903, "eqr_8ea026cb53a501be", 4301, "eqo_68b907bef7fb0d0c", 2526,
        "tablespoon", "tablespoon", "single", "", "approve_recommended",
        current_canonical_key="measuring spoon", equipment_id=2460,
        canonical_name="Tablespoon", canonical_key="tablespoon",
        attributes={"measure_size": "tablespoon"},
        match_type="phase3c3_verified_same_tenant", confidence=0.99,
    ),
    DecisionSpec(
        11, TENANT_LOCAL, "manual://recipe/d0ef0b49deba454abf953088fd6f03ff",
        4310, "eqr_d466daff6c38f30a", 4723, "eqo_59c295f18d178854", 2569,
        "ZSXDC", "ZSXDC", "single", "", "reject_keep_pending",
        current_canonical_key="zsxdc",
    ),
)


EXPECTED_TARGETS = {
    101: TargetExpectation(TENANT_LOCAL, "teaspoon", "teaspoon", "", ""),
    2066: TargetExpectation(TENANT_LOCAL, "lid", "lid", "", ""),
    2460: TargetExpectation(TENANT_LOCAL, "tablespoon", "tablespoon", "", ""),
    8104: TargetExpectation(
        TENANT_U, "Ice cream maker", "ice cream maker", "Ice cream maker", "ice cream maker"
    ),
    8112: TargetExpectation(TENANT_U, "Knife", "knife", "Knife", "knife"),
    8140: TargetExpectation(TENANT_U, "Saucepan", "saucepan", "Saucepan", "saucepan"),
    8153: TargetExpectation(TENANT_U, "Skillet", "skillet", "Skillet", "skillet"),
}

EXPECTED_INGREDIENT_TARGETS = {
    6610: {
        "user_id": TENANT_U,
        "name": "Soy paper sheets",
        "normalized_name": "soy paper sheets",
        "image_url": "",
        "image_path": "",
    },
}

CONTEXT_FILES = (
    "PushShoppingList/user_data/users/476262025aa2477a86c6efd66c77c8b0/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home5_action_resInput_RES4902_menu_item_menu-item-128-Vegetable_Banhmi.json",
    "PushShoppingList/user_data/users/476262025aa2477a86c6efd66c77c8b0/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home5_action_resInput_RES4902_menu_item_menu-item-194-Ocean_Roll.json",
    "PushShoppingList/user_data/users/476262025aa2477a86c6efd66c77c8b0/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home5_action_resInput_RES4902_menu_item_menu-item-243-Chocolate_Ice_Cream.json",
    "PushShoppingList/user_data/users/476262025aa2477a86c6efd66c77c8b0/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home5_action_resInput_RES4902_menu_item_menu-item-262-Hot_Tea.json",
    "PushShoppingList/user_data/users/476262025aa2477a86c6efd66c77c8b0/recipe-extractor/data/output/menu_menu_f17e3a2b3ca64844934d5aaa3668effa_menu_item_menu-item-11-Chicken_Gyoza.json",
    "PushShoppingList/user_data/users/476262025aa2477a86c6efd66c77c8b0/recipe-extractor/data/output/menu_menu_f17e3a2b3ca64844934d5aaa3668effa_menu_item_menu-item-212-White_Rice.json",
    "PushShoppingList/services/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home_action_resInput_RES4902_menu_item_menu-item-10-Pork_Dumpling.json",
    "PushShoppingList/services/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home_action_resInput_RES4902_menu_item_menu-item-222-White_Rice.json",
    "PushShoppingList/services/recipe-extractor/data/output/velasiancuisine_com_rs_menu_home_action_resInput_RES4902_menu_item_menu-item-265-Coconut_Juice.json",
    "PushShoppingList/services/recipe-extractor/data/output/manual_recipe_d0ef0b49deba454abf953088fd6f03ff.json",
)
EXPECTED_CONTEXT_SHA256 = (
    "E2CFA81B43EE4B21B6279DBC24800D7E56743C240AEC39BA0552591160118935"
)


def _phase3c2a_completed(connection):
    row = connection.execute(
        """
        SELECT id, run_key FROM equipment_requirement_migration_runs
         WHERE mode = 'canonicalize_medium_auto' AND status = 'complete'
         ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        raise RuntimeError("A completed Phase 3C-2A run is required.")
    return {"id": int(row["id"]), "run_key": str(row["run_key"])}


def _decision_scope_hash():
    return _json_hash([
        {
            "case": spec.case_number,
            "user_id": spec.user_id,
            "requirement_id": spec.requirement_id,
            "option_id": spec.option_id,
            "action": spec.action,
            "equipment_id": spec.equipment_id,
            "canonical_name": spec.canonical_name,
            "canonical_key": spec.canonical_key,
            "option_kind": spec.option_kind,
            "attributes": spec.attributes or {},
            "alias_name": spec.alias_name,
            "match_type": spec.match_type,
            "confidence": spec.confidence,
        }
        for spec in DECISIONS
    ])


def _verify_recipe_context(repository_root):
    rows = []
    for relative in CONTEXT_FILES:
        path = Path(repository_root) / relative
        if not path.is_file():
            raise RuntimeError(f"Phase 3C-2B recipe context is missing: {relative}")
        rows.append([relative, _sha256_file(path)])
    fingerprint = _json_hash(rows)
    if fingerprint != EXPECTED_CONTEXT_SHA256:
        raise RuntimeError(
            "Phase 3C-2B active recipe context drifted; no Phase 3C-3 changes applied."
        )
    return {"files": rows, "sha256": fingerprint}


def _verify_backup_context(backup, context):
    manifest = json.loads(Path(backup["manifest_path"]).read_text(encoding="utf-8"))
    copied = {
        Path(str(row["path"])).as_posix(): str(row["sha256"])
        for row in manifest["outputs"]
    }
    expected = {
        Path(path).as_posix(): digest for path, digest in context["files"]
    }
    missing = {path: digest for path, digest in expected.items() if copied.get(path) != digest}
    if missing:
        raise RuntimeError(f"Pre-3C-3 backup recipe-context mismatch: {sorted(missing)}")


def _rows_by_id(connection, table):
    columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
    return columns, {
        int(row[0]): list(row)
        for row in connection.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY id"
        ).fetchall()
    }


def _assert_existing_rows_unchanged(connection, table, columns, before):
    for row_id, values in before.items():
        row = connection.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None or list(row) != values:
            raise RuntimeError(f"A pre-existing {table} row changed: {row_id}")


def _expected_counts(phase):
    suffix = "before" if phase == "before" else "after"
    return {
        "equipment": EXPECTED[f"equipment_{suffix}"],
        "aliases": EXPECTED[f"aliases_{suffix}"],
        "requirements": EXPECTED[f"requirements_{suffix}"],
        "options": EXPECTED[f"options_{suffix}"],
        "ready_requirements": EXPECTED[f"ready_requirements_{suffix}"],
        "pending_requirements": EXPECTED[f"pending_requirements_{suffix}"],
        "ready_options": EXPECTED[f"ready_options_{suffix}"],
        "pending_options": EXPECTED[f"pending_options_{suffix}"],
        "pending_reviews": EXPECTED[f"pending_reviews_{suffix}"],
    }


def _verify_targets(connection):
    for equipment_id, expected in EXPECTED_TARGETS.items():
        row = connection.execute(
            """
            SELECT user_id, name, normalized_name, canonical_name, canonical_key,
                   status, merged_into_id, image_url, image_path
              FROM equipment WHERE id = ?
            """,
            (equipment_id,),
        ).fetchone()
        values = dict(row) if row else {}
        expected_values = {
            "user_id": expected.user_id,
            "name": expected.name,
            "normalized_name": expected.normalized_name,
            "canonical_name": expected.canonical_name,
            "canonical_key": expected.canonical_key,
            "status": "active",
            "merged_into_id": None,
            "image_url": "",
            "image_path": "",
        }
        if values != expected_values:
            raise RuntimeError(f"Approved same-tenant target changed: equipment {equipment_id}")

    for ingredient_id, expected in EXPECTED_INGREDIENT_TARGETS.items():
        row = connection.execute(
            """
            SELECT user_id, name, normalized_name, image_url, image_path
              FROM ingredients WHERE id = ?
            """,
            (ingredient_id,),
        ).fetchone()
        if not row or dict(row) != expected:
            raise RuntimeError(f"Approved ingredient context changed: ingredient {ingredient_id}")


def _validate_spec_row(connection, spec, row):
    checks = {
        "id": spec.option_pk,
        "option_id": spec.option_id,
        "user_id": spec.user_id,
        "requirement_id": spec.requirement_pk,
        "equipment_id": spec.current_equipment_id,
        "source_option_text": spec.source_option_text,
        "canonical_key": spec.current_canonical_key,
        "option_kind": spec.current_option_kind,
        "review_status": spec.current_option_status,
        "logical_requirement_id": spec.requirement_id,
        "requirement_user_id": spec.user_id,
        "recipe_id": spec.recipe_id,
        "requirement_source": spec.source_text,
        "requirement_connector": spec.connector,
        "requirement_conjunction_group": spec.conjunction_group,
        "requirement_status": "pending",
    }
    mismatches = {
        key: {"expected": value, "actual": row[key]}
        for key, value in checks.items() if row[key] != value
    }
    if mismatches:
        raise RuntimeError(f"Phase 3C-3 case {spec.case_number} drifted: {mismatches}")
    review = connection.execute(
        """
        SELECT id, user_id, source_record_id, source_text, status
          FROM equipment_normalization_reviews WHERE id = ?
        """,
        (spec.review_pk,),
    ).fetchone()
    expected_review = {
        "id": spec.review_pk,
        "user_id": spec.user_id,
        "source_record_id": f"{spec.recipe_id}#{spec.requirement_id}",
        "source_text": spec.source_text,
        "status": "pending",
    }
    if not review or dict(review) != expected_review:
        raise RuntimeError(f"Phase 3C-3 review drifted for case {spec.case_number}.")


def build_phase3c3_plan(connection):
    """Build and validate the exact owner-approved plan without writing."""
    counts = _table_counts(connection)
    if counts != _expected_counts("before"):
        raise RuntimeError(
            f"Phase 3C-3 preflight count drift: expected={_expected_counts('before')}, actual={counts}"
        )
    phase3c2a_run = _phase3c2a_completed(connection)
    rows = _pending_rows(connection)
    if _identifier_hash(rows) != EXPECTED_IDENTIFIER_SHA256:
        raise RuntimeError("Phase 3C-3 holdout identifiers drifted from Phase 3C-2B.")
    record_fingerprint = _holdout_fingerprint(connection, rows)
    if record_fingerprint != EXPECTED_RECORD_FINGERPRINT:
        raise RuntimeError("Phase 3C-3 holdout records drifted from Phase 3C-2B.")
    if len(rows) != len(DECISIONS):
        raise RuntimeError("Phase 3C-3 decision cardinality changed.")
    if any(str(row["user_id"]) != str(row["requirement_user_id"]) for row in rows):
        raise RuntimeError("A Phase 3C-3 option crosses its requirement tenant boundary.")

    by_identifier = {
        (str(row["logical_requirement_id"]), str(row["option_id"])): row for row in rows
    }
    if len(by_identifier) != len(rows):
        raise RuntimeError("Phase 3C-3 logical identifiers are not unique.")
    for spec in DECISIONS:
        row = by_identifier.get((spec.requirement_id, spec.option_id))
        if row is None:
            raise RuntimeError(f"Phase 3C-3 case {spec.case_number} is missing.")
        _validate_spec_row(connection, spec, row)

    approved = [spec for spec in DECISIONS if spec.action == "approve_recommended"]
    rejected = [spec for spec in DECISIONS if spec.action == "reject_keep_pending"]
    if len(approved) != EXPECTED["approved_options"] or len(rejected) != EXPECTED["rejected_options"]:
        raise RuntimeError("Phase 3C-3 owner-choice boundary changed.")
    quarantine_hash = _json_hash([
        [spec.requirement_id, spec.option_id] for spec in rejected
    ])
    if quarantine_hash != EXPECTED_QUARANTINE_IDENTIFIER_SHA256:
        raise RuntimeError("Phase 3C-3 quarantine identifiers changed.")

    _verify_targets(connection)
    aliases = {}
    option_aliases = {}
    for spec in approved:
        if not spec.alias_name:
            continue
        alias_key = normalized_equipment_key(spec.alias_name)
        identity = (spec.user_id, alias_key)
        if not alias_key or spec.equipment_id is None:
            raise RuntimeError(f"Invalid alias plan for case {spec.case_number}.")
        if identity in aliases and aliases[identity]["equipment_id"] != spec.equipment_id:
            raise RuntimeError(f"Ambiguous Phase 3C-3 alias: {identity}")
        existing = connection.execute(
            "SELECT id FROM equipment_aliases WHERE user_id = ? AND alias_key = ?", identity
        ).fetchone()
        collision = connection.execute(
            """
            SELECT id FROM equipment
             WHERE user_id = ? AND (normalized_name = ? OR canonical_key = ?)
            """,
            (spec.user_id, alias_key, alias_key),
        ).fetchone()
        if existing or collision:
            raise RuntimeError(f"Phase 3C-3 alias collision: {identity}")
        aliases[identity] = {
            "alias_name": spec.alias_name,
            "equipment_id": spec.equipment_id,
        }
        option_aliases[spec.option_id] = identity
    if len(aliases) != EXPECTED["aliases_inserted"]:
        raise RuntimeError("Phase 3C-3 deterministic alias count changed.")

    return {
        "counts_before": counts,
        "phase3c2a_run": phase3c2a_run,
        "rows": rows,
        "approved": approved,
        "rejected": rejected,
        "aliases": aliases,
        "option_aliases": option_aliases,
        "identifier_sha256": _identifier_hash(rows),
        "record_fingerprint": record_fingerprint,
        "quarantine_identifier_sha256": quarantine_hash,
        "decision_scope_sha256": _decision_scope_hash(),
    }


def _insert_aliases(connection, plan, now):
    alias_ids = {}
    for identity, values in sorted(plan["aliases"].items()):
        cursor = connection.execute(
            """
            INSERT INTO equipment_aliases (
                user_id, equipment_id, alias_name, alias_key, source, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'phase3c3_owner_approved', 'active', ?, ?)
            """,
            (identity[0], values["equipment_id"], values["alias_name"], identity[1], now, now),
        )
        alias_ids[identity] = int(cursor.lastrowid)
    if len(alias_ids) != EXPECTED["aliases_inserted"]:
        raise RuntimeError("Phase 3C-3 alias insertion count mismatch.")
    return alias_ids


def _merge_attributes(current_json, additions, case_number):
    values = _parse_attributes(current_json)
    for key, value in (additions or {}).items():
        if key in values and values[key] != value:
            raise RuntimeError(
                f"Phase 3C-3 case {case_number} attribute collision for {key!r}."
            )
        values[key] = value
    return _canonical_json(values)


def _assert_only_changed(before, after, allowed, label):
    changed = {key for key in before if before[key] != after[key]}
    if not changed.issubset(set(allowed)):
        raise RuntimeError(f"Immutable fields changed for {label}: {sorted(changed - set(allowed))}")


def _apply_decisions(connection, plan, alias_ids, run_id, now):
    approved_count = 0
    rejected_count = 0
    audit_count = 0
    for spec in DECISIONS:
        requirement_before = dict(connection.execute(
            "SELECT * FROM recipe_equipment_requirements WHERE id = ?", (spec.requirement_pk,)
        ).fetchone())
        option_before = dict(connection.execute(
            "SELECT * FROM recipe_equipment_options WHERE id = ?", (spec.option_pk,)
        ).fetchone())
        review_before = dict(connection.execute(
            "SELECT * FROM equipment_normalization_reviews WHERE id = ?", (spec.review_pk,)
        ).fetchone())

        if spec.action == "approve_recommended":
            alias_identity = plan["option_aliases"].get(spec.option_id)
            alias_id = alias_ids.get(alias_identity) if alias_identity else None
            attributes_json = _merge_attributes(
                option_before["attributes_json"], spec.attributes, spec.case_number
            )
            cursor = connection.execute(
                """
                UPDATE recipe_equipment_options
                   SET equipment_id = ?, canonical_name = ?, canonical_key = ?,
                       option_kind = ?, attributes_json = ?, matched_alias_id = ?,
                       match_type = ?, match_confidence = ?, review_status = 'ready',
                       updated_at = ?
                 WHERE id = ? AND option_id = ? AND user_id = ?
                   AND review_status <> 'ready'
                """,
                (
                    spec.equipment_id, spec.canonical_name, spec.canonical_key,
                    spec.option_kind, attributes_json, alias_id, spec.match_type,
                    spec.confidence, now, spec.option_pk, spec.option_id, spec.user_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Phase 3C-3 option update drifted for case {spec.case_number}.")
            remaining = int(connection.execute(
                "SELECT COUNT(*) FROM recipe_equipment_options WHERE requirement_id = ? AND review_status <> 'ready'",
                (spec.requirement_pk,),
            ).fetchone()[0])
            if remaining:
                raise RuntimeError(f"Phase 3C-3 case {spec.case_number} requirement remains pending.")
            req_cursor = connection.execute(
                """
                UPDATE recipe_equipment_requirements
                   SET review_status = 'ready', updated_at = ?
                 WHERE id = ? AND requirement_id = ? AND user_id = ? AND review_status = 'pending'
                """,
                (now, spec.requirement_pk, spec.requirement_id, spec.user_id),
            )
            if req_cursor.rowcount != 1:
                raise RuntimeError(f"Phase 3C-3 requirement update drifted for case {spec.case_number}.")
            review_decision = "phase3c3_owner_approved"
            review_note = f"Approved Phase 3C-3 recommended decision for case {spec.case_number}."
            approved_count += 1
        elif spec.action == "reject_keep_pending":
            review_decision = "phase3c3_rejected_keep_pending"
            review_note = f"Rejected Phase 3C-3 case {spec.case_number}; requirement and option remain pending."
            rejected_count += 1
        else:
            raise RuntimeError(f"Unsupported Phase 3C-3 action: {spec.action}")

        review_cursor = connection.execute(
            """
            UPDATE equipment_normalization_reviews
               SET status = 'resolved', decision = ?, decision_note = ?, updated_at = ?
             WHERE id = ? AND user_id = ? AND status = 'pending'
            """,
            (review_decision, review_note, now, spec.review_pk, spec.user_id),
        )
        if review_cursor.rowcount != 1:
            raise RuntimeError(f"Phase 3C-3 review update drifted for case {spec.case_number}.")

        requirement_after = dict(connection.execute(
            "SELECT * FROM recipe_equipment_requirements WHERE id = ?", (spec.requirement_pk,)
        ).fetchone())
        option_after = dict(connection.execute(
            "SELECT * FROM recipe_equipment_options WHERE id = ?", (spec.option_pk,)
        ).fetchone())
        review_after = dict(connection.execute(
            "SELECT * FROM equipment_normalization_reviews WHERE id = ?", (spec.review_pk,)
        ).fetchone())

        if spec.action == "approve_recommended":
            _assert_only_changed(
                requirement_before, requirement_after, {"review_status", "updated_at"},
                f"case {spec.case_number} requirement",
            )
            _assert_only_changed(
                option_before, option_after,
                {
                    "equipment_id", "canonical_name", "canonical_key", "option_kind",
                    "attributes_json", "matched_alias_id", "match_type",
                    "match_confidence", "review_status", "updated_at",
                },
                f"case {spec.case_number} option",
            )
        else:
            if requirement_after != requirement_before or option_after != option_before:
                raise RuntimeError(
                    f"Rejected Phase 3C-3 case {spec.case_number} changed its requirement or option."
                )
        _assert_only_changed(
            review_before, review_after,
            {"status", "decision", "decision_note", "updated_at"},
            f"case {spec.case_number} review",
        )

        before_payload = {
            "requirement": requirement_before,
            "option": option_before,
            "review": review_before,
        }
        after_payload = {
            "requirement": requirement_after,
            "option": option_after,
            "review": review_after,
        }
        connection.execute(
            """
            INSERT INTO equipment_requirement_migration_map (
                migration_run_id, user_id, recipe_id, legacy_recipe_equipment_id,
                legacy_equipment_id, requirement_id, option_id, decision,
                before_json, after_json, created_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, spec.user_id, spec.recipe_id, spec.requirement_id,
                spec.option_id, review_decision, _canonical_json(before_payload),
                _canonical_json(after_payload), now,
            ),
        )
        audit_count += 1

    if approved_count != EXPECTED["approved_options"] or rejected_count != EXPECTED["rejected_options"]:
        raise RuntimeError("Phase 3C-3 applied decision count mismatch.")
    if audit_count != len(DECISIONS):
        raise RuntimeError("Phase 3C-3 audit count mismatch.")
    return approved_count, rejected_count, audit_count


def apply_phase3c3_owner_decisions(
    repository_root,
    *,
    db_path=None,
    output_roots=None,
    backup_base=None,
    approval_phrase="",
):
    if str(approval_phrase or "") != CLI_APPROVAL_PHRASE:
        raise PermissionError(
            f"Phase 3C-3 requires approval_phrase={CLI_APPROVAL_PHRASE!r}."
        )
    flags = enabled_application_feature_flags()
    if flags:
        raise RuntimeError(
            "Phase 3C-3 requires every structured-equipment feature flag to remain disabled: "
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
    decision_scope_sha256 = _decision_scope_hash()
    run_key = f"{MIGRATION_VERSION}:{EXPECTED_IDENTIFIER_SHA256}:{decision_scope_sha256}"

    with _readonly_connection(db_path) as read_connection:
        existing = _completed_run(read_connection, run_key)
        if existing:
            return existing
        if not requirements.structured_equipment_schema_available(read_connection):
            raise RuntimeError("The additive structured-equipment schema is unavailable.")
        phase3a_source_hash = _phase3a_source_hash(read_connection)
        plan = build_phase3c3_plan(read_connection)
        staged_before = _staged_fingerprint(read_connection)
        equipment_columns, equipment_before = _baseline_equipment_rows(read_connection)
        alias_columns, aliases_before = _rows_by_id(read_connection, "equipment_aliases")
        ingredient_columns, ingredients_before = _rows_by_id(read_connection, "ingredients")
        links_before = _legacy_link_fingerprint(read_connection)

    context_before = _verify_recipe_context(repository_root)
    database_sha_before = _sha256_file(db_path)
    outputs_before = active_output_file_manifest(repository_root, output_roots)
    backup = create_verified_backup(
        repository_root, db_path, output_roots, backup_base=backup_base
    )
    _verify_backup_context(backup, context_before)
    with _readonly_connection(backup["database_backup_path"]) as backup_connection:
        if _staged_fingerprint(backup_connection) != staged_before:
            raise RuntimeError("Pre-3C-3 backup staged fingerprint mismatch; no changes applied.")
        backup_plan = build_phase3c3_plan(backup_connection)
        if backup_plan["record_fingerprint"] != plan["record_fingerprint"]:
            raise RuntimeError("Pre-3C-3 backup holdout mismatch; no changes applied.")
    if _sha256_file(db_path) != database_sha_before:
        raise RuntimeError("Database changed during pre-3C-3 backup; no changes applied.")
    if _verify_recipe_context(repository_root) != context_before:
        raise RuntimeError("Recipe context changed during pre-3C-3 backup; no changes applied.")

    connection = sqlite3.connect(db_path, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    master_data.install_recipe_master_connection_guest_write_fences(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if _staged_fingerprint(connection) != staged_before:
            raise RuntimeError("Staged data changed after backup; Phase 3C-3 rolled back.")
        plan = build_phase3c3_plan(connection)
        now = _utc_now_iso()
        cursor = connection.execute(
            """
            INSERT INTO equipment_requirement_migration_runs (
                run_key, mode, source_hash, status, summary_json, started_at
            ) VALUES (?, 'canonicalize_owner_decisions', ?, 'running', '{}', ?)
            """,
            (run_key, decision_scope_sha256, now),
        )
        run_id = int(cursor.lastrowid)
        alias_ids = _insert_aliases(connection, plan, now)
        approved, rejected, audit_rows = _apply_decisions(
            connection, plan, alias_ids, run_id, now
        )

        counts_after = _table_counts(connection)
        if counts_after != _expected_counts("after"):
            raise RuntimeError(
                f"Post-Phase-3C-3 count mismatch: expected={_expected_counts('after')}, actual={counts_after}"
            )
        pending_after = _pending_rows(connection)
        if _identifier_hash(pending_after) != EXPECTED_QUARANTINE_IDENTIFIER_SHA256:
            raise RuntimeError("Phase 3C-3 quarantine set changed; transaction rolled back.")
        _assert_existing_rows_unchanged(
            connection, "equipment", equipment_columns, equipment_before
        )
        _assert_existing_rows_unchanged(
            connection, "equipment_aliases", alias_columns, aliases_before
        )
        _assert_existing_rows_unchanged(
            connection, "ingredients", ingredient_columns, ingredients_before
        )
        links_after = _legacy_link_fingerprint(connection)
        if links_after != links_before:
            raise RuntimeError("A legacy recipe association changed; Phase 3C-3 rolled back.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key reconciliation failed; Phase 3C-3 rolled back.")
        if enabled_application_feature_flags():
            raise RuntimeError("A structured-equipment feature flag became enabled.")

        summary = {
            "mode": "phase3c3_owner_decisions",
            "migration_version": MIGRATION_VERSION,
            "run_key": run_key,
            "migration_run_id": run_id,
            "phase3a_source_hash": phase3a_source_hash,
            "phase3c2a_run": plan["phase3c2a_run"],
            "idempotent_noop": False,
            "backup": backup,
            "counts_before": plan["counts_before"],
            "counts_after": counts_after,
            "identifier_fingerprints": {
                "phase3c2b_holdout": plan["identifier_sha256"],
                "quarantined_after": EXPECTED_QUARANTINE_IDENTIFIER_SHA256,
                "decision_scope": decision_scope_sha256,
                "record_fingerprint_before": plan["record_fingerprint"],
                "recipe_context": context_before["sha256"],
            },
            "approved_scope": {
                "requirements_resolved": approved,
                "options_resolved": approved,
                "reviews_approved": approved,
                "reviews_rejected": rejected,
                "equipment_created": 0,
                "equipment_modified": 0,
                "aliases_inserted": len(alias_ids),
                "alias_ids": sorted(alias_ids.values()),
                "audit_rows": audit_rows,
                "cases": [
                    {"case": spec.case_number, "choice": spec.action}
                    for spec in DECISIONS
                ],
            },
            "quarantine": {
                "requirements": rejected,
                "options": rejected,
                "pending_reviews": 0,
                "identifier_sha256": EXPECTED_QUARANTINE_IDENTIFIER_SHA256,
            },
            "reconciliation": {
                "preexisting_equipment_rows_unchanged": True,
                "preexisting_alias_rows_unchanged": True,
                "ingredient_rows_unchanged": True,
                "legacy_recipe_associations_before": links_before,
                "legacy_recipe_associations_after": links_after,
                "legacy_recipe_associations_unchanged": True,
                "images_copied_or_replaced": 0,
                "feature_flags_enabled": [],
                "application_reads_modified": False,
                "cutover_performed": False,
            },
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
        foreign_keys = len(verification.execute("PRAGMA foreign_key_check").fetchall())
        final_counts = _table_counts(verification)
        _, final_equipment = _baseline_equipment_rows(verification)
        equipment_preserved = {
            row_id: final_equipment.get(row_id) for row_id in equipment_before
        } == equipment_before
        final_links = _legacy_link_fingerprint(verification)
        final_pending = _pending_rows(verification)
        pending_hash = _identifier_hash(final_pending)
        map_count = int(verification.execute(
            "SELECT COUNT(*) FROM equipment_requirement_migration_map WHERE migration_run_id = ?",
            (summary["migration_run_id"],),
        ).fetchone()[0])
    outputs_after = active_output_file_manifest(repository_root, output_roots)
    context_after = _verify_recipe_context(repository_root)
    post_commit = {
        "database_integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
        "counts": final_counts,
        "preexisting_equipment_rows_unchanged": equipment_preserved,
        "legacy_recipe_associations_unchanged": final_links == links_before,
        "recipe_output_files_unchanged": outputs_after == outputs_before,
        "recipe_context_unchanged": context_after == context_before,
        "quarantine_identifier_sha256": pending_hash,
        "audit_rows": map_count,
        "feature_flags_enabled": enabled_application_feature_flags(),
    }
    expected_post = {
        "database_integrity_check": "ok",
        "foreign_key_violations": 0,
        "counts": summary["counts_after"],
        "preexisting_equipment_rows_unchanged": True,
        "legacy_recipe_associations_unchanged": True,
        "recipe_output_files_unchanged": True,
        "recipe_context_unchanged": True,
        "quarantine_identifier_sha256": EXPECTED_QUARANTINE_IDENTIFIER_SHA256,
        "audit_rows": len(DECISIONS),
        "feature_flags_enabled": [],
    }
    if post_commit != expected_post:
        raise RuntimeError(f"Post-Phase-3C-3 reconciliation failed: {post_commit}")
    summary["post_commit"] = post_commit
    return summary
