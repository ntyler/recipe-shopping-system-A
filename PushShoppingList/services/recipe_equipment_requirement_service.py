"""Feature-gated structured persistence for recipe equipment requirements.

Schema creation and structured writes are explicit operations.  Importing or
reading this module never changes the application database.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

from PushShoppingList.services.equipment_normalization_service import (
    PARSER_VERSION,
    equipment_source_text,
    instruction_texts,
    normalized_equipment_key,
    parse_equipment_list,
    requirement_summary,
    truthy,
)


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
PHASE3A_MIGRATION_TOKEN = "phase3a-additive-stage-v1"
LOGGER = logging.getLogger(__name__)

STRUCTURED_EQUIPMENT_FLAG_NAMES = (
    "RECIPE_EQUIPMENT_STRUCTURED_SHADOW_ENABLED",
    "RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_ENABLED",
    "RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED",
    "RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED",
    "RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED",
    "RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED",
    "RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED",
)

TENANT_ALLOWLIST_ENV = {
    "RECIPE_EQUIPMENT_STRUCTURED_SHADOW_ENABLED": (
        "RECIPE_EQUIPMENT_STRUCTURED_SHADOW_TENANTS"
    ),
    "RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_ENABLED": (
        "RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_TENANTS"
    ),
    "RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED": (
        "RECIPE_EQUIPMENT_STRUCTURED_READ_TENANTS"
    ),
    "RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED": (
        "RECIPE_EQUIPMENT_STRUCTURED_UI_TENANTS"
    ),
    "RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED": (
        "RECIPE_EQUIPMENT_STRUCTURED_WRITE_TENANTS"
    ),
    "RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED": (
        "RECIPE_EQUIPMENT_REVIEW_WRITE_TENANTS"
    ),
}


class StructuredEquipmentFallback(RuntimeError):
    """A fail-closed reason that makes the whole recipe use legacy equipment."""

    def __init__(self, reason, details=None):
        super().__init__(str(reason or "invalid_structured_data"))
        self.reason = str(reason or "invalid_structured_data")
        self.details = details if isinstance(details, dict) else {}


def _env_enabled(name):
    return str(os.getenv(name, "") or "").strip().casefold() in TRUE_VALUES


def _tenant_allowlist(name):
    return {
        value.strip()
        for value in str(os.getenv(name, "") or "").split(",")
        if value.strip()
    }


def _tenant_gate_enabled(flag_name, user_id=None):
    """Inspect a global flag, and require an exact tenant when one is supplied.

    Calls without ``user_id`` are introspection-only and are retained for the
    migration safety checks. Runtime callers always supply a tenant.
    """
    if not _env_enabled(flag_name):
        return False
    if user_id is None:
        return True
    tenant = str(user_id or "").strip()
    allowlist_name = TENANT_ALLOWLIST_ENV.get(flag_name)
    return bool(tenant and allowlist_name and tenant in _tenant_allowlist(allowlist_name))


def structured_equipment_shadow_enabled(user_id=None):
    return _tenant_gate_enabled("RECIPE_EQUIPMENT_STRUCTURED_SHADOW_ENABLED", user_id)


def structured_equipment_dual_write_enabled(user_id=None):
    return _tenant_gate_enabled("RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_ENABLED", user_id)


def structured_equipment_ui_enabled(user_id=None):
    return _tenant_gate_enabled("RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED", user_id)


def structured_equipment_read_enabled(user_id=None):
    return _tenant_gate_enabled("RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED", user_id)


def structured_equipment_write_enabled(user_id=None):
    return _tenant_gate_enabled("RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED", user_id)


def structured_equipment_schema_writes_enabled():
    return _env_enabled("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED")


def structured_equipment_review_writes_enabled(user_id=None):
    return _tenant_gate_enabled("RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED", user_id)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def requirements_from_recipe_data(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    return parse_equipment_list(
        recipe_data.get("equipment", []),
        instructions=recipe_data.get("instructions", []),
    )


def add_structured_equipment_preview(recipe_data, *, user_id=None):
    """Attach a structured compatibility preview when structured writes are enabled."""
    if (
        not isinstance(recipe_data, dict)
        or not str(user_id or "").strip()
        or not structured_equipment_write_enabled(user_id)
    ):
        return recipe_data
    recipe_data["equipment_requirements"] = requirements_from_recipe_data(recipe_data)
    recipe_data["equipment_requirement_parser_version"] = PARSER_VERSION
    return recipe_data


def review_queue_from_master_rows(rows):
    queue = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        requirements = parse_equipment_list([{"equipment": name}])
        summary = requirement_summary(requirements)
        has_structure = any(
            requirement.get("connector") in {"or", "and"}
            or any(
                option.get("attributes") or option.get("notes") or option.get("option_kind") != "equipment"
                for option in requirement.get("options", [])
            )
            for requirement in requirements
        )
        if not has_structure and not summary["review_requirement_count"]:
            continue
        queue.append({
            "equipment_id": row.get("id"),
            "name": name,
            "usage_count": int(row.get("usage_count") or 0),
            "review_status": (
                "needs_review" if summary["review_requirement_count"] else "ready"
            ),
            "requirements": requirements,
            "summary": summary,
        })
    return queue


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _json_object(value, *, field_name):
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StructuredEquipmentFallback(
            "unreadable_json", {"field": field_name}
        ) from exc
    if not isinstance(parsed, dict):
        raise StructuredEquipmentFallback(
            "invalid_json_shape", {"field": field_name}
        )
    return parsed


def equipment_source_hash(recipe_data):
    """Hash only legacy inputs that can change the equipment parser result."""
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    payload = {
        "equipment": deepcopy(
            recipe_data.get("equipment")
            if isinstance(recipe_data.get("equipment"), list)
            else []
        ),
        "instructions": instruction_texts(recipe_data.get("instructions", [])),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest().upper()


def _pending_identifier_fingerprint(requirements):
    identifiers = []
    for requirement in requirements if isinstance(requirements, list) else []:
        if requirement.get("review_status") != "ready":
            requirement_id = str(requirement.get("requirement_id") or "")
            for option in requirement.get("options", []):
                if option.get("review_status") != "ready":
                    identifiers.append([
                        requirement_id,
                        str(option.get("option_id") or ""),
                    ])
    return hashlib.sha256(_canonical_json(sorted(identifiers)).encode("utf-8")).hexdigest().upper()


def load_structured_equipment_requirements(
    connection,
    user_id,
    recipe_id,
    *,
    require_ready=True,
):
    """Load and validate one recipe hierarchy without crossing tenant scope."""
    user_id = str(user_id or "").strip()
    recipe_id = str(recipe_id or "").strip()
    if not user_id or not recipe_id:
        raise StructuredEquipmentFallback("missing_identity")
    if connection is None or not structured_equipment_schema_available(connection):
        raise StructuredEquipmentFallback("schema_unavailable")

    requirement_rows = connection.execute(
        """
        SELECT *
          FROM recipe_equipment_requirements
         WHERE user_id = ? AND recipe_id = ?
         ORDER BY sort_order ASC, id ASC
        """,
        (user_id, recipe_id),
    ).fetchall()
    if not requirement_rows:
        raise StructuredEquipmentFallback("missing_structured_recipe")

    option_rows = connection.execute(
        """
        SELECT o.*,
               r.user_id AS requirement_user_id,
               e.user_id AS equipment_user_id,
               e.status AS equipment_status,
               e.image_url AS master_image_url,
               e.image_path AS master_image_path,
               a.user_id AS alias_user_id,
               a.equipment_id AS alias_equipment_id,
               a.status AS alias_status
          FROM recipe_equipment_options o
          JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
          LEFT JOIN equipment e ON e.id = o.equipment_id
          LEFT JOIN equipment_aliases a ON a.id = o.matched_alias_id
         WHERE r.user_id = ? AND r.recipe_id = ?
         ORDER BY r.sort_order ASC, r.id ASC, o.sort_order ASC, o.id ASC
        """,
        (user_id, recipe_id),
    ).fetchall()

    options_by_requirement = {}
    seen_option_ids = set()
    for source_row in option_rows:
        row = dict(source_row)
        option_id = str(row.get("option_id") or "").strip()
        if not option_id or option_id in seen_option_ids:
            raise StructuredEquipmentFallback("duplicate_or_missing_option_id")
        seen_option_ids.add(option_id)
        if str(row.get("user_id") or "") != user_id or str(
            row.get("requirement_user_id") or ""
        ) != user_id:
            raise StructuredEquipmentFallback("tenant_violation", {"option_id": option_id})

        equipment_id = row.get("equipment_id")
        if equipment_id is not None and str(row.get("equipment_user_id") or "") != user_id:
            raise StructuredEquipmentFallback(
                "tenant_violation", {"option_id": option_id, "target": "equipment"}
            )
        alias_id = row.get("matched_alias_id")
        if alias_id is not None and (
            str(row.get("alias_user_id") or "") != user_id
            or int(row.get("alias_equipment_id") or 0) != int(equipment_id or 0)
            or str(row.get("alias_status") or "") != "active"
        ):
            raise StructuredEquipmentFallback(
                "tenant_violation", {"option_id": option_id, "target": "alias"}
            )

        option_kind = str(row.get("option_kind") or "unresolved")
        if option_kind not in {
            "equipment", "supply", "facility", "ingredient", "instruction", "unresolved"
        }:
            raise StructuredEquipmentFallback(
                "invalid_classification", {"option_id": option_id, "kind": option_kind}
            )
        if (
            option_kind == "equipment"
            and str(row.get("review_status") or "") == "ready"
            and (
                equipment_id is None
                or str(row.get("equipment_status") or "") != "active"
            )
        ):
            raise StructuredEquipmentFallback(
                "missing_equipment_target", {"option_id": option_id}
            )
        if require_ready and str(row.get("review_status") or "") != "ready":
            raise StructuredEquipmentFallback(
                "pending_option", {"option_id": option_id}
            )

        # Master images are deliberately retained only as validation context;
        # they are never projected into a recipe-authored equipment row.
        option = {
            key: value
            for key, value in row.items()
            if key not in {
                "requirement_user_id", "equipment_user_id", "equipment_status",
                "master_image_url", "master_image_path", "alias_user_id",
                "alias_equipment_id", "alias_status", "attributes_json",
            }
        }
        option["attributes"] = _json_object(
            row.get("attributes_json"), field_name=f"option:{option_id}:attributes_json"
        )
        options_by_requirement.setdefault(int(row["requirement_id"]), []).append(option)

    requirements = []
    seen_requirement_ids = set()
    for source_row in requirement_rows:
        row = dict(source_row)
        requirement_id = str(row.get("requirement_id") or "").strip()
        if not requirement_id or requirement_id in seen_requirement_ids:
            raise StructuredEquipmentFallback("duplicate_or_missing_requirement_id")
        seen_requirement_ids.add(requirement_id)
        if str(row.get("user_id") or "") != user_id:
            raise StructuredEquipmentFallback(
                "tenant_violation", {"requirement_id": requirement_id}
            )
        connector = str(row.get("connector") or "single")
        if connector not in {"single", "and", "or"}:
            raise StructuredEquipmentFallback(
                "invalid_connector", {"requirement_id": requirement_id}
            )
        if require_ready and str(row.get("review_status") or "") != "ready":
            raise StructuredEquipmentFallback(
                "pending_requirement", {"requirement_id": requirement_id}
            )
        options = options_by_requirement.get(int(row["id"]), [])
        if not options:
            raise StructuredEquipmentFallback(
                "missing_options", {"requirement_id": requirement_id}
            )
        requirement = {
            key: value for key, value in row.items() if key != "metadata_json"
        }
        requirement["optional"] = bool(requirement.get("optional"))
        requirement["source_metadata"] = _json_object(
            row.get("metadata_json"),
            field_name=f"requirement:{requirement_id}:metadata_json",
        )
        requirement["options"] = options
        requirements.append(requirement)
    return requirements


def semantic_equipment_projection(requirements):
    """Collapse stored AND/derived rows back into authored equipment rows."""
    groups = {}
    order = []
    for requirement in requirements if isinstance(requirements, list) else []:
        if not isinstance(requirement, dict):
            raise StructuredEquipmentFallback("invalid_requirement_shape")
        group_id = str(requirement.get("conjunction_group") or "").strip()
        key = ("group", group_id) if group_id else (
            "requirement", str(requirement.get("requirement_id") or "")
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(requirement)

    projection = []
    for key in order:
        members = sorted(
            groups[key], key=lambda row: (int(row.get("sort_order") or 0), int(row.get("id") or 0))
        )
        source_texts = {str(row.get("source_text") or "") for row in members}
        optional_values = {bool(row.get("optional")) for row in members}
        quantities = {str(row.get("quantity") or "") for row in members}
        if len(source_texts) != 1:
            raise StructuredEquipmentFallback("group_source_conflict", {"group": key[1]})
        if len(optional_values) != 1:
            raise StructuredEquipmentFallback("group_optional_conflict", {"group": key[1]})
        if len(quantities) != 1:
            raise StructuredEquipmentFallback("group_quantity_conflict", {"group": key[1]})

        metadata = {}
        for member in members:
            for metadata_key, value in (member.get("source_metadata") or {}).items():
                if metadata_key in metadata and metadata[metadata_key] != value:
                    raise StructuredEquipmentFallback(
                        "group_metadata_conflict",
                        {"group": key[1], "field": metadata_key},
                    )
                metadata[metadata_key] = deepcopy(value)
        options = [
            deepcopy(option)
            for member in members
            for option in member.get("options", [])
        ]
        if not options:
            raise StructuredEquipmentFallback("missing_options", {"group": key[1]})
        connector = str(members[0].get("connector") or "single")
        if len(members) > 1 or str(key[1]).startswith("phase3c1:"):
            connector = "and"
        projection.append({
            "source_text": next(iter(source_texts)),
            "optional": next(iter(optional_values)),
            "quantity": next(iter(quantities)),
            "sort_order": min(int(row.get("sort_order") or 0) for row in members),
            "connector": connector,
            "conjunction_group": key[1] if key[0] == "group" else "",
            "requirement_ids": [str(row.get("requirement_id") or "") for row in members],
            "source_metadata": metadata,
            "options": options,
        })
    return sorted(projection, key=lambda row: row["sort_order"])


def _legacy_row_optional(row):
    parsed = parse_equipment_list([row])
    if parsed:
        return bool(parsed[0].get("optional"))
    return truthy(row.get("optional") if isinstance(row, dict) else False)


def compatibility_equipment_rows(requirements, legacy_rows=None):
    """Return one compatibility row per authored source row.

    When legacy rows are supplied, they are the presentation source of truth.
    The structured hierarchy must match them one-for-one before exact deep
    copies are returned. This preserves arbitrary recipe image metadata and
    avoids leaking master-equipment images.
    """
    semantic_rows = semantic_equipment_projection(requirements)
    if legacy_rows is not None:
        legacy_rows = legacy_rows if isinstance(legacy_rows, list) else []
        if len(semantic_rows) != len(legacy_rows):
            raise StructuredEquipmentFallback(
                "row_count_mismatch",
                {"structured": len(semantic_rows), "legacy": len(legacy_rows)},
            )
        for index, (semantic, legacy) in enumerate(zip(semantic_rows, legacy_rows)):
            if equipment_source_text(legacy) != str(semantic.get("source_text") or ""):
                raise StructuredEquipmentFallback(
                    "wording_or_order_mismatch", {"index": index}
                )
            legacy_optional = _legacy_row_optional(legacy)
            if legacy_optional != bool(semantic.get("optional")):
                raise StructuredEquipmentFallback("optional_mismatch", {"index": index})
        return deepcopy(legacy_rows)

    rows = []
    for semantic in semantic_rows:
        text = str(semantic.get("source_text") or "").strip()
        if text:
            rows.append({"equipment": text, "text": text, "optional": bool(semantic["optional"])})
    return rows


def compare_legacy_and_structured_rows(legacy_rows, projected_rows, semantic_rows=None):
    legacy_rows = legacy_rows if isinstance(legacy_rows, list) else []
    projected_rows = projected_rows if isinstance(projected_rows, list) else []
    semantic_rows = semantic_rows if isinstance(semantic_rows, list) else []
    metrics = {
        "legacy_row_count": len(legacy_rows),
        "structured_row_count": len(projected_rows),
        "row_count_difference": len(projected_rows) - len(legacy_rows),
        "wording_order_differences": 0,
        "optional_differences": 0,
        "image_differences": 0,
        "connector_differences": 0,
        "attribute_differences": 0,
        "attribute_validation_errors": 0,
    }
    image_keys = {
        "equipment_image_url", "equipment_image_path", "equipment_image_generated_at",
        "equipment_image_prompt", "image_url", "image_path",
    }
    for legacy, projected in zip(legacy_rows, projected_rows):
        if equipment_source_text(legacy) != equipment_source_text(projected):
            metrics["wording_order_differences"] += 1
        if _legacy_row_optional(legacy) != bool(
            projected.get("optional") if isinstance(projected, dict) else False
        ):
            metrics["optional_differences"] += 1
        if isinstance(legacy, dict) and isinstance(projected, dict):
            if any(legacy.get(key) != projected.get(key) for key in image_keys):
                metrics["image_differences"] += 1
    parsed_legacy = semantic_equipment_projection(parse_equipment_list(legacy_rows)) if legacy_rows else []
    for legacy_semantic, structured_semantic in zip(parsed_legacy, semantic_rows):
        if legacy_semantic.get("connector") != structured_semantic.get("connector"):
            metrics["connector_differences"] += 1
    return metrics


def _sync_status(connection, user_id, recipe_id):
    row = connection.execute(
        """
        SELECT user_id, recipe_id, source_hash, requirement_count,
               parser_version, synced_at
          FROM recipe_equipment_requirement_sync
         WHERE user_id = ? AND recipe_id = ?
        """,
        (user_id, recipe_id),
    ).fetchone()
    return dict(row) if row else None


def structured_equipment_read_result(
    connection,
    user_id,
    recipe_id,
    recipe_data,
    *,
    require_sync=True,
    expected_pending_fingerprint="",
):
    started = time.perf_counter()
    legacy_rows = (
        recipe_data.get("equipment", [])
        if isinstance(recipe_data, dict) and isinstance(recipe_data.get("equipment"), list)
        else []
    )
    result = {
        "eligible": False,
        "fallback_reason": "invalid_structured_data",
        "equipment": legacy_rows,
        "semantic_rows": [],
        "metrics": {},
        "pending_identifier_fingerprint": "",
    }
    semantic_rows = []
    candidate_rows = []
    try:
        requirements = load_structured_equipment_requirements(
            connection, user_id, recipe_id, require_ready=False
        )
        pending_fingerprint = _pending_identifier_fingerprint(requirements)
        result["pending_identifier_fingerprint"] = pending_fingerprint
        semantic_rows = semantic_equipment_projection(requirements)
        candidate_rows = compatibility_equipment_rows(requirements)
        result["semantic_rows"] = semantic_rows
        if expected_pending_fingerprint and pending_fingerprint != expected_pending_fingerprint:
            raise StructuredEquipmentFallback("pending_set_changed")
        for requirement in requirements:
            if str(requirement.get("review_status") or "") != "ready":
                raise StructuredEquipmentFallback(
                    "pending_requirement",
                    {"requirement_id": requirement.get("requirement_id")},
                )
            for option in requirement.get("options", []):
                if str(option.get("review_status") or "") != "ready":
                    raise StructuredEquipmentFallback(
                        "pending_option", {"option_id": option.get("option_id")}
                    )
        if require_sync:
            sync = _sync_status(connection, user_id, recipe_id)
            if sync is None:
                raise StructuredEquipmentFallback("missing_sync")
            if str(sync.get("source_hash") or "") != equipment_source_hash(recipe_data):
                raise StructuredEquipmentFallback("stale_sync")
            if str(sync.get("parser_version") or "") != PARSER_VERSION:
                raise StructuredEquipmentFallback("stale_parser_version")
            if int(sync.get("requirement_count") or 0) != len(requirements):
                raise StructuredEquipmentFallback("sync_count_mismatch")
        projected_rows = compatibility_equipment_rows(requirements, legacy_rows=legacy_rows)
        result.update({
            "eligible": True,
            "fallback_reason": "",
            "equipment": projected_rows,
            "semantic_rows": semantic_rows,
            "pending_identifier_fingerprint": pending_fingerprint,
            "metrics": compare_legacy_and_structured_rows(
                legacy_rows, projected_rows, semantic_rows
            ),
        })
    except StructuredEquipmentFallback as exc:
        result["fallback_reason"] = exc.reason
        result["fallback_details"] = exc.details
        result["metrics"] = compare_legacy_and_structured_rows(
            legacy_rows, candidate_rows, semantic_rows
        )
        if "attributes_json" in str(exc.details.get("field") or ""):
            result["metrics"]["attribute_validation_errors"] = 1
    except (sqlite3.DatabaseError, TypeError, ValueError) as exc:
        result["fallback_reason"] = "unreadable_structured_data"
        result["fallback_details"] = {"error_type": type(exc).__name__}
        result["metrics"] = compare_legacy_and_structured_rows(legacy_rows, [], [])
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


def emit_structured_equipment_event(event, **fields):
    payload = {"event": str(event or "structured_equipment"), **fields}
    LOGGER.info("structured_equipment_observability %s", _canonical_json(payload))
    return payload


@contextmanager
def _readonly_master_connection():
    from PushShoppingList.services import recipe_master_data_service as master_data

    db_path = master_data.recipe_master_db_path()
    if not db_path.is_file():
        yield None
        return
    with master_data.RECIPE_MASTER_DB_LOCK:
        connection = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=30
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            connection.close()


def apply_structured_equipment_read(
    recipe_url,
    recipe_data,
    *,
    user_id=None,
    connection=None,
    consumer="recipe_output",
):
    """Shadow and optionally select structured rows; flags-off is an exact no-op."""
    from PushShoppingList.services import recipe_master_data_service as master_data

    user_id = master_data.scoped_recipe_user_id(user_id)
    shadow_enabled = structured_equipment_shadow_enabled(user_id)
    read_enabled = structured_equipment_read_enabled(user_id)
    if not isinstance(recipe_data, dict) or not (shadow_enabled or read_enabled):
        return recipe_data
    recipe_id = master_data.recipe_id_for_url(recipe_url)

    def resolve(active_connection):
        if active_connection is None:
            return {
                "eligible": False,
                "fallback_reason": "database_unavailable",
                "equipment": recipe_data.get("equipment", []),
                "metrics": {},
                "latency_ms": 0,
            }
        return structured_equipment_read_result(
            active_connection, user_id, recipe_id, recipe_data, require_sync=True
        )

    if connection is not None:
        result = resolve(connection)
    else:
        with _readonly_master_connection() as managed_connection:
            result = resolve(managed_connection)

    emit_structured_equipment_event(
        "shadow_compare" if shadow_enabled else "read_decision",
        user_id=user_id,
        recipe_id=recipe_id,
        consumer=consumer,
        eligible=bool(result.get("eligible")),
        fallback_reason=str(result.get("fallback_reason") or ""),
        tenant_violations=int(
            str(result.get("fallback_reason") or "") == "tenant_violation"
        ),
        pending_set_changed=bool(
            str(result.get("fallback_reason") or "") == "pending_set_changed"
        ),
        pending_identifier_fingerprint=str(
            result.get("pending_identifier_fingerprint") or ""
        ),
        latency_ms=result.get("latency_ms", 0),
        **(result.get("metrics") or {}),
    )
    if not read_enabled or not result.get("eligible"):
        return recipe_data
    projected = deepcopy(recipe_data)
    projected["equipment"] = deepcopy(result["equipment"])
    return projected


def structured_equipment_review_queue(user_id, *, connection=None):
    """Read the actual pending structured queue for exactly one tenant."""
    user_id = str(user_id or "").strip()
    if not user_id:
        return []

    def load(active_connection):
        if active_connection is None or not structured_equipment_schema_available(active_connection):
            return []
        recipe_rows = active_connection.execute(
            """
            SELECT DISTINCT recipe_id
              FROM recipe_equipment_requirements
             WHERE user_id = ?
               AND (
                    review_status <> 'ready'
                    OR EXISTS (
                        SELECT 1 FROM recipe_equipment_options o
                         WHERE o.requirement_id = recipe_equipment_requirements.id
                           AND o.review_status <> 'ready'
                    )
               )
             ORDER BY recipe_id
            """,
            (user_id,),
        ).fetchall()
        queue = []
        for recipe_row in recipe_rows:
            recipe_id = str(recipe_row[0])
            requirements = load_structured_equipment_requirements(
                active_connection, user_id, recipe_id, require_ready=False
            )
            for requirement in requirements:
                pending_options = [
                    option for option in requirement["options"]
                    if option.get("review_status") != "ready"
                ]
                if requirement.get("review_status") == "ready" and not pending_options:
                    continue
                queue.append({
                    "user_id": user_id,
                    "recipe_id": recipe_id,
                    "equipment_id": requirement["requirement_id"],
                    "name": requirement["source_text"],
                    "usage_count": 1,
                    "requirement_id": requirement["requirement_id"],
                    "source_text": requirement["source_text"],
                    "optional": bool(requirement["optional"]),
                    "quantity": requirement["quantity"],
                    "connector": requirement["connector"],
                    "conjunction_group": requirement["conjunction_group"],
                    "review_status": requirement["review_status"],
                    "requirements": [{
                        **deepcopy(requirement),
                        "parse_confidence": float(
                            requirement.get("parse_confidence") or 0
                        ),
                    }],
                    "options": deepcopy(requirement["options"]),
                })
        return queue

    if connection is not None:
        return load(connection)
    with _readonly_master_connection() as managed_connection:
        return load(managed_connection)


def _column_names(connection, table_name):
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }


def structured_equipment_schema_available(connection):
    required = {
        "equipment_aliases",
        "recipe_equipment_requirements",
        "recipe_equipment_options",
        "equipment_normalization_reviews",
        "equipment_requirement_migration_runs",
        "equipment_requirement_migration_map",
        "recipe_equipment_requirement_sync",
    }
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return required.issubset(existing)


def ensure_structured_equipment_schema(
    connection,
    *,
    authorized=False,
    migration_token="",
):
    """Create the additive schema only after an explicit caller authorization."""
    migration_authorized = (
        authorized and str(migration_token or "") == PHASE3A_MIGRATION_TOKEN
    )
    if not authorized or not (
        structured_equipment_schema_writes_enabled() or migration_authorized
    ):
        raise PermissionError(
            "Structured equipment schema writes are locked. Set "
            "RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED=true and pass authorized=True."
        )
    if "equipment" not in {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }:
        raise RuntimeError("The legacy equipment table must exist before adding the structured schema.")

    equipment_columns = _column_names(connection, "equipment")
    additions = {
        "canonical_name": "TEXT NOT NULL DEFAULT ''",
        "canonical_key": "TEXT NOT NULL DEFAULT ''",
        "description": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "image_provenance_json": "TEXT NOT NULL DEFAULT '{}'",
        "merged_into_id": "INTEGER DEFAULT NULL",
    }
    for column_name, definition in additions.items():
        if column_name not in equipment_columns:
            connection.execute(
                f'ALTER TABLE equipment ADD COLUMN "{column_name}" {definition}'
            )

    connection.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_user_id_id
            ON equipment(user_id, id);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_user_canonical_key
            ON equipment(user_id, canonical_key)
            WHERE canonical_key <> '' AND status <> 'merged';

        CREATE TABLE IF NOT EXISTS equipment_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL,
            alias_name TEXT NOT NULL,
            alias_key TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, alias_key),
            FOREIGN KEY(user_id, equipment_id)
                REFERENCES equipment(user_id, id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS recipe_equipment_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            source_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            quantity TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            connector TEXT NOT NULL DEFAULT 'single',
            conjunction_group TEXT NOT NULL DEFAULT '',
            parse_confidence REAL NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'pending',
            parser_version TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, recipe_id, requirement_id),
            UNIQUE(user_id, id)
        );

        CREATE TABLE IF NOT EXISTS recipe_equipment_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            requirement_id INTEGER NOT NULL,
            equipment_id INTEGER DEFAULT NULL,
            source_option_text TEXT NOT NULL DEFAULT '',
            canonical_name TEXT NOT NULL DEFAULT '',
            canonical_key TEXT NOT NULL DEFAULT '',
            option_kind TEXT NOT NULL DEFAULT 'equipment',
            attributes_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            matched_alias_id INTEGER DEFAULT NULL,
            match_type TEXT NOT NULL DEFAULT '',
            match_confidence REAL NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(requirement_id, option_id),
            FOREIGN KEY(user_id, requirement_id)
                REFERENCES recipe_equipment_requirements(user_id, id) ON DELETE CASCADE,
            FOREIGN KEY(user_id, equipment_id)
                REFERENCES equipment(user_id, id) ON DELETE RESTRICT,
            FOREIGN KEY(matched_alias_id)
                REFERENCES equipment_aliases(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS equipment_normalization_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_record_id TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL,
            proposal_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            decision TEXT NOT NULL DEFAULT '',
            decision_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, source_kind, source_record_id, source_text)
        );

        CREATE TABLE IF NOT EXISTS equipment_requirement_migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT NOT NULL UNIQUE,
            mode TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            summary_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS equipment_requirement_migration_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_run_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            legacy_recipe_equipment_id INTEGER DEFAULT NULL,
            legacy_equipment_id INTEGER DEFAULT NULL,
            requirement_id TEXT NOT NULL DEFAULT '',
            option_id TEXT NOT NULL DEFAULT '',
            decision TEXT NOT NULL DEFAULT '',
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(migration_run_id, user_id, recipe_id, legacy_recipe_equipment_id, option_id),
            FOREIGN KEY(migration_run_id)
                REFERENCES equipment_requirement_migration_runs(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS recipe_equipment_requirement_sync (
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '',
            requirement_count INTEGER NOT NULL DEFAULT 0,
            parser_version TEXT NOT NULL DEFAULT '',
            synced_at TEXT NOT NULL,
            PRIMARY KEY(user_id, recipe_id)
        );

        CREATE INDEX IF NOT EXISTS idx_equipment_aliases_equipment
            ON equipment_aliases(user_id, equipment_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_requirements_recipe
            ON recipe_equipment_requirements(user_id, recipe_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_equipment_options_requirement
            ON recipe_equipment_options(user_id, requirement_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_equipment_options_equipment
            ON recipe_equipment_options(user_id, equipment_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_reviews_status
            ON equipment_normalization_reviews(user_id, status, id);
        """
    )
    return True


