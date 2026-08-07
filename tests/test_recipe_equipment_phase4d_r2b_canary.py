import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.app import create_app
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import recipe_equipment_requirement_service as equipment
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services import structured_equipment_canary_service as canary
from PushShoppingList.services import user_account_service


TENANT = "6700fb164ae645e29cc592cccc101bc7"
OTHER_TENANT = "different-workspace"


def _connection(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _install_structured_schema(connection):
    connection.execute(
        """
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            equipment_section TEXT NOT NULL DEFAULT 'MISC',
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        )
        """
    )
    equipment.ensure_structured_equipment_schema(
        connection,
        authorized=True,
        migration_token=equipment.PHASE3A_MIGRATION_TOKEN,
    )


def _seed_exact_canary_database(path):
    connection = _connection(path)
    _install_structured_schema(connection)
    target_id = int(connection.execute(
        """
        INSERT INTO equipment (
            user_id, name, normalized_name, canonical_name, canonical_key,
            status, created_at, updated_at
        ) VALUES (?, 'Canary tool', 'canary tool', 'Canary tool', 'canary tool',
                  'active', 'now', 'now')
        """,
        (TENANT,),
    ).lastrowid)
    requirement_index = 0
    option_index = 0
    for recipe_index in range(canary.CANARY_RECIPE_COUNT):
        recipe_id = f"https://example.test/canary/{recipe_index:03d}"
        recipe_requirement_count = 4 if recipe_index < 42 else 3
        for recipe_sort_order in range(recipe_requirement_count):
            requirement_index += 1
            connector = (
                "and" if requirement_index <= 30
                else "or" if requirement_index <= 61
                else "single"
            )
            requirement_pk = int(connection.execute(
                """
                INSERT INTO recipe_equipment_requirements (
                    requirement_id, user_id, recipe_id, source_text, optional,
                    quantity, notes, sort_order, connector, conjunction_group,
                    parse_confidence, review_status, parser_version,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, '', ?, ?, ?, 1.0, 'ready', ?,
                          '{"fixture":true}', 'now', 'now')
                """,
                (
                    f"eqr_fixture_{requirement_index:04d}",
                    TENANT,
                    recipe_id,
                    f"Canary tool {requirement_index}",
                    str(requirement_index),
                    recipe_sort_order,
                    connector,
                    f"group-{requirement_index}" if connector == "and" else "",
                    equipment.PARSER_VERSION,
                ),
            ).lastrowid)
            option_count = 2 if connector == "or" else 1
            for option_sort_order in range(option_count):
                option_index += 1
                option_kind = (
                    "supply" if option_index <= 5
                    else "facility" if option_index <= 7
                    else "equipment"
                )
                attributes = (
                    {"fixture_attribute": option_index}
                    if option_index <= 84 else {}
                )
                connection.execute(
                    """
                    INSERT INTO recipe_equipment_options (
                        option_id, user_id, requirement_id, equipment_id,
                        source_option_text, canonical_name, canonical_key,
                        option_kind, attributes_json, notes, sort_order,
                        matched_alias_id, match_type, match_confidence,
                        review_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, NULL,
                              'fixture_exact', 1.0, 'ready', 'now', 'now')
                    """,
                    (
                        f"eqo_fixture_{option_index:04d}",
                        TENANT,
                        requirement_pk,
                        target_id if option_kind == "equipment" else None,
                        f"Canary option {option_index}",
                        f"Canary option {option_index}",
                        f"canary option {option_index}",
                        option_kind,
                        json.dumps(attributes, separators=(",", ":")),
                        option_sort_order,
                    ),
                )
        source_hash = hashlib.sha256(recipe_id.encode("utf-8")).hexdigest().upper()
        connection.execute(
            """
            INSERT INTO recipe_equipment_requirement_sync (
                user_id, recipe_id, source_hash, requirement_count,
                parser_version, synced_at
            ) VALUES (?, ?, ?, ?, ?, 'now')
            """,
            (
                TENANT,
                recipe_id,
                source_hash,
                recipe_requirement_count,
                equipment.PARSER_VERSION,
            ),
        )
    connection.commit()
    assert requirement_index == 306
    assert option_index == 337
    connection.close()


def _configure_isolated_app(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [
            {
                "user_id": TENANT,
                "email": "owner@example.test",
                "account_status": "active",
            },
            {
                "user_id": OTHER_TENANT,
                "email": "other@example.test",
                "account_status": "active",
            },
        ],
    })
    monkeypatch.setenv(canary.CANARY_AUDIT_DIR_ENV, str(tmp_path / "audit"))
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "phase4d-r2b-tests-only-deterministic-signing-key-2026",
    })


