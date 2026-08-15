import json
import logging

from PushShoppingList.services import maintenance_log_service as logs


def test_structured_maintenance_log_hashes_identity_and_allows_only_counts(caplog):
    caplog.set_level(logging.INFO, logger="shopping_app.maintenance")

    payload = logs.emit_maintenance_event(
        event="guest_purge",
        run_id="run-1",
        phase="recipe_rows",
        mode="apply",
        outcome="complete",
        counts={"deleted": 7},
        workspace_id="sensitive-guest-id",
        source_sha256="ABC123",
        duration_ms=12,
    )

    assert payload["workspace_fingerprint"]
    assert "sensitive-guest-id" not in json.dumps(payload)
    rendered = caplog.records[-1].getMessage()
    assert "sensitive-guest-id" not in rendered
    assert json.loads(rendered)["counts"] == {"deleted": 7}


def test_structured_maintenance_log_rejects_unbounded_or_invalid_fields():
    try:
        logs.maintenance_event(
            event="migration",
            run_id="run",
            phase="parse",
            mode="dry-run",
            outcome="unknown",
        )
    except ValueError as exc:
        assert "outcome" in str(exc)
    else:
        raise AssertionError("Invalid outcomes must fail closed.")

    try:
        logs.maintenance_event(
            event="migration",
            run_id="run",
            phase="parse",
            mode="dry-run",
            outcome="preview",
            counts={"records": {"raw": "payload"}},
        )
    except ValueError as exc:
        assert "counts" in str(exc)
    else:
        raise AssertionError("Structured payloads must not be accepted as count values.")