def replace_recipe_requirements(
    connection,
    user_id,
    recipe_id,
    requirements,
    *,
    authorized=False,
    migration_token="",
):
    migration_authorized = (
        authorized and str(migration_token or "") == PHASE3A_MIGRATION_TOKEN
    )
    if not authorized or not (
        structured_equipment_write_enabled(user_id) or migration_authorized
    ):
        raise PermissionError(
            "Structured equipment writes are locked. Set "
            "RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED=true and pass authorized=True."
        )
    if not structured_equipment_schema_available(connection):
        raise RuntimeError("Structured equipment schema is not installed.")

    user_id = str(user_id or "").strip()
    recipe_id = str(recipe_id or "").strip()
    now = _utc_now_iso()
    connection.execute(
        "DELETE FROM recipe_equipment_requirements WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id),
    )
    for requirement in requirements if isinstance(requirements, list) else []:
        cursor = connection.execute(
            """
            INSERT INTO recipe_equipment_requirements (
                requirement_id, user_id, recipe_id, source_text, optional,
                quantity, notes, sort_order, connector, conjunction_group,
                parse_confidence, review_status, parser_version, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requirement.get("requirement_id"), user_id, recipe_id,
                requirement.get("source_text", ""), int(bool(requirement.get("optional"))),
                requirement.get("quantity", ""), requirement.get("notes", ""),
                int(requirement.get("sort_order") or 0), requirement.get("connector", "single"),
                requirement.get("conjunction_group", ""),
                float(requirement.get("parse_confidence") or 0),
                requirement.get("review_status", "pending"),
                requirement.get("parser_version", PARSER_VERSION),
                json.dumps(requirement.get("source_metadata") or {}, sort_keys=True),
                now, now,
            ),
        )
        requirement_row_id = int(cursor.lastrowid)
        for option in requirement.get("options", []):
            connection.execute(
                """
                INSERT INTO recipe_equipment_options (
                    option_id, user_id, requirement_id, equipment_id,
                    source_option_text, canonical_name, canonical_key, option_kind,
                    attributes_json, notes, sort_order, matched_alias_id, match_type,
                    match_confidence, review_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    option.get("option_id"), user_id, requirement_row_id,
                    option.get("equipment_id"), option.get("source_option_text", ""),
                    option.get("canonical_name", ""), option.get("canonical_key", ""),
                    option.get("option_kind", "unresolved"),
                    json.dumps(option.get("attributes") or {}, sort_keys=True),
                    option.get("notes", ""), int(option.get("sort_order") or 0),
                    option.get("matched_alias_id"), option.get("match_type", ""),
                    float(option.get("match_confidence") or 0),
                    option.get("review_status", "pending"), now, now,
                ),
            )
    return requirement_summary(requirements)