def _enable_canary(monkeypatch, tenant=TENANT):
    monkeypatch.setenv(canary.CANARY_FLAG, "true")
    monkeypatch.setenv(canary.CANARY_TENANTS_ENV, tenant)
    for gate in ("SHADOW", "READ"):
        monkeypatch.setenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_ENABLED", "true")
        monkeypatch.setenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_TENANTS", tenant)


def _sign_in(client, tenant=TENANT):
    with client.session_transaction() as session:
        session["user_id"] = tenant


def _page_plan(response):
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    element = soup.find("script", {"id": "structuredEquipmentCanaryPlan"})
    return json.loads(element.string)


def _manifest_fingerprints(path):
    with _connection(path) as connection:
        manifest = canary.build_canary_manifest(connection, TENANT)
    return {
        row["recipe_id"]: row["structured_state_fingerprint"]
        for row in manifest["recipes"]
    }


def _install_successful_recipe_loader(monkeypatch, fingerprints):
    def load_recipe(recipe_url):
        equipment.emit_structured_equipment_event(
            "shadow_compare",
            user_id=TENANT,
            recipe_id=recipe_url,
            consumer="editor_api",
            eligible=True,
            fallback_reason="",
            pending_set_changed=False,
            tenant_violations=0,
            structured_state_fingerprint=fingerprints[recipe_url],
            latency_ms=1.25,
        )
        return {
            "ok": True,
            "recipe": {
                "source_url": recipe_url,
                "equipment": [{"equipment": "Canary tool"}],
                "metadata": {"image_url": "/unchanged.png"},
            },
        }

    monkeypatch.setattr(recipe_routes, "load_editable_recipe", load_recipe)


