import json
import logging
import sqlite3

import pytest

from PushShoppingList.services import recipe_equipment_requirement_service as equipment
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services.equipment_normalization_service import PARSER_VERSION


TENANT = "tenant-a"
RECIPE = "https://example.com/recipe-a"


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


def _insert_equipment(
    connection,
    name,
    *,
    tenant=TENANT,
    image_url="",
    image_path="",
):
    key = name.casefold()
    cursor = connection.execute(
        """
        INSERT INTO equipment (
            user_id, name, normalized_name, canonical_name, canonical_key,
            status, image_url, image_path, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 'now', 'now')
        """,
        (tenant, name, key, name, key, image_url, image_path),
    )
    return int(cursor.lastrowid)


def _stage(connection, recipe_data, *, tenant=TENANT, recipe_id=RECIPE):
    parsed = equipment.requirements_from_recipe_data(recipe_data)
    equipment.replace_recipe_requirements(
        connection,
        tenant,
        recipe_id,
        parsed,
        authorized=True,
        migration_token=equipment.PHASE3A_MIGRATION_TOKEN,
    )
    return parsed


def _resolve_all_equipment_options(connection, target_id):
    connection.execute(
        """
        UPDATE recipe_equipment_options
           SET equipment_id = ?, review_status = 'ready', match_type = 'fixture_exact',
               match_confidence = 1.0
         WHERE option_kind = 'equipment'
        """,
        (target_id,),
    )
    connection.execute(
        "UPDATE recipe_equipment_options SET review_status = 'ready' WHERE option_kind <> 'equipment'"
    )
    connection.execute(
        "UPDATE recipe_equipment_requirements SET review_status = 'ready'"
    )