def _deterministic_equipment_match(
    connection, user_id, canonical_key, *, excluded_equipment_ids=None
):
    canonical_key = normalized_equipment_key(canonical_key)
    if not canonical_key:
        return None
    rows = connection.execute(
        """
        SELECT e.id AS equipment_id, NULL AS alias_id, 'exact_same_tenant' AS match_type
          FROM equipment e
         WHERE e.user_id = ?
           AND e.status = 'active'
           AND (e.canonical_key = ? OR e.normalized_name = ?)
        UNION ALL
        SELECT e.id AS equipment_id, a.id AS alias_id, 'alias_same_tenant' AS match_type
          FROM equipment_aliases a
          JOIN equipment e
            ON e.id = a.equipment_id AND e.user_id = a.user_id
         WHERE a.user_id = ? AND a.alias_key = ?
           AND a.status = 'active' AND e.status = 'active'
        """,
        (user_id, canonical_key, canonical_key, user_id, canonical_key),
    ).fetchall()
    excluded_equipment_ids = {
        int(value) for value in (excluded_equipment_ids or set())
    }
    targets = {}
    for row in rows:
        values = dict(row)
        equipment_id = int(values["equipment_id"])
        if equipment_id in excluded_equipment_ids:
            continue
        current = targets.get(equipment_id)
        if current is None or values.get("alias_id") is not None:
            targets[equipment_id] = values
    if len(targets) != 1:
        return None
    return next(iter(targets.values()))