def _request_sample(client, plan, sequence):
    recipe_index = (sequence - 1) % canary.CANARY_RECIPE_COUNT
    pass_number = ((sequence - 1) // canary.CANARY_RECIPE_COUNT) + 1
    recipe = plan["recipes"][recipe_index]
    return client.get(
        "/api/recipe",
        query_string={"url": recipe["url"]},
        headers={
            "X-Recipe-Equipment-Canary": recipe["sample_token"],
            "X-Recipe-Equipment-Canary-Pass": str(pass_number),
            "X-Recipe-Equipment-Canary-Sequence": str(sequence),
        },
    )


def _observation_context():
    return {
        "recipe": {
            "recipe_id": "https://example.test/canary/000",
            "structured_state_fingerprint": "D" * 64,
        }
    }


def _valid_observation(consumer="editor_api", **overrides):
    event = {
        "event": "shadow_compare",
        "user_id": TENANT,
        "recipe_id": "https://example.test/canary/000",
        "consumer": consumer,
        "eligible": True,
        "fallback_reason": "",
        "structured_state_fingerprint": "D" * 64,
        "latency_ms": 1.25,
        **{key: 0 for key in canary.DIFFERENCE_METRICS},
    }
    event.update(overrides)
    return event


def test_canary_observation_selects_one_primary_and_validates_ancillary_events():
    primary = _valid_observation(latency_ms=1.25)
    ancillary = _valid_observation("recipe_output", latency_ms=2.5)

    first = canary.select_authenticated_canary_observation(
        [primary, ancillary], _observation_context(), TENANT
    )
    reversed_order = canary.select_authenticated_canary_observation(
        [ancillary, primary], _observation_context(), TENANT
    )
    duplicated_ancillary = canary.select_authenticated_canary_observation(
        [ancillary, primary, dict(ancillary)], _observation_context(), TENANT
    )

    assert first["consumer"] == "editor_api"
    assert first["eligible"] is True
    assert first["latency_ms"] == 2.5
    assert reversed_order == first
    assert duplicated_ancillary == first


def test_canary_observation_requires_exactly_one_primary():
    ancillary = _valid_observation("recipe_output")
    missing = canary.select_authenticated_canary_observation(
        [ancillary], _observation_context(), TENANT
    )
    duplicate = canary.select_authenticated_canary_observation(
        [_valid_observation(), _valid_observation()],
        _observation_context(),
        TENANT,
    )

    assert missing["eligible"] is False
    assert missing["fallback_reason"] == "missing_primary_canary_observation"
    assert duplicate["eligible"] is False
    assert duplicate["fallback_reason"] == "ambiguous_primary_canary_observation"


@pytest.mark.parametrize(
    ("override", "expected_reason", "tenant_violation"),
    [
        ({"user_id": OTHER_TENANT}, "canary_observation_identity_mismatch", 1),
        ({"recipe_id": "https://example.test/wrong"}, "canary_observation_identity_mismatch", 0),
        ({"eligible": False}, "ineligible_canary_observation", 0),
        ({"fallback_reason": "stale_sync"}, "canary_observation_fallback", 0),
        ({"structured_state_fingerprint": "E" * 64}, "canary_observation_fingerprint_mismatch", 0),
        ({"pending_set_changed": True}, "canary_observation_difference", 0),
        ({"latency_ms": "1.25"}, "malformed_canary_observation", 0),
        ({"fallback_reason": None}, "malformed_canary_observation", 0),
    ],
)
def test_canary_observation_rejects_invalid_ancillary_events(
    override, expected_reason, tenant_violation
):
    result = canary.select_authenticated_canary_observation(
        [_valid_observation(), _valid_observation("recipe_output", **override)],
        _observation_context(),
        TENANT,
    )

    assert result["eligible"] is False
    assert result["fallback_reason"] == expected_reason
    assert result["tenant_violations"] == tenant_violation


@pytest.mark.parametrize("metric", canary.DIFFERENCE_METRICS)
def test_canary_observation_preserves_every_ancillary_difference(metric):
    result = canary.select_authenticated_canary_observation(
        [_valid_observation(), _valid_observation("recipe_output", **{metric: 1})],
        _observation_context(),
        TENANT,
    )

    assert result["eligible"] is False
    assert result["fallback_reason"] == "canary_observation_difference"
    assert result[metric] == 1


def test_canary_observation_repeated_validation_is_deterministic():
    observations = [
        _valid_observation("recipe_output", latency_ms=3.0),
        _valid_observation(latency_ms=2.0),
    ]
    results = [
        canary.select_authenticated_canary_observation(
            observations, _observation_context(), TENANT
        )
        for _ in range(5)
    ]
    assert results == [results[0]] * 5


def test_canary_gate_is_default_deny_exact_tenant_and_rejects_wildcards(monkeypatch):
    monkeypatch.delenv(canary.CANARY_FLAG, raising=False)
    monkeypatch.delenv(canary.CANARY_TENANTS_ENV, raising=False)
    assert canary.authenticated_canary_enabled(TENANT) is False
    assert equipment.authenticated_equipment_canary_enabled(TENANT) is False

    monkeypatch.setenv(canary.CANARY_FLAG, "true")
    assert canary.authenticated_canary_enabled(TENANT) is False
    monkeypatch.setenv(canary.CANARY_TENANTS_ENV, f"{OTHER_TENANT},*")
    assert canary.authenticated_canary_enabled(TENANT) is False
    monkeypatch.setenv(canary.CANARY_TENANTS_ENV, f"{OTHER_TENANT},{TENANT}")
    assert canary.authenticated_canary_enabled(TENANT) is True
    assert canary.authenticated_canary_enabled(OTHER_TENANT) is True
    assert canary.authenticated_canary_enabled("unknown") is False


def test_server_manifest_and_signed_tokens_are_exact_and_fail_closed(monkeypatch, tmp_path):
    db_path = tmp_path / "canary.sqlite3"
    _seed_exact_canary_database(db_path)
    with _connection(db_path) as connection:
        manifest = canary.build_canary_manifest(connection, TENANT)
        plan = canary.issue_canary_plan(connection, TENANT, "test-secret", now=100)
        assert manifest["counts"] == canary.EXPECTED_CANARY_COUNTS
        assert len(plan["recipes"]) == 88
        assert plan["expected_sample_count"] == 528
        assert plan["selection_mode"] == "structured_read"
        context = canary.authorize_canary_sample(
            connection,
            plan["recipes"][0]["sample_token"],
            TENANT,
            "test-secret",
            plan["recipes"][0]["url"],
            1,
            1,
            now=101,
        )
        assert context["recipe"]["ordinal"] == 1
        assert context["selection_mode"] == "structured_read"
        baseline_plan = canary.issue_canary_plan(
            connection,
            TENANT,
            "test-secret",
            selection_mode="legacy_baseline",
            now=100,
        )
        baseline_context = canary.authorize_canary_sample(
            connection,
            baseline_plan["recipes"][0]["sample_token"],
            TENANT,
            "test-secret",
            baseline_plan["recipes"][0]["url"],
            1,
            1,
            now=101,
        )
        assert baseline_plan["selection_mode"] == "legacy_baseline"
        assert baseline_context["selection_mode"] == "legacy_baseline"

        with pytest.raises(canary.CanaryTokenError):
            canary.validate_canary_token(plan["token"] + "tampered", TENANT, "test-secret", now=101)
        with pytest.raises(canary.CanaryTokenError):
            canary.validate_canary_token(plan["token"], OTHER_TENANT, "test-secret", now=101)
        with pytest.raises(canary.CanaryTokenError):
            canary.validate_canary_token(plan["token"], TENANT, "test-secret", now=2000)
        with pytest.raises(canary.CanaryTokenError):
            canary.authorize_canary_sample(
                connection,
                plan["recipes"][0]["sample_token"],
                TENANT,
                "test-secret",
                plan["recipes"][0]["url"],
                1,
                2,
                now=101,
            )


def test_canary_page_rejects_disabled_unauthenticated_guest_and_wrong_tenant(
    monkeypatch, tmp_path
):
    db_path = master_data.recipe_master_db_path()
    _seed_exact_canary_database(db_path)
    app = _configure_isolated_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        _sign_in(client)
        assert client.get("/structured-equipment/authenticated-canary").status_code == 404

    _enable_canary(monkeypatch)
    with app.test_client() as client:
        page = client.get("/structured-equipment/authenticated-canary")
        assert page.status_code == 302
        assert page.headers["Location"] == "/#userAccountSection"
        assert client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            json={"event": "run_started", "reason": "owner_started"},
        ).status_code == 401
    with app.test_client() as client:
        _sign_in(client, OTHER_TENANT)
        assert client.get("/structured-equipment/authenticated-canary").status_code == 403
    with app.test_client() as client:
        client.get("/guest/start")
        assert client.get("/structured-equipment/authenticated-canary").status_code == 403
    with app.test_client() as client:
        _sign_in(client)
        response = client.get("/structured-equipment/authenticated-canary")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "Start authenticated canary" in response.get_data(as_text=True)
        plan = _page_plan(response)
        assert len(plan["recipes"]) == 88
        assert plan["expected_sample_count"] == 528
        assert client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["token"]},
            data="[]",
            content_type="application/json",
        ).status_code == 400
        assert client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["token"] + "tampered"},
            json={"event": "run_started", "reason": "owner_started"},
        ).status_code == 403
        assert client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["recipes"][0]["sample_token"]},
            json={"event": "run_started", "reason": "owner_started"},
        ).status_code == 403
        assert client.post(
            "/api/recipe",
            headers={"X-Recipe-Equipment-Canary": plan["token"]},
            json={"recipe": {}},
        ).status_code == 405

    monkeypatch.delenv("RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED", raising=False)
    monkeypatch.delenv("RECIPE_EQUIPMENT_STRUCTURED_READ_TENANTS", raising=False)
    with app.test_client() as client:
        _sign_in(client)
        baseline_page = client.get("/structured-equipment/authenticated-canary")
        assert baseline_page.status_code == 200
        assert _page_plan(baseline_page)["selection_mode"] == "legacy_baseline"


