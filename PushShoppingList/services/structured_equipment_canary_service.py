"""Default-off authenticated HTTP canary support for structured equipment reads.

The correlation token created here is not an authentication credential. Every
route using it must first resolve the normal registered-user Flask session and
then pass that server-derived tenant into these helpers.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from itsdangerous import BadData, URLSafeSerializer

from PushShoppingList.services.equipment_normalization_service import PARSER_VERSION
from PushShoppingList.services import recipe_equipment_requirement_service as requirements


CANARY_FLAG = "RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_ENABLED"
CANARY_TENANTS_ENV = "RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_TENANTS"
CANARY_AUDIT_DIR_ENV = "RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_AUDIT_DIR"
CANARY_TOKEN_SALT = "structured-equipment-authenticated-canary-v1"
CANARY_TOKEN_VERSION = "phase4d-r2b-v1"
CANARY_TOKEN_TTL_SECONDS = 30 * 60
CANARY_PASS_COUNT = 6
CANARY_RECIPE_COUNT = 88
CANARY_SAMPLE_COUNT = CANARY_PASS_COUNT * CANARY_RECIPE_COUNT
CANARY_SELECTION_MODES = {"legacy_baseline", "structured_read"}
MAX_TOKEN_LENGTH = 4096
MAX_CLIENT_LATENCY_MS = 120_000.0
TRUE_VALUES = {"1", "true", "yes", "y", "on"}
RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
SHA256_PATTERN = re.compile(r"^[A-F0-9]{64}$")
AUDIT_LOCK = threading.Lock()

EXPECTED_CANARY_COUNTS = {
    "recipes": 88,
    "requirements": 306,
    "options": 337,
    "pending_requirements": 0,
    "pending_options": 0,
    "and_requirements": 30,
    "or_requirements": 31,
    "attributed_options": 84,
    "supply_options": 5,
    "facility_options": 2,
}

DIFFERENCE_METRICS = (
    "tenant_violations",
    "pending_set_changed",
    "row_count_difference",
    "wording_order_differences",
    "optional_differences",
    "quantity_differences",
    "image_differences",
    "connector_differences",
    "conjunction_group_differences",
    "classification_differences",
    "attribute_differences",
    "attribute_validation_errors",
    "metadata_differences",
    "response_body_differences",
)

RUN_EVENTS = {
    "run_started",
    "run_completed",
    "run_cancelled",
    "client_error",
}

STOP_REASONS = {
    "owner_started",
    "completed",
    "owner_cancelled",
    "http_error",
    "invalid_json",
    "server_rejected",
    "network_error",
    "unexpected_error",
}


class CanaryError(RuntimeError):
    """Base failure for a canary request that must fail closed."""


class CanaryInvariantError(CanaryError):
    """The staged tenant data does not match the bounded canary scope."""


class CanaryTokenError(CanaryError):
    """The correlation token is missing, invalid, expired, or out of scope."""


class CanaryAuditError(CanaryError):
    """Sanitized audit telemetry could not be safely recorded."""


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_json(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _sha256_text(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest().upper()


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def authenticated_canary_globally_enabled():
    return str(os.getenv(CANARY_FLAG, "") or "").strip().casefold() in TRUE_VALUES


def authenticated_canary_enabled(user_id):
    tenant = str(user_id or "").strip()
    allowlist = {
        item.strip()
        for item in str(os.getenv(CANARY_TENANTS_ENV, "") or "").split(",")
        if item.strip()
    }
    return bool(
        tenant
        and authenticated_canary_globally_enabled()
        and tenant in allowlist
        and "*" not in allowlist
    )


@contextmanager
def readonly_master_connection():
    from PushShoppingList.services import recipe_master_data_service as master_data

    db_path = master_data.recipe_master_db_path()
    if not db_path.is_file():
        raise CanaryInvariantError("The recipe master database is unavailable.")
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


def _scalar(connection, sql, parameters=()):
    return connection.execute(sql, parameters).fetchone()[0]


def _canary_counts(connection, tenant):
    counts = {
        "recipes": int(_scalar(
            connection,
            "SELECT COUNT(DISTINCT recipe_id) FROM recipe_equipment_requirements WHERE user_id = ?",
            (tenant,),
        )),
        "requirements": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE user_id = ?",
            (tenant,),
        )),
        "options": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_options WHERE user_id = ?",
            (tenant,),
        )),
        "pending_requirements": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE user_id = ? AND review_status <> 'ready'",
            (tenant,),
        )),
        "pending_options": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_options WHERE user_id = ? AND review_status <> 'ready'",
            (tenant,),
        )),
        "and_requirements": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE user_id = ? AND connector = 'and'",
            (tenant,),
        )),
        "or_requirements": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE user_id = ? AND connector = 'or'",
            (tenant,),
        )),
        "attributed_options": int(_scalar(
            connection,
            """
            SELECT COUNT(*) FROM recipe_equipment_options
             WHERE user_id = ? AND trim(COALESCE(attributes_json, '')) NOT IN ('', '{}')
            """,
            (tenant,),
        )),
        "supply_options": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_options WHERE user_id = ? AND option_kind = 'supply'",
            (tenant,),
        )),
        "facility_options": int(_scalar(
            connection,
            "SELECT COUNT(*) FROM recipe_equipment_options WHERE user_id = ? AND option_kind = 'facility'",
            (tenant,),
        )),
    }
    if counts != EXPECTED_CANARY_COUNTS:
        raise CanaryInvariantError(
            f"Canary count drift: expected={EXPECTED_CANARY_COUNTS}, actual={counts}"
        )
    return counts


def _verify_tenant_boundaries(connection, tenant):
    checks = {
        "option_requirement": """
            SELECT COUNT(*)
              FROM recipe_equipment_options o
              JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
             WHERE r.user_id = ? AND o.user_id <> r.user_id
        """,
        "option_equipment": """
            SELECT COUNT(*)
              FROM recipe_equipment_options o
              JOIN equipment e ON e.id = o.equipment_id
             WHERE o.user_id = ? AND e.user_id <> o.user_id
        """,
        "option_alias": """
            SELECT COUNT(*)
              FROM recipe_equipment_options o
              JOIN equipment_aliases a ON a.id = o.matched_alias_id
             WHERE o.user_id = ? AND a.user_id <> o.user_id
        """,
    }
    violations = {
        name: int(_scalar(connection, sql, (tenant,)))
        for name, sql in checks.items()
    }
    if any(violations.values()):
        raise CanaryInvariantError(f"Canary tenant boundary drift: {violations}")


def build_canary_manifest(connection, tenant):
    """Return the exact server-controlled Phase 4D recipe manifest."""
    tenant = str(tenant or "").strip()
    if not tenant:
        raise CanaryInvariantError("A registered tenant is required.")
    if not requirements.structured_equipment_schema_available(connection):
        raise CanaryInvariantError("The structured-equipment schema is unavailable.")
    if str(connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
        raise CanaryInvariantError("The recipe master database failed integrity_check.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise CanaryInvariantError("The recipe master database has foreign-key violations.")

    counts = _canary_counts(connection, tenant)
    _verify_tenant_boundaries(connection, tenant)
    sync_rows = connection.execute(
        """
        SELECT user_id, recipe_id, source_hash, requirement_count, parser_version
          FROM recipe_equipment_requirement_sync
         WHERE user_id = ?
         ORDER BY recipe_id
        """,
        (tenant,),
    ).fetchall()
    if len(sync_rows) != CANARY_RECIPE_COUNT:
        raise CanaryInvariantError("The canary synchronization set is not exactly 88 recipes.")

    requirement_recipe_ids = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT recipe_id FROM recipe_equipment_requirements WHERE user_id = ?",
            (tenant,),
        ).fetchall()
    }
    sync_recipe_ids = {str(row["recipe_id"]) for row in sync_rows}
    if requirement_recipe_ids != sync_recipe_ids:
        raise CanaryInvariantError("The canary recipe and synchronization sets differ.")

    recipes = []
    for ordinal, sync_row in enumerate(sync_rows, start=1):
        recipe_id = str(sync_row["recipe_id"] or "").strip()
        source_hash = str(sync_row["source_hash"] or "").strip().upper()
        if not recipe_id or not SHA256_PATTERN.fullmatch(source_hash):
            raise CanaryInvariantError("A canary synchronization row is malformed.")
        if str(sync_row["parser_version"] or "") != PARSER_VERSION:
            raise CanaryInvariantError("A canary synchronization row has a stale parser version.")
        structured_rows = requirements.load_structured_equipment_requirements(
            connection,
            tenant,
            recipe_id,
            require_ready=True,
        )
        if int(sync_row["requirement_count"] or 0) != len(structured_rows):
            raise CanaryInvariantError("A canary synchronization requirement count drifted.")
        recipes.append({
            "ordinal": ordinal,
            "recipe_id": recipe_id,
            "recipe_sha256": _sha256_text(recipe_id),
            "source_hash": source_hash,
            "requirement_count": len(structured_rows),
            "parser_version": PARSER_VERSION,
            "structured_state_fingerprint": (
                requirements.structured_requirement_state_fingerprint(structured_rows)
            ),
        })

    fingerprint_payload = [
        {
            "ordinal": row["ordinal"],
            "recipe_id": row["recipe_id"],
            "source_hash": row["source_hash"],
            "requirement_count": row["requirement_count"],
            "parser_version": row["parser_version"],
            "structured_state_fingerprint": row["structured_state_fingerprint"],
        }
        for row in recipes
    ]
    return {
        "tenant": tenant,
        "counts": counts,
        "recipes": recipes,
        "manifest_fingerprint": _sha256_json(fingerprint_payload),
    }


def _serializer(secret_key):
    if not secret_key:
        raise CanaryTokenError("The application signing key is unavailable.")
    return URLSafeSerializer(secret_key, salt=CANARY_TOKEN_SALT)


def issue_canary_plan(
    connection,
    tenant,
    secret_key,
    *,
    selection_mode="structured_read",
    now=None,
):
    if selection_mode not in CANARY_SELECTION_MODES:
        raise CanaryInvariantError("The canary selection mode is invalid.")
    manifest = build_canary_manifest(connection, tenant)
    issued_at = int(time.time() if now is None else now)
    payload = {
        "version": CANARY_TOKEN_VERSION,
        "kind": "run",
        "tenant": manifest["tenant"],
        "run_id": uuid4().hex,
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "selection_mode": selection_mode,
        "issued_at": issued_at,
        "expires_at": issued_at + CANARY_TOKEN_TTL_SECONDS,
    }
    token = _serializer(secret_key).dumps(payload)
    recipe_plans = []
    for row in manifest["recipes"]:
        sample_payload = {
            **payload,
            "kind": "sample",
            "ordinal": row["ordinal"],
            "recipe_sha256": row["recipe_sha256"],
            "source_hash": row["source_hash"],
            "requirement_count": row["requirement_count"],
            "parser_version": row["parser_version"],
            "structured_state_fingerprint": row["structured_state_fingerprint"],
        }
        recipe_plans.append({
            "ordinal": row["ordinal"],
            "url": row["recipe_id"],
            "sample_token": _serializer(secret_key).dumps(sample_payload),
        })
    return {
        "run_id": payload["run_id"],
        "token": token,
        "expires_at": payload["expires_at"],
        "pass_count": CANARY_PASS_COUNT,
        "recipe_count": CANARY_RECIPE_COUNT,
        "expected_sample_count": CANARY_SAMPLE_COUNT,
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "selection_mode": selection_mode,
        "recipes": recipe_plans,
    }


def validate_canary_token(token, tenant, secret_key, *, expected_kind=None, now=None):
    token = str(token or "").strip()
    tenant = str(tenant or "").strip()
    if not token or len(token) > MAX_TOKEN_LENGTH or not tenant:
        raise CanaryTokenError("The canary token is missing or malformed.")
    try:
        payload = _serializer(secret_key).loads(token)
    except BadData as exc:
        raise CanaryTokenError("The canary token signature is invalid.") from exc
    if not isinstance(payload, dict):
        raise CanaryTokenError("The canary token payload is malformed.")
    current_time = int(time.time() if now is None else now)
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    run_id = str(payload.get("run_id") or "")
    manifest_fingerprint = str(payload.get("manifest_fingerprint") or "")
    if (
        payload.get("version") != CANARY_TOKEN_VERSION
        or payload.get("kind") not in {"run", "sample"}
        or (expected_kind is not None and payload.get("kind") != expected_kind)
        or str(payload.get("tenant") or "") != tenant
        or payload.get("selection_mode") not in CANARY_SELECTION_MODES
        or not RUN_ID_PATTERN.fullmatch(run_id)
        or not SHA256_PATTERN.fullmatch(manifest_fingerprint)
        or not isinstance(issued_at, int)
        or not isinstance(expires_at, int)
        or issued_at > current_time + 60
        or expires_at <= current_time
        or expires_at - issued_at != CANARY_TOKEN_TTL_SECONDS
    ):
        raise CanaryTokenError("The canary token is expired or out of scope.")
    if payload.get("kind") == "sample" and (
        not isinstance(payload.get("ordinal"), int)
        or not 1 <= payload["ordinal"] <= CANARY_RECIPE_COUNT
        or not SHA256_PATTERN.fullmatch(str(payload.get("recipe_sha256") or ""))
        or not SHA256_PATTERN.fullmatch(str(payload.get("source_hash") or ""))
        or not SHA256_PATTERN.fullmatch(
            str(payload.get("structured_state_fingerprint") or "")
        )
        or not isinstance(payload.get("requirement_count"), int)
        or payload["requirement_count"] < 1
        or str(payload.get("parser_version") or "") != PARSER_VERSION
    ):
        raise CanaryTokenError("The canary sample token is malformed.")
    return payload


def authorize_canary_run(connection, token, tenant, secret_key, *, now=None):
    payload = validate_canary_token(
        token,
        tenant,
        secret_key,
        expected_kind="run",
        now=now,
    )
    manifest = build_canary_manifest(connection, tenant)
    if payload["manifest_fingerprint"] != manifest["manifest_fingerprint"]:
        raise CanaryInvariantError("The canary manifest changed after token issuance.")
    return payload, manifest


def authorize_canary_sample(
    connection,
    token,
    tenant,
    secret_key,
    recipe_url,
    pass_number,
    sequence,
    *,
    now=None,
):
    payload = validate_canary_token(
        token,
        tenant,
        secret_key,
        expected_kind="sample",
        now=now,
    )
    try:
        pass_number = int(pass_number)
        sequence = int(sequence)
    except (TypeError, ValueError) as exc:
        raise CanaryTokenError("The canary sample position is malformed.") from exc
    if not 1 <= sequence <= CANARY_SAMPLE_COUNT:
        raise CanaryTokenError("The canary sample sequence is out of range.")
    expected_pass = ((sequence - 1) // CANARY_RECIPE_COUNT) + 1
    expected_index = (sequence - 1) % CANARY_RECIPE_COUNT
    if pass_number != expected_pass or not 1 <= pass_number <= CANARY_PASS_COUNT:
        raise CanaryTokenError("The canary pass does not match the sample sequence.")
    if int(payload.get("ordinal") or 0) != expected_index + 1:
        raise CanaryTokenError("The sample token does not match the canary sequence.")
    sync_row = connection.execute(
        """
        SELECT recipe_id, source_hash, requirement_count, parser_version
          FROM recipe_equipment_requirement_sync
         WHERE user_id = ?
         ORDER BY recipe_id
         LIMIT 1 OFFSET ?
        """,
        (tenant, expected_index),
    ).fetchone()
    if sync_row is None:
        raise CanaryInvariantError("The canary synchronization row is missing.")
    expected_recipe_id = str(sync_row["recipe_id"] or "")
    if (
        str(recipe_url or "").strip() != expected_recipe_id
        or _sha256_text(expected_recipe_id) != str(payload.get("recipe_sha256") or "")
        or str(sync_row["source_hash"] or "").upper() != str(payload.get("source_hash") or "")
        or int(sync_row["requirement_count"] or 0) != int(payload.get("requirement_count") or -1)
        or str(sync_row["parser_version"] or "") != str(payload.get("parser_version") or "")
    ):
        raise CanaryTokenError("The recipe does not match the server-controlled canary order.")
    structured_rows = requirements.load_structured_equipment_requirements(
        connection,
        tenant,
        expected_recipe_id,
        require_ready=True,
    )
    expected_recipe = {
        "ordinal": expected_index + 1,
        "recipe_id": expected_recipe_id,
        "recipe_sha256": str(payload["recipe_sha256"]),
        "source_hash": str(payload["source_hash"]),
        "requirement_count": int(payload["requirement_count"]),
        "parser_version": str(payload["parser_version"]),
        "structured_state_fingerprint": str(payload.get("structured_state_fingerprint") or ""),
    }
    if (
        len(structured_rows) != expected_recipe["requirement_count"]
        or requirements.structured_requirement_state_fingerprint(structured_rows)
        != expected_recipe["structured_state_fingerprint"]
    ):
        raise CanaryInvariantError("The recipe's structured state changed after token issuance.")
    return {
        "run_id": payload["run_id"],
        "tenant": tenant,
        "manifest_fingerprint": payload["manifest_fingerprint"],
        "selection_mode": payload["selection_mode"],
        "pass_number": pass_number,
        "sequence": sequence,
        "recipe": expected_recipe,
    }


def _audit_root():
    configured = str(os.getenv(CANARY_AUDIT_DIR_ENV, "") or "").strip()
    if not configured:
        raise CanaryAuditError("The canary audit directory is not configured.")
    configured_path = Path(configured).expanduser()
    if not configured_path.is_absolute():
        raise CanaryAuditError("The canary audit directory must be absolute.")
    root = configured_path.resolve()
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise CanaryAuditError("The canary audit directory is unsafe.")
    return root


def _audit_path(run_id):
    run_id = str(run_id or "")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise CanaryAuditError("The canary run identifier is invalid.")
    root = _audit_root()
    path = (root / f"{run_id}.jsonl").resolve()
    if path.parent != root:
        raise CanaryAuditError("The canary audit path escaped its configured root.")
    return path


def append_audit_record(run_id, record):
    if not isinstance(record, dict):
        raise CanaryAuditError("The canary audit record is malformed.")
    path = _audit_path(run_id)
    line = _canonical_json(record) + "\n"
    with AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_symlink():
            raise CanaryAuditError("The canary audit file is unsafe.")
        with path.open("a", encoding="utf-8", newline="\n") as target:
            target.write(line)
            target.flush()
            os.fsync(target.fileno())
    return path


def _coerce_metric(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _observation_failure(reason, observations, *, tenant_violation=False):
    """Return a sanitized fail-closed event without retaining observation data."""
    metrics = {key: 0 for key in DIFFERENCE_METRICS}
    latency_ms = 0.0
    fingerprints = set()
    for event in observations:
        if not isinstance(event, dict):
            continue
        fingerprint = event.get("structured_state_fingerprint")
        if isinstance(fingerprint, str) and SHA256_PATTERN.fullmatch(fingerprint):
            fingerprints.add(fingerprint)
        for key in DIFFERENCE_METRICS:
            metrics[key] = max(metrics[key], _coerce_metric(event.get(key)))
        value = event.get("latency_ms", 0)
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            latency_ms = max(latency_ms, parsed)
    if tenant_violation:
        metrics["tenant_violations"] = max(1, metrics["tenant_violations"])
    fingerprint = next(iter(fingerprints)) if len(fingerprints) == 1 else ""
    return {
        "consumer": "editor_api",
        "eligible": False,
        "fallback_reason": str(reason or "invalid_canary_observation")[:120],
        "structured_state_fingerprint": fingerprint,
        "latency_ms": latency_ms,
        **metrics,
    }


def select_authenticated_canary_observation(captured_events, context, tenant):
    """Select one primary editor observation and validate every ancillary event.

    Nested recipe reads can emit additional structured observations. They are
    safe to accept only when each describes the same authenticated recipe and
    proves the same eligible, difference-free structured state.
    """
    observations = (
        list(captured_events)
        if isinstance(captured_events, (list, tuple))
        else []
    )
    recipe = context.get("recipe") if isinstance(context, dict) else None
    expected_recipe_id = str((recipe or {}).get("recipe_id") or "")
    expected_fingerprint = str(
        (recipe or {}).get("structured_state_fingerprint") or ""
    )
    tenant = str(tenant or "")
    if (
        not observations
        or not tenant
        or not expected_recipe_id
        or not SHA256_PATTERN.fullmatch(expected_fingerprint)
    ):
        return _observation_failure(
            "missing_primary_canary_observation", observations
        )

    primary_events = [
        event
        for event in observations
        if isinstance(event, dict) and event.get("consumer") == "editor_api"
    ]
    if len(primary_events) != 1:
        reason = (
            "missing_primary_canary_observation"
            if not primary_events
            else "ambiguous_primary_canary_observation"
        )
        return _observation_failure(reason, observations)

    max_latency_ms = 0.0
    for event in observations:
        if not isinstance(event, dict):
            return _observation_failure(
                "malformed_canary_observation", observations
            )
        if event.get("event") not in {"shadow_compare", "read_decision"}:
            return _observation_failure(
                "malformed_canary_observation", observations
            )
        consumer = event.get("consumer")
        if not isinstance(consumer, str) or not consumer.strip():
            return _observation_failure(
                "malformed_canary_observation", observations
            )
        event_tenant = event.get("user_id")
        event_recipe_id = event.get("recipe_id")
        if not isinstance(event_tenant, str) or event_tenant != tenant:
            return _observation_failure(
                "canary_observation_identity_mismatch",
                observations,
                tenant_violation=True,
            )
        if (
            not isinstance(event_recipe_id, str)
            or event_recipe_id != expected_recipe_id
        ):
            return _observation_failure(
                "canary_observation_identity_mismatch", observations
            )
        if event.get("eligible") is not True:
            return _observation_failure(
                "ineligible_canary_observation", observations
            )
        fallback_reason = event.get("fallback_reason", "")
        if not isinstance(fallback_reason, str):
            return _observation_failure(
                "malformed_canary_observation", observations
            )
        if fallback_reason:
            return _observation_failure(
                "canary_observation_fallback", observations
            )
        fingerprint = event.get("structured_state_fingerprint")
        if (
            not isinstance(fingerprint, str)
            or fingerprint != expected_fingerprint
        ):
            return _observation_failure(
                "canary_observation_fingerprint_mismatch", observations
            )

        for key in DIFFERENCE_METRICS:
            value = event.get(key, 0)
            if isinstance(value, bool):
                parsed = int(value)
            elif isinstance(value, (int, float)) and math.isfinite(float(value)):
                parsed = int(value)
                if float(parsed) != float(value):
                    return _observation_failure(
                        "malformed_canary_observation", observations
                    )
            else:
                return _observation_failure(
                    "malformed_canary_observation", observations
                )
            if parsed:
                return _observation_failure(
                    "canary_observation_difference", observations
                )

        latency = event.get("latency_ms", 0)
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            return _observation_failure(
                "malformed_canary_observation", observations
            )
        latency = float(latency)
        if not math.isfinite(latency) or latency < 0:
            return _observation_failure(
                "malformed_canary_observation", observations
            )
        max_latency_ms = max(max_latency_ms, latency)

    selected = dict(primary_events[0])
    selected["latency_ms"] = max_latency_ms
    for key in DIFFERENCE_METRICS:
        selected[key] = 0
    return selected


def sample_audit_record(
    context,
    structured_event,
    *,
    response_payload,
    application_http_status,
    handler_latency_ms,
):
    event = structured_event if isinstance(structured_event, dict) else {}
    recipe = context["recipe"]
    differences = {
        key: _coerce_metric(event.get(key))
        for key in DIFFERENCE_METRICS
    }
    state_difference = int(
        str(event.get("structured_state_fingerprint") or "")
        != recipe["structured_state_fingerprint"]
    )
    eligible = bool(event.get("eligible"))
    fallback_reason = str(event.get("fallback_reason") or "")[:120]
    consumer = str(event.get("consumer") or "")[:80]
    passed = bool(
        eligible
        and not fallback_reason
        and consumer == "editor_api"
        and not state_difference
        and not any(differences.values())
        and int(application_http_status) == 200
    )
    return {
        "timestamp": _utc_now_iso(),
        "event": "sample",
        "run_id": context["run_id"],
        "tenant": context["tenant"],
        "manifest_fingerprint": context["manifest_fingerprint"],
        "selection_mode": context["selection_mode"],
        "pass_number": context["pass_number"],
        "sequence": context["sequence"],
        "recipe_ordinal": recipe["ordinal"],
        "recipe_sha256": recipe["recipe_sha256"],
        "authenticated": True,
        "consumer": consumer,
        "eligible": eligible,
        "fallback_reason": fallback_reason,
        "structured_state_differences": state_difference,
        "structured_comparison_latency_ms": round(float(event.get("latency_ms") or 0), 3),
        "total_request_handler_latency_ms": round(float(handler_latency_ms or 0), 3),
        "application_http_status": int(application_http_status),
        "response_sha256": _sha256_json(response_payload),
        "passed": passed,
        **differences,
    }


def _validated_client_latencies(values):
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > CANARY_SAMPLE_COUNT:
        raise CanaryTokenError("The client latency sample is malformed.")
    parsed = []
    for value in values:
        if isinstance(value, bool):
            raise CanaryTokenError("The client latency sample is malformed.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise CanaryTokenError("The client latency sample is malformed.") from exc
        if not math.isfinite(number) or number < 0 or number > MAX_CLIENT_LATENCY_MS:
            raise CanaryTokenError("The client latency sample is out of range.")
        parsed.append(round(number, 3))
    return parsed


def _percentile(values, percentile):
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 3)


def latency_summary(values):
    values = list(values or [])
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": round(max(values), 3) if values else 0.0,
    }


def run_event_audit_record(context, event, reason, client_latencies_ms=None):
    event = str(event or "")
    reason = str(reason or "")
    if event not in RUN_EVENTS or reason not in STOP_REASONS:
        raise CanaryTokenError("The canary lifecycle event is invalid.")
    latencies = _validated_client_latencies(client_latencies_ms)
    return {
        "timestamp": _utc_now_iso(),
        "event": event,
        "run_id": context["run_id"],
        "tenant": context["tenant"],
        "manifest_fingerprint": context["manifest_fingerprint"],
        "selection_mode": context["selection_mode"],
        "reason": reason,
        "client_latency": latency_summary(latencies),
    }


def load_audit_records(run_id):
    path = _audit_path(run_id)
    if not path.is_file() or path.is_symlink():
        return []
    records = []
    with AUDIT_LOCK:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CanaryAuditError("The canary audit file is malformed.") from exc
            if not isinstance(record, dict) or str(record.get("run_id") or "") != run_id:
                raise CanaryAuditError("The canary audit file contains an invalid record.")
            records.append(record)
    return records


def summarize_canary_run(context):
    records = load_audit_records(context["run_id"])
    samples = [record for record in records if record.get("event") == "sample"]
    mode_mismatches = sum(
        str(record.get("selection_mode") or "") != context["selection_mode"]
        for record in records
    )
    scope_mismatches = sum(
        str(record.get("tenant") or "") != context["tenant"]
        or str(record.get("manifest_fingerprint") or "")
        != context["manifest_fingerprint"]
        for record in records
    )
    expected_positions = {
        (pass_number, ordinal, ((pass_number - 1) * CANARY_RECIPE_COUNT) + ordinal)
        for pass_number in range(1, CANARY_PASS_COUNT + 1)
        for ordinal in range(1, CANARY_RECIPE_COUNT + 1)
    }
    actual_positions = {
        (
            int(record.get("pass_number") or 0),
            int(record.get("recipe_ordinal") or 0),
            int(record.get("sequence") or 0),
        )
        for record in samples
    }
    duplicates = len(samples) - len(actual_positions)
    response_hashes = {}
    for record in samples:
        response_hashes.setdefault(str(record.get("recipe_sha256") or ""), set()).add(
            str(record.get("response_sha256") or "")
        )
    response_hash_differences = sum(
        max(0, len(values) - 1) for values in response_hashes.values()
    )
    server_latencies = [
        float(record.get("structured_comparison_latency_ms") or 0)
        for record in samples
    ]
    handler_latencies = [
        float(record.get("total_request_handler_latency_ms") or 0)
        for record in samples
    ]
    difference_total = sum(
        _coerce_metric(record.get(metric))
        for record in samples
        for metric in DIFFERENCE_METRICS
    ) + sum(_coerce_metric(record.get("structured_state_differences")) for record in samples)
    completed_events = [
        record for record in records if record.get("event") == "run_completed"
    ]
    latest_client_latency = (
        completed_events[-1].get("client_latency") if completed_events else latency_summary([])
    )
    structured_latency = latency_summary(server_latencies)
    request_handler_latency = latency_summary(handler_latencies)
    latency_thresholds_passed = bool(
        structured_latency["count"] == CANARY_SAMPLE_COUNT
        and structured_latency["p95_ms"] <= 50
        and structured_latency["p99_ms"] <= 100
        and int((latest_client_latency or {}).get("count") or 0) == CANARY_SAMPLE_COUNT
    )
    passed_samples = sum(bool(record.get("passed")) for record in samples)
    fallback_count = sum(bool(record.get("fallback_reason")) for record in samples)
    error_count = len(samples) - passed_samples
    coverage_complete = actual_positions == expected_positions and duplicates == 0
    complete = bool(
        len(samples) == CANARY_SAMPLE_COUNT
        and coverage_complete
        and passed_samples == CANARY_SAMPLE_COUNT
        and difference_total == 0
        and response_hash_differences == 0
        and completed_events
        and latency_thresholds_passed
        and mode_mismatches == 0
        and scope_mismatches == 0
    )
    return {
        "run_id": context["run_id"],
        "tenant": context["tenant"],
        "manifest_fingerprint": context["manifest_fingerprint"],
        "selection_mode": context["selection_mode"],
        "expected_sample_count": CANARY_SAMPLE_COUNT,
        "sample_count": len(samples),
        "passed_sample_count": passed_samples,
        "eligible_percent": round((passed_samples / len(samples)) * 100, 3) if samples else 0.0,
        "coverage_complete": coverage_complete,
        "duplicate_sample_count": duplicates,
        "fallback_count": fallback_count,
        "error_count": error_count,
        "difference_total": difference_total,
        "response_hash_differences": response_hash_differences,
        "selection_mode_mismatches": mode_mismatches,
        "scope_mismatches": scope_mismatches,
        "structured_comparison_latency": structured_latency,
        "request_handler_latency": request_handler_latency,
        "client_round_trip_latency": latest_client_latency,
        "latency_thresholds_passed": latency_thresholds_passed,
        "complete": complete,
    }