def _new_option_values(
    connection, user_id, option, *, excluded_equipment_ids=None
):
    values = {
        "equipment_id": None,
        "canonical_name": str(option.get("canonical_name") or ""),
        "canonical_key": str(option.get("canonical_key") or ""),
        "option_kind": str(option.get("option_kind") or "unresolved"),
        "attributes_json": _canonical_json(option.get("attributes") or {}),
        "notes": str(option.get("notes") or ""),
        "matched_alias_id": None,
        "match_type": str(option.get("match_type") or ""),
        "match_confidence": float(option.get("match_confidence") or 0),
        "review_status": "pending",
    }
    if values["option_kind"] == "equipment":
        match = _deterministic_equipment_match(
            connection,
            user_id,
            values["canonical_key"],
            excluded_equipment_ids=excluded_equipment_ids,
        )
        if match:
            values.update({
                "equipment_id": int(match["equipment_id"]),
                "matched_alias_id": match.get("alias_id"),
                "match_type": str(match["match_type"]),
                "match_confidence": 1.0,
                "review_status": "ready",
            })
    elif values["option_kind"] in {"supply", "facility", "instruction"}:
        values.update({
            "match_type": "deterministic_classification",
            "match_confidence": max(values["match_confidence"], 0.95),
            "review_status": "ready",
        })
    return values