def test_owner_click_workflow_records_exactly_528_http_reads_without_data_writes(
    monkeypatch, tmp_path
):
    db_path = master_data.recipe_master_db_path()
    _seed_exact_canary_database(db_path)
    fingerprints = _manifest_fingerprints(db_path)
    _install_successful_recipe_loader(monkeypatch, fingerprints)
    _enable_canary(monkeypatch)
    app = _configure_isolated_app(monkeypatch, tmp_path)
    before_hash = hashlib.sha256(Path(db_path).read_bytes()).hexdigest()

    with app.test_client() as client:
        _sign_in(client)
        page = client.get("/structured-equipment/authenticated-canary")
        plan = _page_plan(page)
        started = client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["token"]},
            json={"event": "run_started", "reason": "owner_started", "client_latencies_ms": []},
        )
        assert started.status_code == 200
        for sequence in range(1, canary.CANARY_SAMPLE_COUNT + 1):
            response = _request_sample(client, plan, sequence)
            assert response.status_code == 200, (sequence, response.get_json())
        completed = client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["token"]},
            json={
                "event": "run_completed",
                "reason": "completed",
                "client_latencies_ms": [2.5] * canary.CANARY_SAMPLE_COUNT,
            },
        )

    assert completed.status_code == 200
    summary = completed.get_json()["summary"]
    assert summary["complete"] is True
    assert summary["sample_count"] == 528
    assert summary["passed_sample_count"] == 528
    assert summary["eligible_percent"] == 100.0
    assert summary["coverage_complete"] is True
    assert summary["fallback_count"] == 0
    assert summary["error_count"] == 0
    assert summary["difference_total"] == 0
    assert summary["response_hash_differences"] == 0
    assert summary["client_round_trip_latency"]["p95_ms"] == 2.5
    assert hashlib.sha256(Path(db_path).read_bytes()).hexdigest() == before_hash
    assert list((tmp_path / "users").rglob("*.json")) == []

    audit_path = tmp_path / "audit" / f"{plan['run_id']}.jsonl"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert audit_text.count('"event":"sample"') == 528
    for forbidden in (
        "cookie",
        "authorization",
        "session_storage",
        "local_storage",
        "owner@example.test",
    ):
        assert forbidden not in audit_text.casefold()


