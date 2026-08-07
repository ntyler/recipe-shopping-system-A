"""Approved Phase 3A backup and additive equipment staging workflow."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from PushShoppingList.services.equipment_migration_preview_service import (
    discover_output_roots,
    output_equipment,
    output_identity,
    output_instructions,
    workspace_id_for_output_root,
)
from PushShoppingList.services.equipment_normalization_service import (
    PARSER_VERSION,
    clean_text,
    normalized_equipment_key,
    parse_equipment_list,
)
from PushShoppingList.services import recipe_equipment_requirement_service as requirements


CLI_APPROVAL_PHRASE = "PHASE3A_APPROVED"
MIGRATION_VERSION = "equipment-requirements-phase3a-v1"

APPLICATION_FEATURE_FLAGS = {
    "RECIPE_EQUIPMENT_STRUCTURED_SHADOW_ENABLED": requirements.structured_equipment_shadow_enabled,
    "RECIPE_EQUIPMENT_STRUCTURED_DUAL_WRITE_ENABLED": requirements.structured_equipment_dual_write_enabled,
    "RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED": requirements.structured_equipment_ui_enabled,
    "RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED": requirements.structured_equipment_read_enabled,
    "RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED": requirements.structured_equipment_write_enabled,
    "RECIPE_EQUIPMENT_AUTHENTICATED_CANARY_ENABLED": (
        requirements.authenticated_equipment_canary_enabled
    ),
    "RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED": requirements.structured_equipment_schema_writes_enabled,
    "RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED": requirements.structured_equipment_review_writes_enabled,
}

LEGACY_EQUIPMENT_COLUMNS = (
    "id", "user_id", "name", "normalized_name", "display_name_override",
    "equipment_section", "image_url", "image_path", "created_at", "updated_at",
)
LEGACY_LINK_COLUMNS = (
    "id", "user_id", "recipe_id", "equipment_id", "original_recipe_text",
    "optional", "sort_order",
)


def _utc_now():
    return datetime.now(timezone.utc)


def enabled_application_feature_flags():
    return [name for name, resolver in APPLICATION_FEATURE_FLAGS.items() if resolver()]


def _utc_now_iso():
    return _utc_now().isoformat()


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _json_hash(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def _readonly_connection(db_path):
    db_path = Path(db_path).resolve()
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_exists(connection, table_name):
    return bool(connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (str(table_name),),
    ).fetchone())


def legacy_table_fingerprint(connection):
    equipment_rows = []
    link_rows = []
    if _table_exists(connection, "equipment"):
        equipment_rows = [
            list(row)
            for row in connection.execute(
                f"SELECT {', '.join(LEGACY_EQUIPMENT_COLUMNS)} FROM equipment ORDER BY id"
            ).fetchall()
        ]
    if _table_exists(connection, "recipe_equipment"):
        link_rows = [
            list(row)
            for row in connection.execute(
                f"SELECT {', '.join(LEGACY_LINK_COLUMNS)} FROM recipe_equipment ORDER BY id"
            ).fetchall()
        ]
    return {
        "equipment_count": len(equipment_rows),
        "recipe_equipment_count": len(link_rows),
        "equipment_sha256": _json_hash(equipment_rows),
        "recipe_equipment_sha256": _json_hash(link_rows),
    }


def active_output_file_manifest(repository_root, output_roots):
    repository_root = Path(repository_root).resolve()
    records = []
    for output_root in output_roots:
        for path in sorted(Path(output_root).glob("*.json"), key=lambda item: item.name.casefold()):
            if path.name == "sorted_ingredients.json":
                continue
            resolved = path.resolve()
            records.append({
                "path": str(resolved.relative_to(repository_root)),
                "size_bytes": resolved.stat().st_size,
                "sha256": _sha256_file(resolved),
            })
    return records


def source_snapshot(repository_root, db_path, output_roots):
    with _readonly_connection(db_path) as connection:
        legacy = legacy_table_fingerprint(connection)
    outputs = active_output_file_manifest(repository_root, output_roots)
    return {
        "legacy": legacy,
        "outputs": outputs,
        "source_hash": _json_hash({"legacy": legacy, "outputs": outputs}),
    }


def source_snapshot_with_connection(repository_root, connection, output_roots):
    legacy = legacy_table_fingerprint(connection)
    outputs = active_output_file_manifest(repository_root, output_roots)
    return {
        "legacy": legacy,
        "outputs": outputs,
        "source_hash": _json_hash({"legacy": legacy, "outputs": outputs}),
    }


def completed_run_for_source(db_path, source_hash):
    with _readonly_connection(db_path) as connection:
        if not _table_exists(connection, "equipment_requirement_migration_runs"):
            return None
        row = connection.execute(
            """
            SELECT id, run_key, summary_json, completed_at
              FROM equipment_requirement_migration_runs
             WHERE run_key = ? AND status = 'complete'
            """,
            (f"{MIGRATION_VERSION}:{source_hash}",),
        ).fetchone()
        if not row:
            return None
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            summary = {}
        return {
            **summary,
            "migration_run_id": int(row["id"]),
            "run_key": str(row["run_key"]),
            "completed_at": str(row["completed_at"] or ""),
            "idempotent_noop": True,
        }


def create_verified_backup(
    repository_root,
    db_path,
    output_roots,
    *,
    backup_base=None,
    expected_snapshot=None,
):
    repository_root = Path(repository_root).resolve()
    db_path = Path(db_path).resolve()
    backup_base = Path(backup_base or (
        repository_root
        / "PushShoppingList"
        / "user_data"
        / "equipment-requirement-migration-backups"
    )).resolve()
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_base / stamp
    if backup_dir.exists():
        backup_dir = backup_base / f"{stamp}-{uuid.uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    snapshot_before = expected_snapshot or source_snapshot(
        repository_root, db_path, output_roots
    )
    source_db_hash_before = _sha256_file(db_path)
    backup_db_path = backup_dir / "recipe_master.sqlite3"
    with _readonly_connection(db_path) as source, sqlite3.connect(backup_db_path) as destination:
        source.backup(destination)
        integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
        backup_legacy = legacy_table_fingerprint(destination)
    if integrity.casefold() != "ok":
        raise RuntimeError(f"Backup database integrity check failed: {integrity}")
    if backup_legacy != snapshot_before["legacy"]:
        raise RuntimeError("Backup database legacy-table fingerprint does not match the source snapshot.")

    copied_outputs = []
    for record in snapshot_before["outputs"]:
        source_path = repository_root / record["path"]
        destination_path = backup_dir / "recipe-output" / record["path"]
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        destination_hash = _sha256_file(destination_path)
        if destination_hash != record["sha256"]:
            raise RuntimeError(f"Backup hash mismatch for {record['path']}")
        copied_outputs.append({
            **record,
            "backup_path": str(destination_path.relative_to(backup_dir)),
        })

    snapshot_after = source_snapshot(repository_root, db_path, output_roots)
    source_db_hash_after = _sha256_file(db_path)
    if snapshot_after != snapshot_before or source_db_hash_after != source_db_hash_before:
        raise RuntimeError(
            "Source data changed while the backup was being created; staging was not started."
        )

    manifest = {
        "created_at": _utc_now_iso(),
        "verified": True,
        "source_database": str(db_path),
        "source_database_sha256": source_db_hash_before,
        "backup_database": str(backup_db_path),
        "backup_database_sha256": _sha256_file(backup_db_path),
        "database_integrity_check": integrity,
        "legacy_table_fingerprint": backup_legacy,
        "source_hash": snapshot_before["source_hash"],
        "output_file_count": len(copied_outputs),
        "outputs": copied_outputs,
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if not manifest_path.is_file() or not _sha256_file(manifest_path):
        raise RuntimeError("Backup manifest verification failed.")
    return {
        "backup_dir": str(backup_dir),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "database_backup_path": str(backup_db_path),
        "database_backup_sha256": manifest["backup_database_sha256"],
        "database_integrity_check": integrity,
        "output_file_count": len(copied_outputs),
        "source_hash": snapshot_before["source_hash"],
        "verified": True,
    }


def verified_backup_for_source(backup_base, source_hash):
    backup_base = Path(backup_base).resolve()
    if not backup_base.is_dir():
        return None
    manifests = sorted(
        backup_base.glob("*/manifest.json"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(manifest, dict):
            continue
        if not manifest.get("verified") or manifest.get("source_hash") != source_hash:
            continue
        backup_dir = manifest_path.parent
        database_path = Path(str(manifest.get("backup_database") or ""))
        if not database_path.is_absolute():
            database_path = backup_dir / database_path
        if not database_path.is_file():
            continue
        if _sha256_file(database_path) != manifest.get("backup_database_sha256"):
            continue
        outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), list) else []
        valid = True
        for record in outputs:
            backup_path = backup_dir / str(record.get("backup_path") or "")
            if not backup_path.is_file() or _sha256_file(backup_path) != record.get("sha256"):
                valid = False
                break
        if not valid:
            continue
        with sqlite3.connect(database_path) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.casefold() != "ok":
            continue
        return {
            "backup_dir": str(backup_dir),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256_file(manifest_path),
            "database_backup_path": str(database_path),
            "database_backup_sha256": manifest["backup_database_sha256"],
            "database_integrity_check": integrity,
            "output_file_count": len(outputs),
            "source_hash": source_hash,
            "verified": True,
            "reused": True,
        }
    return None


def _load_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Unable to read recipe JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Recipe JSON is not an object: {path}")
    return payload


def _recipe_key(value):
    from PushShoppingList.services.equipment_migration_preview_service import _url_key
    return _url_key(value)


def staged_recipe_sources(connection, output_roots):
    records = {}
    source_kinds = Counter()
    for output_root in output_roots:
        workspace_id = workspace_id_for_output_root(output_root)
        for path in sorted(Path(output_root).glob("*.json"), key=lambda item: item.name.casefold()):
            if path.name == "sorted_ingredients.json":
                continue
            payload = _load_json(path)
            recipe_id = _recipe_key(output_identity(payload))
            if not recipe_id:
                continue
            key = (workspace_id, recipe_id)
            if key in records:
                raise RuntimeError(
                    f"Stable recipe identity collision during staging: {workspace_id} {recipe_id}"
                )
            equipment = output_equipment(payload)
            if not equipment:
                continue
            records[key] = {
                "user_id": workspace_id,
                "recipe_id": recipe_id,
                "source_kind": "json",
                "source_path": str(path),
                "equipment": equipment,
                "instructions": output_instructions(payload),
            }
            source_kinds["json"] += 1

    sql_groups = defaultdict(list)
    sql_rows = connection.execute(
        """
        SELECT link.*, equipment.name AS equipment_name
          FROM recipe_equipment AS link
          JOIN equipment ON equipment.id = link.equipment_id
         ORDER BY link.user_id, link.recipe_id, link.sort_order, link.id
        """
    ).fetchall()
    for row in sql_rows:
        key = (str(row["user_id"]), _recipe_key(row["recipe_id"]))
        sql_groups[key].append(dict(row))

    for key, links in sql_groups.items():
        if key in records:
            continue
        records[key] = {
            "user_id": key[0],
            "recipe_id": key[1],
            "source_kind": "sql_only",
            "source_path": "",
            "equipment": [{
                "equipment": clean_text(
                    row.get("original_recipe_text") or row.get("equipment_name")
                ),
                "optional": bool(row.get("optional")),
            } for row in links],
            "instructions": [],
        }
        source_kinds["sql_only"] += 1
    return records, sql_rows, source_kinds


def _equipment_lookup(connection):
    lookup = defaultdict(list)
    for row in connection.execute(
        "SELECT id, user_id, name FROM equipment ORDER BY user_id, id"
    ).fetchall():
        key = normalized_equipment_key(row["name"])
        if key:
            lookup[(str(row["user_id"]), key)].append({
                "id": int(row["id"]),
                "name": str(row["name"]),
            })
    return lookup


def _insert_alias(connection, user_id, equipment_id, option, now):
    if option.get("match_type") != "alias":
        return None, False, False
    alias_name = clean_text(option.get("source_option_text"))
    alias_key = normalized_equipment_key(alias_name)
    if not alias_key or alias_key == option.get("canonical_key"):
        return None, False, False
    existing = connection.execute(
        "SELECT id, equipment_id FROM equipment_aliases WHERE user_id = ? AND alias_key = ?",
        (user_id, alias_key),
    ).fetchone()
    if existing:
        if int(existing["equipment_id"]) == int(equipment_id):
            return int(existing["id"]), False, False
        return None, False, True
    cursor = connection.execute(
        """
        INSERT INTO equipment_aliases (
            user_id, equipment_id, alias_name, alias_key, source, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'phase3a_backfill', 'active', ?, ?)
        """,
        (user_id, equipment_id, alias_name, alias_key, now, now),
    )
    return int(cursor.lastrowid), True, False


def _resolve_requirement_options(connection, lookup, user_id, requirement, now):
    requirement = deepcopy(requirement)
    counts = Counter()
    for option in requirement.get("options", []):
        option_kind = option.get("option_kind")
        if option_kind != "equipment":
            counts[f"{option_kind}_options"] += 1
            continue
        candidates = lookup.get((user_id, option.get("canonical_key")), [])
        if len(candidates) == 1:
            option["equipment_id"] = candidates[0]["id"]
            alias_id, inserted, conflict = _insert_alias(
                connection, user_id, candidates[0]["id"], option, now
            )
            if alias_id:
                option["matched_alias_id"] = alias_id
            if inserted:
                counts["aliases_inserted"] += 1
            if conflict:
                option["review_status"] = "needs_review"
                option["review_reason"] = "alias_conflict"
                counts["alias_conflicts"] += 1
            else:
                counts["matched_equipment_options"] += 1
        elif len(candidates) > 1:
            option["review_status"] = "needs_review"
            option["review_reason"] = "ambiguous_existing_equipment"
            counts["ambiguous_equipment_options"] += 1
        else:
            option["review_status"] = "pending_master"
            option["review_reason"] = "canonical_equipment_missing"
            counts["pending_master_options"] += 1

    if any(
        option.get("review_status") not in {"ready", ""}
        for option in requirement.get("options", [])
    ):
        requirement["review_status"] = "pending"
    elif requirement.get("review_status") == "needs_review":
        requirement["review_status"] = "pending"
    else:
        requirement["review_status"] = "ready"
    return requirement, counts


def _upsert_pending_review(connection, user_id, recipe_id, requirement, source_kind, now):
    if requirement.get("review_status") == "ready":
        return False
    source_record_id = f"{recipe_id}#{requirement.get('requirement_id')}"
    proposal = json.dumps(requirement, ensure_ascii=False, sort_keys=True, default=str)
    connection.execute(
        """
        INSERT INTO equipment_normalization_reviews (
            user_id, source_kind, source_record_id, source_text, proposal_json,
            confidence, status, decision, decision_note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', '', ?, ?)
        ON CONFLICT(user_id, source_kind, source_record_id, source_text) DO UPDATE SET
            proposal_json = excluded.proposal_json,
            confidence = excluded.confidence,
            updated_at = excluded.updated_at
        WHERE equipment_normalization_reviews.status = 'pending'
        """,
        (
            user_id,
            source_kind,
            source_record_id,
            requirement.get("source_text", ""),
            proposal,
            float(requirement.get("parse_confidence") or 0),
            now,
            now,
        ),
    )
    return True


def _logical_requirement_index(staged_requirements):
    index = defaultdict(list)
    for key, requirements_list in staged_requirements.items():
        for requirement in requirements_list:
            index[(key[0], key[1], normalized_equipment_key(requirement.get("source_text")))].append(requirement)
    return index


def _stage_migration_maps(
    connection,
    run_id,
    sql_rows,
    staged_requirements,
    now,
):
    requirement_index = _logical_requirement_index(staged_requirements)
    mapped_links = 0
    unmapped_links = 0
    map_rows = 0
    for row in sql_rows:
        user_id = str(row["user_id"])
        recipe_id = _recipe_key(row["recipe_id"])
        source_text = clean_text(row["original_recipe_text"] or row["equipment_name"])
        candidates = requirement_index.get(
            (user_id, recipe_id, normalized_equipment_key(source_text)),
            [],
        )
        requirement = candidates[0] if candidates else None
        options = requirement.get("options", []) if requirement else []
        if requirement:
            mapped_links += 1
        else:
            unmapped_links += 1
            options = [None]
        for option in options or [None]:
            after = {
                "requirement": requirement,
                "option": option,
            }
            connection.execute(
                """
                INSERT INTO equipment_requirement_migration_map (
                    migration_run_id, user_id, recipe_id,
                    legacy_recipe_equipment_id, legacy_equipment_id,
                    requirement_id, option_id, decision,
                    before_json, after_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, user_id, recipe_id, int(row["id"]), int(row["equipment_id"]),
                    requirement.get("requirement_id", "") if requirement else "",
                    option.get("option_id", "") if option else "",
                    "staged" if requirement else "unmapped",
                    json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str),
                    json.dumps(after, ensure_ascii=False, sort_keys=True, default=str),
                    now,
                ),
            )
            map_rows += 1
    return {
        "legacy_links_mapped": mapped_links,
        "legacy_links_unmapped": unmapped_links,
        "migration_map_rows": map_rows,
    }