def _existing_structured_rows(connection, user_id, recipe_id):
    requirements = [
        dict(row) for row in connection.execute(
            """
            SELECT * FROM recipe_equipment_requirements
             WHERE user_id = ? AND recipe_id = ?
             ORDER BY sort_order, id
            """,
            (user_id, recipe_id),
        ).fetchall()
    ]
    options = [
        dict(row) for row in connection.execute(
            """
            SELECT o.*
              FROM recipe_equipment_options o
              JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
             WHERE r.user_id = ? AND r.recipe_id = ?
             ORDER BY r.sort_order, r.id, o.sort_order, o.id
            """,
            (user_id, recipe_id),
        ).fetchall()
    ]
    by_requirement = {}
    for option in options:
        by_requirement.setdefault(int(option["requirement_id"]), []).append(option)
    return requirements, by_requirement


def _update_if_changed(connection, table, row_id, current, values, now):
    changed = {
        key: value for key, value in values.items()
        if current.get(key) != value
    }
    if not changed:
        return False
    assignments = ", ".join(f'"{key}" = ?' for key in changed)
    connection.execute(
        f'UPDATE "{table}" SET {assignments}, updated_at = ? WHERE id = ?',
        (*changed.values(), now, int(row_id)),
    )
    current.update(changed)
    current["updated_at"] = now
    return True