def test_first_equivalence_failure_is_audited_and_rejected(monkeypatch, tmp_path):
    db_path = master_data.recipe_master_db_path()
    _seed_exact_canary_database(db_path)
    fingerprints = _manifest_fingerprints(db_path)

    def mismatching_loader(recipe_url):
        equipment.emit_structured_equipment_event(
            "shadow_compare",
            user_id=TENANT,
            recipe_id=recipe_url,
            consumer="editor_api",
            eligible=True,
            fallback_reason="",
            structured_state_fingerprint=fingerprints[recipe_url],
            connector_differences=1,
            latency_ms=1.0,
        )
        return {"ok": True, "recipe": {"source_url": recipe_url}}

    monkeypatch.setattr(recipe_routes, "load_editable_recipe", mismatching_loader)
    _enable_canary(monkeypatch)
    app = _configure_isolated_app(monkeypatch, tmp_path)
    with app.test_client() as client:
        _sign_in(client)
        plan = _page_plan(client.get("/structured-equipment/authenticated-canary"))
        client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["token"]},
            json={"event": "run_started", "reason": "owner_started"},
        )
        failed = _request_sample(client, plan, 1)
        cancelled = client.post(
            "/api/structured-equipment/authenticated-canary/run-event",
            headers={"X-Recipe-Equipment-Canary": plan["token"]},
            json={"event": "client_error", "reason": "server_rejected", "client_latencies_ms": [1.0]},
        )

    assert failed.status_code == 409
    summary = cancelled.get_json()["summary"]
    assert summary["sample_count"] == 1
    assert summary["passed_sample_count"] == 0
    assert summary["difference_total"] == 1
    assert summary["complete"] is False