def stage_phase3a_migration(
    repository_root,
    *,
    db_path=None,
    output_roots=None,
    backup_base=None,
    approval_phrase="",
):
    if str(approval_phrase or "") != CLI_APPROVAL_PHRASE:
        raise PermissionError(
            f"Phase 3A staging requires approval_phrase={CLI_APPROVAL_PHRASE!r}."
        )
    enabled_flags = enabled_application_feature_flags()
    if enabled_flags:
        raise RuntimeError(
            "Phase 3A requires all structured-equipment application flags to remain disabled: "
            + ", ".join(enabled_flags)
        )
    repository_root = Path(repository_root).resolve()
    db_path = Path(db_path or (
        repository_root / "PushShoppingList" / "user_data" / "recipe_master.sqlite3"
    )).resolve()
    output_roots = (
        [Path(path).resolve() for path in output_roots]
        if output_roots is not None
        else discover_output_roots(repository_root)
    )
    resolved_backup_base = Path(backup_base or (
        repository_root
        / "PushShoppingList"
        / "user_data"
        / "equipment-requirement-migration-backups"
    )).resolve()
    snapshot = source_snapshot(repository_root, db_path, output_roots)
    existing_run = completed_run_for_source(db_path, snapshot["source_hash"])
    if existing_run:
        return existing_run

    backup = verified_backup_for_source(
        resolved_backup_base,
        snapshot["source_hash"],
    )
    if backup is None:
        backup = create_verified_backup(
            repository_root,
            db_path,
            output_roots,
            backup_base=resolved_backup_base,
            expected_snapshot=snapshot,
        )
    if backup["source_hash"] != snapshot["source_hash"]:
        raise RuntimeError("Verified backup source hash does not match the staging source hash.")

    connection = sqlite3.connect(db_path, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    legacy_before = legacy_table_fingerprint(connection)
    if legacy_before != snapshot["legacy"]:
        connection.close()
        raise RuntimeError("Legacy database content changed after backup; staging was not started.")

    requirements.ensure_structured_equipment_schema(
        connection,
        authorized=True,
        migration_token=requirements.PHASE3A_MIGRATION_TOKEN,
    )
    run_key = f"{MIGRATION_VERSION}:{snapshot['source_hash']}"
    now = _utc_now_iso()
    summary = {
        "mode": "phase3a_stage",
        "migration_version": MIGRATION_VERSION,
        "parser_version": PARSER_VERSION,
        "run_key": run_key,
        "source_hash": snapshot["source_hash"],
        "backup": backup,
        "legacy_before": legacy_before,
        "feature_flags_enabled": enabled_flags,
        "idempotent_noop": False,
    }

    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            INSERT INTO equipment_requirement_migration_runs (
                run_key, mode, source_hash, status, summary_json, started_at
            ) VALUES (?, 'stage', ?, 'running', '{}', ?)
            """,
            (run_key, snapshot["source_hash"], now),
        )
        run_id = int(cursor.lastrowid)

        recipe_sources, sql_rows, source_kinds = staged_recipe_sources(
            connection, output_roots
        )
        lookup = _equipment_lookup(connection)
        staged_requirements = {}
        counts = Counter()
        connection.execute("DELETE FROM recipe_equipment_requirements")
        connection.execute(
            "DELETE FROM equipment_normalization_reviews WHERE status = 'pending'"
        )

        for key in sorted(recipe_sources):
            source = recipe_sources[key]
            parsed = parse_equipment_list(
                source["equipment"], instructions=source["instructions"]
            )
            resolved = []
            for requirement in parsed:
                resolved_requirement, resolution_counts = _resolve_requirement_options(
                    connection, lookup, source["user_id"], requirement, now
                )
                counts.update(resolution_counts)
                resolved.append(resolved_requirement)
                counts["requirements_staged"] += 1
                counts["options_staged"] += len(resolved_requirement.get("options", []))
                if resolved_requirement.get("review_status") == "ready":
                    counts["ready_requirements"] += 1
                elif _upsert_pending_review(
                    connection,
                    source["user_id"],
                    source["recipe_id"],
                    resolved_requirement,
                    source["source_kind"],
                    now,
                ):
                    counts["pending_reviews"] += 1

            requirements.replace_recipe_requirements(
                connection,
                source["user_id"],
                source["recipe_id"],
                resolved,
                authorized=True,
                migration_token=requirements.PHASE3A_MIGRATION_TOKEN,
            )
            staged_requirements[key] = resolved
            counts["recipes_staged"] += 1

        mapping_summary = _stage_migration_maps(
            connection, run_id, sql_rows, staged_requirements, now
        )
        counts.update(mapping_summary)

        snapshot_at_commit = source_snapshot_with_connection(
            repository_root,
            connection,
            output_roots,
        )
        if snapshot_at_commit["source_hash"] != snapshot["source_hash"]:
            raise RuntimeError("Legacy source data changed during staging; transaction rolled back.")
        legacy_after = legacy_table_fingerprint(connection)
        if legacy_after != legacy_before:
            raise RuntimeError("Legacy equipment tables changed during staging; transaction rolled back.")

        summary.update({
            "migration_run_id": run_id,
            "completed_at": _utc_now_iso(),
            "source_kinds": dict(source_kinds),
            "counts": dict(counts),
            "legacy_after": legacy_after,
            "legacy_unchanged": legacy_after == legacy_before,
        })
        connection.execute(
            """
            UPDATE equipment_requirement_migration_runs
               SET status = 'complete', summary_json = ?, completed_at = ?
             WHERE id = ?
            """,
            (
                json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str),
                summary["completed_at"],
                run_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    with _readonly_connection(db_path) as verification:
        final_legacy = legacy_table_fingerprint(verification)
        summary["post_commit"] = {
            "legacy_unchanged": final_legacy == legacy_before,
            "legacy_fingerprint": final_legacy,
            "requirement_rows": int(verification.execute(
                "SELECT COUNT(*) FROM recipe_equipment_requirements"
            ).fetchone()[0]),
            "option_rows": int(verification.execute(
                "SELECT COUNT(*) FROM recipe_equipment_options"
            ).fetchone()[0]),
            "pending_review_rows": int(verification.execute(
                "SELECT COUNT(*) FROM equipment_normalization_reviews WHERE status = 'pending'"
            ).fetchone()[0]),
            "alias_rows": int(verification.execute(
                "SELECT COUNT(*) FROM equipment_aliases"
            ).fetchone()[0]),
            "migration_map_rows": int(verification.execute(
                "SELECT COUNT(*) FROM equipment_requirement_migration_map WHERE migration_run_id = ?",
                (summary["migration_run_id"],),
            ).fetchone()[0]),
        }
    if not summary["post_commit"]["legacy_unchanged"]:
        raise RuntimeError("Post-commit legacy-table verification failed.")
    if enabled_application_feature_flags():
        raise RuntimeError("A structured-equipment application feature flag became enabled during staging.")
    return summary