def _upsert_pending_review(connection, user_id, recipe_id, requirement, now):
    pending_options = [
        option for option in requirement.get("options", [])
        if option.get("review_status") != "ready"
    ]
    if not pending_options:
        return 0
    source_record_id = f"{recipe_id}#{requirement['requirement_id']}"
    proposal = {
        "requirement_id": requirement["requirement_id"],
        "connector": requirement.get("connector", "single"),
        "options": [
            {
                "option_id": option.get("option_id"),
                "source_option_text": option.get("source_option_text"),
                "canonical_name": option.get("canonical_name"),
                "canonical_key": option.get("canonical_key"),
                "option_kind": option.get("option_kind"),
            }
            for option in pending_options
        ],
    }
    existing = connection.execute(
        """
        SELECT id, status FROM equipment_normalization_reviews
         WHERE user_id = ? AND source_kind = 'structured_dual_write'
           AND source_record_id = ? AND source_text = ?
        """,
        (user_id, source_record_id, requirement["source_text"]),
    ).fetchone()
    if existing:
        # A prior owner decision remains audit history and is never reopened.
        if str(existing["status"] or "") != "pending":
            return 0
        connection.execute(
            """
            UPDATE equipment_normalization_reviews
               SET proposal_json = ?, confidence = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                _canonical_json(proposal),
                float(requirement.get("parse_confidence") or 0),
                now,
                int(existing["id"]),
            ),
        )
        return 0
    connection.execute(
        """
        INSERT INTO equipment_normalization_reviews (
            user_id, source_kind, source_record_id, source_text,
            proposal_json, confidence, status, decision, decision_note,
            created_at, updated_at
        ) VALUES (?, 'structured_dual_write', ?, ?, ?, ?, 'pending', '', '', ?, ?)
        """,
        (
            user_id,
            source_record_id,
            requirement["source_text"],
            _canonical_json(proposal),
            float(requirement.get("parse_confidence") or 0),
            now,
            now,
        ),
    )
    return 1


def reconcile_recipe_requirements(
    connection,
    user_id,
    recipe_id,
    recipe_data,
    *,
    excluded_equipment_ids=None,
    failure_injector=None,
):
    """Incrementally dual-write one legacy recipe within the caller transaction."""
    user_id = str(user_id or "").strip()
    recipe_id = str(recipe_id or "").strip()
    if not structured_equipment_dual_write_enabled(user_id):
        return {"enabled": False, "changed": False, "outcome": "flags_off_noop"}
    if not user_id or not recipe_id:
        raise ValueError("Recipe and tenant identities are required for equipment dual write.")
    if not structured_equipment_schema_available(connection):
        raise RuntimeError("Structured equipment schema is unavailable for dual write.")

    parsed = requirements_from_recipe_data(recipe_data)
    source_hash = equipment_source_hash(recipe_data)
    now = _utc_now_iso()
    savepoint = "structured_equipment_dual_write"
    connection.execute(f"SAVEPOINT {savepoint}")
    summary = {
        "enabled": True,
        "changed": False,
        "requirements_inserted": 0,
        "requirements_updated": 0,
        "requirements_deleted": 0,
        "options_inserted": 0,
        "options_updated": 0,
        "options_deleted": 0,
        "approved_options_preserved": 0,
        "reviews_created": 0,
        "outcome": "staged",
    }
    try:
        if callable(failure_injector):
            failure_injector("before_reconcile")
        existing_requirements, existing_options = _existing_structured_rows(
            connection, user_id, recipe_id
        )
        by_logical_id = {
            str(row["requirement_id"]): row for row in existing_requirements
        }
        used_requirement_rows = set()
        parsed_source_texts = {str(row.get("source_text") or "") for row in parsed}

        materialized = []
        for parsed_requirement in parsed:
            logical_id = str(parsed_requirement.get("requirement_id") or "")
            current = by_logical_id.get(logical_id)
            if current is None:
                candidates = [
                    row for row in existing_requirements
                    if int(row["id"]) not in used_requirement_rows
                    and str(row.get("source_text") or "") == str(parsed_requirement.get("source_text") or "")
                    and not _json_object(
                        row.get("metadata_json"),
                        field_name=f"requirement:{row.get('requirement_id')}:metadata_json",
                    ).get("derived_from_requirement_id")
                ]
                current = candidates[0] if len(candidates) == 1 else None

            parser_metadata = deepcopy(parsed_requirement.get("source_metadata") or {})
            if current is None:
                cursor = connection.execute(
                    """
                    INSERT INTO recipe_equipment_requirements (
                        requirement_id, user_id, recipe_id, source_text, optional,
                        quantity, notes, sort_order, connector, conjunction_group,
                        parse_confidence, review_status, parser_version, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        logical_id, user_id, recipe_id,
                        str(parsed_requirement.get("source_text") or ""),
                        int(bool(parsed_requirement.get("optional"))),
                        str(parsed_requirement.get("quantity") or ""),
                        str(parsed_requirement.get("notes") or ""),
                        int(parsed_requirement.get("sort_order") or 0),
                        str(parsed_requirement.get("connector") or "single"),
                        str(parsed_requirement.get("conjunction_group") or ""),
                        float(parsed_requirement.get("parse_confidence") or 0),
                        PARSER_VERSION, _canonical_json(parser_metadata), now, now,
                    ),
                )
                current = dict(connection.execute(
                    "SELECT * FROM recipe_equipment_requirements WHERE id = ?",
                    (int(cursor.lastrowid),),
                ).fetchone())
                existing_requirements.append(current)
                existing_options[int(current["id"])] = []
                summary["requirements_inserted"] += 1
            else:
                existing_metadata = _json_object(
                    current.get("metadata_json"),
                    field_name=f"requirement:{current.get('requirement_id')}:metadata_json",
                )
                recipe_image_keys = {
                    "equipment_image_url", "equipment_image_path",
                    "equipment_image_generated_at", "equipment_image_prompt",
                    "image_url", "image_path",
                }
                preserved_metadata = {
                    key: value for key, value in existing_metadata.items()
                    if key not in recipe_image_keys
                }
                next_metadata = {**preserved_metadata, **parser_metadata}
                next_metadata_json = (
                    current.get("metadata_json")
                    if next_metadata == existing_metadata
                    else _canonical_json(next_metadata)
                )
                updated = _update_if_changed(
                    connection,
                    "recipe_equipment_requirements",
                    current["id"],
                    current,
                    {
                        "source_text": str(parsed_requirement.get("source_text") or ""),
                        "optional": int(bool(parsed_requirement.get("optional"))),
                        "quantity": str(parsed_requirement.get("quantity") or ""),
                        "notes": str(parsed_requirement.get("notes") or ""),
                        "sort_order": int(parsed_requirement.get("sort_order") or 0),
                        "parse_confidence": float(parsed_requirement.get("parse_confidence") or 0),
                        "metadata_json": next_metadata_json,
                    },
                    now,
                )
                summary["requirements_updated"] += int(updated)

            used_requirement_rows.add(int(current["id"]))
            option_rows = existing_options.setdefault(int(current["id"]), [])
            by_option_id = {str(row["option_id"]): row for row in option_rows}
            used_option_rows = set()
            normalized_options = []
            for parsed_option in parsed_requirement.get("options", []):
                option_id = str(parsed_option.get("option_id") or "")
                option_row = by_option_id.get(option_id)
                if option_row is None:
                    candidates = [
                        row for row in option_rows
                        if int(row["id"]) not in used_option_rows
                        and str(row.get("source_option_text") or "")
                        == str(parsed_option.get("source_option_text") or "")
                    ]
                    option_row = candidates[0] if len(candidates) == 1 else None
                if option_row is None:
                    resolved = _new_option_values(
                        connection,
                        user_id,
                        parsed_option,
                        excluded_equipment_ids=excluded_equipment_ids,
                    )
                    cursor = connection.execute(
                        """
                        INSERT INTO recipe_equipment_options (
                            option_id, user_id, requirement_id, equipment_id,
                            source_option_text, canonical_name, canonical_key, option_kind,
                            attributes_json, notes, sort_order, matched_alias_id, match_type,
                            match_confidence, review_status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            option_id, user_id, int(current["id"]),
                            resolved["equipment_id"],
                            str(parsed_option.get("source_option_text") or ""),
                            resolved["canonical_name"], resolved["canonical_key"],
                            resolved["option_kind"], resolved["attributes_json"],
                            resolved["notes"], int(parsed_option.get("sort_order") or 0),
                            resolved["matched_alias_id"], resolved["match_type"],
                            resolved["match_confidence"], resolved["review_status"], now, now,
                        ),
                    )
                    option_row = dict(connection.execute(
                        "SELECT * FROM recipe_equipment_options WHERE id = ?",
                        (int(cursor.lastrowid),),
                    ).fetchone())
                    option_rows.append(option_row)
                    summary["options_inserted"] += 1
                else:
                    # The source option is unchanged: all approved canonical,
                    # classification, alias, attribute, and target fields survive.
                    updated = _update_if_changed(
                        connection,
                        "recipe_equipment_options",
                        option_row["id"],
                        option_row,
                        {
                            "source_option_text": str(parsed_option.get("source_option_text") or ""),
                            "sort_order": int(parsed_option.get("sort_order") or 0),
                        },
                        now,
                    )
                    summary["options_updated"] += int(updated)
                    summary["approved_options_preserved"] += int(
                        str(option_row.get("review_status") or "") == "ready"
                    )
                used_option_rows.add(int(option_row["id"]))
                normalized_options.append(option_row)

            # Non-parser options are approved structural additions. They remain
            # attached while the authored source row itself remains unchanged.
            for option_row in option_rows:
                if int(option_row["id"]) not in used_option_rows:
                    normalized_options.append(option_row)
                    summary["approved_options_preserved"] += int(
                        str(option_row.get("review_status") or "") == "ready"
                    )

            requirement_status = (
                "ready"
                if normalized_options
                and all(str(row.get("review_status") or "") == "ready" for row in normalized_options)
                else "pending"
            )
            if _update_if_changed(
                connection,
                "recipe_equipment_requirements",
                current["id"],
                current,
                {"review_status": requirement_status},
                now,
            ):
                summary["requirements_updated"] += 1
            materialized.append({
                **parsed_requirement,
                "requirement_id": str(current["requirement_id"]),
                "review_status": requirement_status,
                "options": [
                    {
                        **row,
                        "option_id": str(row["option_id"]),
                    }
                    for row in normalized_options
                ],
            })

        # Preserve Phase 3C-1 derived requirements only while their authored
        # source row still exists. Removed legacy rows remove their projections.
        for current in existing_requirements:
            row_id = int(current["id"])
            if row_id in used_requirement_rows:
                continue
            metadata = _json_object(
                current.get("metadata_json"),
                field_name=f"requirement:{current.get('requirement_id')}:metadata_json",
            )
            if metadata.get("derived_from_requirement_id") and str(
                current.get("source_text") or ""
            ) in parsed_source_texts:
                used_requirement_rows.add(row_id)
                continue
            summary["options_deleted"] += len(existing_options.get(row_id, []))
            connection.execute(
                "DELETE FROM recipe_equipment_requirements WHERE id = ? AND user_id = ?",
                (row_id, user_id),
            )
            connection.execute(
                """
                UPDATE equipment_normalization_reviews
                   SET status = 'resolved', decision = 'source_requirement_removed',
                       updated_at = ?
                 WHERE user_id = ? AND source_kind = 'structured_dual_write'
                   AND source_record_id = ? AND status = 'pending'
                """,
                (
                    now,
                    user_id,
                    f"{recipe_id}#{current['requirement_id']}",
                ),
            )
            summary["requirements_deleted"] += 1

        if callable(failure_injector):
            failure_injector("before_reviews")
        for requirement in materialized:
            summary["reviews_created"] += _upsert_pending_review(
                connection, user_id, recipe_id, requirement, now
            )

        actual_count = int(connection.execute(
            """
            SELECT COUNT(*) FROM recipe_equipment_requirements
             WHERE user_id = ? AND recipe_id = ?
            """,
            (user_id, recipe_id),
        ).fetchone()[0])
        existing_sync = _sync_status(connection, user_id, recipe_id)
        next_sync = {
            "source_hash": source_hash,
            "requirement_count": actual_count,
            "parser_version": PARSER_VERSION,
        }
        if existing_sync is None:
            connection.execute(
                """
                INSERT INTO recipe_equipment_requirement_sync (
                    user_id, recipe_id, source_hash, requirement_count,
                    parser_version, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, recipe_id, source_hash, actual_count, PARSER_VERSION, now),
            )
            summary["changed"] = True
        elif any(existing_sync.get(key) != value for key, value in next_sync.items()):
            connection.execute(
                """
                UPDATE recipe_equipment_requirement_sync
                   SET source_hash = ?, requirement_count = ?, parser_version = ?, synced_at = ?
                 WHERE user_id = ? AND recipe_id = ?
                """,
                (source_hash, actual_count, PARSER_VERSION, now, user_id, recipe_id),
            )
            summary["changed"] = True

        change_keys = (
            "requirements_inserted", "requirements_updated", "requirements_deleted",
            "options_inserted", "options_updated", "options_deleted", "reviews_created",
        )
        summary["changed"] = summary["changed"] or any(summary[key] for key in change_keys)
        summary["outcome"] = "staged" if summary["changed"] else "idempotent_noop"
        if callable(failure_injector):
            failure_injector("before_release")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        emit_structured_equipment_event(
            "structured_write_transaction",
            user_id=user_id,
            recipe_id=recipe_id,
            outcome=summary["outcome"],
            changed=summary["changed"],
        )
        return summary
    except Exception as exc:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        emit_structured_equipment_event(
            "structured_write_transaction",
            user_id=user_id,
            recipe_id=recipe_id,
            outcome="rolled_back",
            error_type=type(exc).__name__,
        )
        raise


