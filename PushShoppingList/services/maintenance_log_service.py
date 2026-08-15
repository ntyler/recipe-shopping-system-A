"""Redacted structured logging for migrations and maintenance jobs."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from datetime import timezone


LOGGER = logging.getLogger("shopping_app.maintenance")
ALLOWED_OUTCOMES = {"started", "preview", "complete", "failed", "deferred", "no_op"}


def utc_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def identifier_fingerprint(value):
    normalized = str(value or "").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16] if normalized else ""


def maintenance_event(
    *,
    event,
    run_id,
    phase,
    mode,
    outcome,
    counts=None,
    duration_ms=None,
    workspace_id="",
    source_sha256="",
    error_code="",
):
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome not in ALLOWED_OUTCOMES:
        raise ValueError("Unsupported maintenance log outcome.")
    normalized_counts = {}
    for key, value in sorted((counts or {}).items()):
        try:
            normalized_counts[str(key)] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Maintenance log counts must be integers.") from exc
    payload = {
        "timestamp": utc_timestamp(),
        "event": str(event or "maintenance").strip() or "maintenance",
        "run_id": str(run_id or "").strip(),
        "phase": str(phase or "").strip(),
        "mode": str(mode or "").strip(),
        "outcome": normalized_outcome,
        "counts": normalized_counts,
        "workspace_fingerprint": identifier_fingerprint(workspace_id),
        "source_sha256": str(source_sha256 or "").strip(),
        "error_code": str(error_code or "").strip(),
    }
    if duration_ms is not None:
        payload["duration_ms"] = max(0, int(duration_ms))
    return payload


def emit_maintenance_event(**fields):
    payload = maintenance_event(**fields)
    LOGGER.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return payload


__all__ = [
    "emit_maintenance_event",
    "identifier_fingerprint",
    "maintenance_event",
]