def _insert_sync(connection, recipe_data, *, tenant=TENANT, recipe_id=RECIPE, source_hash=None):
    count = connection.execute(
        """
        SELECT COUNT(*) FROM recipe_equipment_requirements
         WHERE user_id = ? AND recipe_id = ?
        """,
        (tenant, recipe_id),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT OR REPLACE INTO recipe_equipment_requirement_sync (
            user_id, recipe_id, source_hash, requirement_count, parser_version, synced_at
        ) VALUES (?, ?, ?, ?, ?, 'now')
        """,
        (
            tenant,
            recipe_id,
            source_hash or equipment.equipment_source_hash(recipe_data),
            count,
            PARSER_VERSION,
        ),
    )


def _enable(monkeypatch, gate, tenant=TENANT):
    monkeypatch.setenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_ENABLED", "true")
    monkeypatch.setenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_TENANTS", tenant)


def test_runtime_gates_are_global_and_exact_tenant_default_deny(monkeypatch):
    gates = {
        "SHADOW": equipment.structured_equipment_shadow_enabled,
        "DUAL_WRITE": equipment.structured_equipment_dual_write_enabled,
        "READ": equipment.structured_equipment_read_enabled,
        "UI": equipment.structured_equipment_ui_enabled,
    }
    for gate, resolver in gates.items():
        monkeypatch.delenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_ENABLED", raising=False)
        monkeypatch.delenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_TENANTS", raising=False)
        assert resolver(TENANT) is False
        monkeypatch.setenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_ENABLED", "true")
        assert resolver() is True  # migration/runtime-state introspection only
        assert resolver(TENANT) is False
        monkeypatch.setenv(f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_TENANTS", "tenant-b,*")
        assert resolver(TENANT) is False
        monkeypatch.setenv(
            f"RECIPE_EQUIPMENT_STRUCTURED_{gate}_TENANTS", f"tenant-b,{TENANT}"
        )
        assert resolver(TENANT) is True
        assert resolver("tenant-b") is True
        assert resolver("tenant-c") is False


def test_flags_off_read_is_same_object_and_database_noop(tmp_path):
    db_path = tmp_path / "flags-off.sqlite3"
    connection = _connection(db_path)
    _install_structured_schema(connection)
    recipe_data = {"equipment": [{"equipment": "Whisk"}], "instructions": []}
    before_changes = connection.total_changes
    result = equipment.apply_structured_equipment_read(
        RECIPE, recipe_data, user_id=TENANT, connection=connection
    )
    assert result is recipe_data
    assert connection.total_changes == before_changes
    assert connection.execute(
        "SELECT COUNT(*) FROM recipe_equipment_requirement_sync"
    ).fetchone()[0] == 0
    connection.close()


def test_projection_groups_and_or_and_phase3c1_derivations_without_image_leak(tmp_path):
    connection = _connection(tmp_path / "projection.sqlite3")
    _install_structured_schema(connection)
    master_image = "/master/do-not-project.png"
    target_id = _insert_equipment(
        connection, "Knife", image_url=master_image, image_path="master/knife.png"
    )
    recipe_data = {
        "equipment": [
            {
                "equipment": "Knife and cutting board",
                "optional": "false",
                "quantity": "2",
                "equipment_image_url": "/recipe/compound.png",
                "equipment_image_prompt": "recipe-only prompt",
            },
            {"equipment": "Wok or large skillet", "optional": True},
        ],
        "instructions": [],
    }
    _stage(connection, recipe_data)
    _resolve_all_equipment_options(connection, target_id)
    first = connection.execute(
        "SELECT * FROM recipe_equipment_requirements ORDER BY sort_order, id LIMIT 1"
    ).fetchone()
    derived_id = "eqr_fixture_derived"
    cursor = connection.execute(
        """
        INSERT INTO recipe_equipment_requirements (
            requirement_id, user_id, recipe_id, source_text, optional, quantity,
            notes, sort_order, connector, conjunction_group, parse_confidence,
            review_status, parser_version, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 0, '2', '', 0, 'single', ?, 0.99, 'ready',
                  'phase3c1-approved', ?, 'now', 'now')
        """,
        (
            derived_id,
            TENANT,
            RECIPE,
            first["source_text"],
            first["conjunction_group"],
            json.dumps({
                "derived_from_requirement_id": first["requirement_id"],
                "semantics": "and",
            }),
        ),
    )
    connection.execute(
        """
        INSERT INTO recipe_equipment_options (
            option_id, user_id, requirement_id, equipment_id, source_option_text,
            canonical_name, canonical_key, option_kind, attributes_json, notes,
            sort_order, matched_alias_id, match_type, match_confidence,
            review_status, created_at, updated_at
        ) VALUES ('eqo_fixture_supply', ?, ?, NULL, 'parchment paper',
                  'Parchment paper', 'parchment paper', 'supply',
                  '{"purpose":"lining"}', '', 0, NULL,
                  'phase3c1_derived_approved', 0.99, 'ready', 'now', 'now')
        """,
        (TENANT, int(cursor.lastrowid)),
    )

    requirements = equipment.load_structured_equipment_requirements(
        connection, TENANT, RECIPE
    )
    semantic = equipment.semantic_equipment_projection(requirements)
    projected = equipment.compatibility_equipment_rows(
        requirements, legacy_rows=recipe_data["equipment"]
    )
    assert projected == recipe_data["equipment"]
    assert projected[0]["equipment_image_url"] == "/recipe/compound.png"
    assert master_image not in json.dumps(projected)
    assert len(semantic) == 2
    assert semantic[0]["connector"] == "and"
    assert semantic[0]["quantity"] == "2"
    assert len(semantic[0]["requirement_ids"]) == 3
    assert semantic[1]["connector"] == "or"
    assert len(semantic[1]["options"]) == 2
    assert any(option["option_kind"] == "supply" for option in semantic[0]["options"])
    assert any(option["attributes"] == {"purpose": "lining"} for option in semantic[0]["options"])
    connection.close()


def test_read_requires_current_sync_and_falls_back_for_pending_and_parser_empty(tmp_path):
    connection = _connection(tmp_path / "read.sqlite3")
    _install_structured_schema(connection)
    target_id = _insert_equipment(
        connection, "Whisk", image_url="/master/whisk.png"
    )
    recipe_data = {
        "equipment": [{
            "equipment": "Whisk",
            "equipment_image_url": "/recipe/whisk.png",
        }],
        "instructions": ["Whisk thoroughly."],
    }
    _stage(connection, recipe_data)
    _resolve_all_equipment_options(connection, target_id)

    result = equipment.structured_equipment_read_result(
        connection, TENANT, RECIPE, recipe_data
    )
    assert result["eligible"] is False
    assert result["fallback_reason"] == "missing_sync"

    _insert_sync(connection, recipe_data, source_hash="STALE")
    result = equipment.structured_equipment_read_result(
        connection, TENANT, RECIPE, recipe_data
    )
    assert result["fallback_reason"] == "stale_sync"

    _insert_sync(connection, recipe_data)
    result = equipment.structured_equipment_read_result(
        connection, TENANT, RECIPE, recipe_data
    )
    assert result["eligible"] is True
    assert result["equipment"] == recipe_data["equipment"]
    assert "/master/whisk.png" not in json.dumps(result["equipment"])

    connection.execute(
        "UPDATE recipe_equipment_requirements SET review_status = 'pending'"
    )
    assert equipment.structured_equipment_read_result(
        connection, TENANT, RECIPE, recipe_data
    )["fallback_reason"] == "pending_requirement"

    assert equipment.structured_equipment_read_result(
        connection, TENANT, "parser-empty", {"equipment": [{"equipment": ""}]}
    )["fallback_reason"] == "missing_structured_recipe"
    connection.close()


def test_repository_rejects_cross_tenant_option_even_when_database_is_corrupt(tmp_path):
    db_path = tmp_path / "tenant.sqlite3"
    connection = _connection(db_path)
    _install_structured_schema(connection)
    _stage(connection, {"equipment": [{"equipment": "Whisk"}]})
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("UPDATE recipe_equipment_options SET user_id = 'tenant-b'")
    connection.commit()
    with pytest.raises(equipment.StructuredEquipmentFallback) as error:
        equipment.load_structured_equipment_requirements(
            connection, TENANT, RECIPE, require_ready=False
        )
    assert error.value.reason == "tenant_violation"
    connection.close()


def test_shadow_comparison_never_changes_returned_data_and_emits_metrics(
    monkeypatch, tmp_path, caplog
):
    connection = _connection(tmp_path / "shadow.sqlite3")
    _install_structured_schema(connection)
    target_id = _insert_equipment(connection, "Whisk")
    recipe_data = {"equipment": [{"equipment": "Whisk"}], "instructions": []}
    _stage(connection, recipe_data)
    _resolve_all_equipment_options(connection, target_id)
    _insert_sync(connection, recipe_data)
    _enable(monkeypatch, "SHADOW")
    caplog.set_level(logging.INFO, logger=equipment.__name__)
    before = json.loads(json.dumps(recipe_data))
    result = equipment.apply_structured_equipment_read(
        RECIPE,
        recipe_data,
        user_id=TENANT,
        connection=connection,
        consumer="pdf_export",
    )
    assert result is recipe_data
    assert recipe_data == before
    message = "\n".join(record.getMessage() for record in caplog.records)
    assert '"event":"shadow_compare"' in message
    assert '"eligible":true' in message
    assert '"consumer":"pdf_export"' in message
    assert '"row_count_difference":0' in message
    assert '"wording_order_differences":0' in message
    assert '"image_differences":0' in message
    assert '"latency_ms":' in message
    connection.close()


def test_tenant_approved_read_uses_validated_projection_but_stays_user_equivalent(
    monkeypatch, tmp_path
):
    connection = _connection(tmp_path / "enabled-read.sqlite3")
    _install_structured_schema(connection)
    target_id = _insert_equipment(connection, "Whisk")
    recipe_data = {
        "equipment": [{"equipment": "Whisk", "equipment_image_url": "/recipe.png"}],
        "instructions": [],
    }
    _stage(connection, recipe_data)
    _resolve_all_equipment_options(connection, target_id)
    _insert_sync(connection, recipe_data)
    _enable(monkeypatch, "READ")
    projected = equipment.apply_structured_equipment_read(
        RECIPE,
        recipe_data,
        user_id=TENANT,
        connection=connection,
        consumer="editor_api",
    )
    assert projected == recipe_data
    assert projected is not recipe_data
    assert projected["equipment"] is not recipe_data["equipment"]
    connection.close()


def _configure_master_database(monkeypatch, tmp_path):
    db_path = tmp_path / "master.sqlite3"
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)
    monkeypatch.delenv("SHOPPING_APP_RECIPE_MASTER_DB", raising=False)
    with master_data.recipe_master_connection() as connection:
        equipment.ensure_structured_equipment_schema(
            connection,
            authorized=True,
            migration_token=equipment.PHASE3A_MIGRATION_TOKEN,
        )
    return db_path


def test_dual_write_preserves_approvals_stages_uncertain_values_and_is_idempotent(
    monkeypatch, tmp_path
):
    db_path = _configure_master_database(monkeypatch, tmp_path)
    _enable(monkeypatch, "DUAL_WRITE")
    with master_data.recipe_master_connection() as connection:
        whisk = master_data.upsert_master_record(
            connection, "equipment", TENANT, "Whisk"
        )
        whisk_id = whisk["id"]

    recipe_data = {
        "equipment": [{"equipment": "Whisk", "quantity": "1"}],
        "instructions": ["Whisk."],
    }
    first = master_data.sync_recipe_master_records(
        RECIPE, recipe_data=recipe_data, user_id=TENANT
    )
    assert first["structured_equipment"]["options_inserted"] == 1

    with _connection(db_path) as connection:
        option = connection.execute(
            "SELECT * FROM recipe_equipment_options"
        ).fetchone()
        assert option["equipment_id"] == whisk_id
        assert option["review_status"] == "ready"
        connection.execute(
            """
            UPDATE recipe_equipment_options
               SET attributes_json = '{"approved":"keep"}',
                   match_type = 'owner_approved', match_confidence = 0.99
             WHERE id = ?
            """,
            (option["id"],),
        )
        approved_id = int(option["id"])

    second = master_data.sync_recipe_master_records(
        RECIPE, recipe_data=recipe_data, user_id=TENANT
    )
    assert second["structured_equipment"]["outcome"] == "idempotent_noop"
    with _connection(db_path) as connection:
        preserved = connection.execute(
            "SELECT * FROM recipe_equipment_options WHERE id = ?", (approved_id,)
        ).fetchone()
        assert preserved["attributes_json"] == '{"approved":"keep"}'
        assert preserved["match_type"] == "owner_approved"
        assert preserved["equipment_id"] == whisk_id

    changed = {
        "equipment": [
            {"equipment": "Whisk", "quantity": "1"},
            {"equipment": "ZXQ never reviewed"},
        ],
        "instructions": ["Whisk."],
    }
    master_data.sync_recipe_master_records(
        RECIPE, recipe_data=changed, user_id=TENANT
    )
    with _connection(db_path) as connection:
        uncertain = connection.execute(
            """
            SELECT o.*, r.review_status AS requirement_status
              FROM recipe_equipment_options o
              JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
             WHERE o.source_option_text = 'ZXQ never reviewed'
            """
        ).fetchone()
        assert uncertain["equipment_id"] is None
        assert uncertain["review_status"] == "pending"
        assert uncertain["requirement_status"] == "pending"
        assert connection.execute(
            """
            SELECT COUNT(*) FROM equipment_normalization_reviews
             WHERE user_id = ? AND source_kind = 'structured_dual_write'
               AND status = 'pending'
            """,
            (TENANT,),
        ).fetchone()[0] == 1


def test_dual_write_failure_injection_rolls_back_the_entire_structured_savepoint(
    monkeypatch, tmp_path
):
    db_path = _configure_master_database(monkeypatch, tmp_path)
    _enable(monkeypatch, "DUAL_WRITE")
    with master_data.recipe_master_connection() as connection:
        master_data.upsert_master_record(connection, "equipment", TENANT, "Whisk")
    base = {"equipment": [{"equipment": "Whisk"}], "instructions": []}
    master_data.sync_recipe_master_records(RECIPE, recipe_data=base, user_id=TENANT)
    connection = _connection(db_path)
    before = [tuple(row) for row in connection.execute(
        "SELECT * FROM recipe_equipment_requirements ORDER BY id"
    )]

    def fail(stage):
        if stage == "before_reviews":
            raise RuntimeError("injected transaction failure")

    with pytest.raises(RuntimeError, match="injected"):
        equipment.reconcile_recipe_requirements(
            connection,
            TENANT,
            RECIPE,
            {"equipment": [{"equipment": "Brand new uncertain value"}]},
            excluded_equipment_ids=set(),
            failure_injector=fail,
        )
    after = [tuple(row) for row in connection.execute(
        "SELECT * FROM recipe_equipment_requirements ORDER BY id"
    )]
    assert after == before
    connection.rollback()
    connection.close()


def test_identity_move_and_delete_preserve_scope_and_sync(monkeypatch, tmp_path):
    db_path = _configure_master_database(monkeypatch, tmp_path)
    _enable(monkeypatch, "DUAL_WRITE")
    with master_data.recipe_master_connection() as connection:
        master_data.upsert_master_record(connection, "equipment", TENANT, "Whisk")
    master_data.sync_recipe_master_records(
        RECIPE,
        recipe_data={"equipment": [{"equipment": "Whisk"}]},
        user_id=TENANT,
    )
    next_recipe = "https://example.com/recipe-renamed"
    with _connection(db_path) as connection:
        moved = equipment.move_structured_recipe_identity(
            connection, TENANT, RECIPE, next_recipe
        )
        assert moved["moved"] == 1
        assert connection.execute(
            "SELECT recipe_id FROM recipe_equipment_requirements"
        ).fetchone()[0] == next_recipe
        assert connection.execute(
            "SELECT recipe_id FROM recipe_equipment_requirement_sync"
        ).fetchone()[0] == next_recipe

    master_data.remove_recipe_master_records_for_recipe(next_recipe, user_id=TENANT)
    with _connection(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_requirements"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM recipe_equipment_requirement_sync"
        ).fetchone()[0] == 0


def test_actual_pending_queue_is_tenant_scoped(tmp_path):
    connection = _connection(tmp_path / "queue.sqlite3")
    _install_structured_schema(connection)
    _stage(connection, {"equipment": [{"equipment": "Bowl"}]})
    _stage(
        connection,
        {"equipment": [{"equipment": "Other tenant item"}]},
        tenant="tenant-b",
        recipe_id="recipe-b",
    )
    queue = equipment.structured_equipment_review_queue(TENANT, connection=connection)
    assert len(queue) == 1
    assert queue[0]["user_id"] == TENANT
    assert queue[0]["source_text"] == "Bowl"
    assert queue[0]["requirements"][0]["options"][0]["source_option_text"] == "Bowl"
    connection.close()


def test_projection_scale_fixture_covers_1068_recipes_and_four_explicit_fallbacks(tmp_path):
    connection = _connection(tmp_path / "scale.sqlite3")
    _install_structured_schema(connection)
    target_id = _insert_equipment(connection, "Whisk")
    exact = 0
    for index in range(1068):
        recipe_id = f"fixture://structured/{index}"
        recipe_data = {
            "equipment": [{
                "equipment": "Whisk",
                "optional": bool(index % 2),
                "equipment_image_url": f"/recipe/{index}.png" if index % 37 == 0 else "",
            }],
            "instructions": [],
        }
        _stage(connection, recipe_data, recipe_id=recipe_id)
        connection.execute(
            """
            UPDATE recipe_equipment_options
               SET equipment_id = ?, review_status = 'ready'
             WHERE requirement_id IN (
                SELECT id FROM recipe_equipment_requirements
                 WHERE user_id = ? AND recipe_id = ?
             )
            """,
            (target_id, TENANT, recipe_id),
        )
        connection.execute(
            """
            UPDATE recipe_equipment_requirements SET review_status = 'ready'
             WHERE user_id = ? AND recipe_id = ?
            """,
            (TENANT, recipe_id),
        )
        requirements = equipment.load_structured_equipment_requirements(
            connection, TENANT, recipe_id
        )
        exact += int(
            equipment.compatibility_equipment_rows(
                requirements, legacy_rows=recipe_data["equipment"]
            ) == recipe_data["equipment"]
        )
    assert exact == 1068
    for index in range(4):
        result = equipment.structured_equipment_read_result(
            connection,
            TENANT,
            f"fixture://parser-empty/{index}",
            {"equipment": [{"equipment": ""}]},
        )
        assert result["fallback_reason"] == "missing_structured_recipe"
    connection.close()