def move_structured_recipe_identity(connection, user_id, previous_recipe_id, recipe_id):
    user_id = str(user_id or "").strip()
    previous_recipe_id = str(previous_recipe_id or "").strip()
    recipe_id = str(recipe_id or "").strip()
    if not structured_equipment_dual_write_enabled(user_id):
        return {"enabled": False, "changed": False}
    if not previous_recipe_id or not recipe_id or previous_recipe_id == recipe_id:
        return {"enabled": True, "changed": False}
    collision = connection.execute(
        """
        SELECT 1 FROM recipe_equipment_requirements
         WHERE user_id = ? AND recipe_id = ? LIMIT 1
        """,
        (user_id, recipe_id),
    ).fetchone()
    sync_collision = _sync_status(connection, user_id, recipe_id)
    if collision or sync_collision:
        raise RuntimeError("Structured equipment identity destination already exists.")
    cursor = connection.execute(
        """
        UPDATE recipe_equipment_requirements SET recipe_id = ?, updated_at = ?
         WHERE user_id = ? AND recipe_id = ?
        """,
        (recipe_id, _utc_now_iso(), user_id, previous_recipe_id),
    )
    connection.execute(
        """
        UPDATE recipe_equipment_requirement_sync SET recipe_id = ?, synced_at = ?
         WHERE user_id = ? AND recipe_id = ?
        """,
        (recipe_id, _utc_now_iso(), user_id, previous_recipe_id),
    )
    reviews = connection.execute(
        """
        SELECT id, source_record_id FROM equipment_normalization_reviews
         WHERE user_id = ? AND source_kind = 'structured_dual_write'
           AND source_record_id LIKE ?
        """,
        (user_id, f"{previous_recipe_id}#%"),
    ).fetchall()
    for review in reviews:
        suffix = str(review["source_record_id"])[len(previous_recipe_id):]
        connection.execute(
            "UPDATE equipment_normalization_reviews SET source_record_id = ?, updated_at = ? WHERE id = ?",
            (f"{recipe_id}{suffix}", _utc_now_iso(), int(review["id"])),
        )
    return {"enabled": True, "changed": bool(cursor.rowcount), "moved": int(cursor.rowcount or 0)}


def delete_structured_recipe_requirements(connection, user_id, recipe_id):
    user_id = str(user_id or "").strip()
    recipe_id = str(recipe_id or "").strip()
    if not structured_equipment_dual_write_enabled(user_id):
        return {"enabled": False, "changed": False, "deleted": 0}
    cursor = connection.execute(
        "DELETE FROM recipe_equipment_requirements WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id),
    )
    connection.execute(
        "DELETE FROM recipe_equipment_requirement_sync WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id),
    )
    connection.execute(
        """
        UPDATE equipment_normalization_reviews
           SET status = 'resolved', decision = 'source_recipe_deleted', updated_at = ?
         WHERE user_id = ? AND source_kind = 'structured_dual_write'
           AND source_record_id LIKE ? AND status = 'pending'
        """,
        (_utc_now_iso(), user_id, f"{recipe_id}#%"),
    )
    return {
        "enabled": True,
        "changed": bool(cursor.rowcount),
        "deleted": int(cursor.rowcount or 0),
    }