def test_audit_redacts_response_and_unrecognized_event_data(monkeypatch, tmp_path):
    monkeypatch.setenv(canary.CANARY_AUDIT_DIR_ENV, str(tmp_path / "audit"))
    context = {
        "run_id": "a" * 32,
        "tenant": TENANT,
        "manifest_fingerprint": "B" * 64,
        "selection_mode": "structured_read",
        "pass_number": 1,
        "sequence": 1,
        "recipe": {
            "ordinal": 1,
            "recipe_sha256": "C" * 64,
            "structured_state_fingerprint": "D" * 64,
        },
    }
    event = {
        "consumer": "editor_api",
        "eligible": True,
        "fallback_reason": "",
        "structured_state_fingerprint": "D" * 64,
        "latency_ms": 1,
        "cookie": "stolen-cookie",
        "authorization": "Bearer secret-token",
    }
    record = canary.sample_audit_record(
        context,
        event,
        response_payload={"password": "do-not-record", "recipe": {"private": "body"}},
        application_http_status=200,
        handler_latency_ms=2,
    )
    canary.append_audit_record(context["run_id"], record)
    text = (tmp_path / "audit" / f"{context['run_id']}.jsonl").read_text(encoding="utf-8")
    for secret in ("stolen-cookie", "secret-token", "do-not-record", '"private":"body"'):
        assert secret not in text
    assert '"response_sha256"' in text


def test_latency_threshold_breach_prevents_successful_reconciliation(monkeypatch):
    run_id = "e" * 32
    manifest_fingerprint = "F" * 64
    records = []
    for sequence in range(1, canary.CANARY_SAMPLE_COUNT + 1):
        ordinal = ((sequence - 1) % canary.CANARY_RECIPE_COUNT) + 1
        pass_number = ((sequence - 1) // canary.CANARY_RECIPE_COUNT) + 1
        records.append({
            "event": "sample",
            "run_id": run_id,
            "selection_mode": "structured_read",
            "pass_number": pass_number,
            "recipe_ordinal": ordinal,
            "sequence": sequence,
            "recipe_sha256": f"recipe-{ordinal}",
            "response_sha256": f"response-{ordinal}",
            "structured_comparison_latency_ms": 60.0,
            "total_request_handler_latency_ms": 70.0,
            "passed": True,
            "fallback_reason": "",
        })
    records.append({
        "event": "run_completed",
        "run_id": run_id,
        "selection_mode": "structured_read",
        "client_latency": canary.latency_summary([80.0] * canary.CANARY_SAMPLE_COUNT),
    })
    monkeypatch.setattr(canary, "load_audit_records", lambda _run_id: records)
    summary = canary.summarize_canary_run({
        "run_id": run_id,
        "tenant": TENANT,
        "manifest_fingerprint": manifest_fingerprint,
        "selection_mode": "structured_read",
    })
    assert summary["coverage_complete"] is True
    assert summary["structured_comparison_latency"]["p95_ms"] == 60.0
    assert summary["latency_thresholds_passed"] is False
    assert summary["complete"] is False


def test_canary_javascript_is_manual_sequential_and_never_reads_authentication_state():
    root = Path(__file__).resolve().parents[1]
    script = (root / "PushShoppingList/static/js/structured-equipment-canary.js").read_text(
        encoding="utf-8"
    )
    template = (root / "PushShoppingList/templates/structured_equipment_canary.html").read_text(
        encoding="utf-8"
    )
    lowered = script.casefold()
    for forbidden in (
        "document.cookie",
        "localstorage",
        "sessionstorage",
        "authorization",
        "set-cookie",
        "navigator.sendbeacon",
    ):
        assert forbidden not in lowered
    assert 'startButton.addEventListener("click", runCanary)' in script
    assert "await fetch(`/api/recipe?url=" in script
    assert 'credentials: "same-origin"' in script
    assert "await delay(THROTTLE_MS)" in script
    assert "activeController.abort()" in script
    assert "throw new Error(\"http_error\")" in script
    assert "structured-equipment-canary.js" in template
    assert "js/app.js" not in template


def test_structured_event_capture_is_request_local_and_deterministic():
    with equipment.capture_structured_equipment_events() as first:
        equipment.emit_structured_equipment_event("read_decision", eligible=True)
    with equipment.capture_structured_equipment_events() as second:
        equipment.emit_structured_equipment_event("read_decision", eligible=False)
    assert first == [{"event": "read_decision", "eligible": True}]
    assert second == [{"event": "read_decision", "eligible": False}]
