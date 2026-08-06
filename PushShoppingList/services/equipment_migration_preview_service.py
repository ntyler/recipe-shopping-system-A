"""Read-only migration preview for structured equipment requirements."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PushShoppingList.services.equipment_normalization_service import (
    PARSER_VERSION,
    parse_equipment_list,
    requirement_summary,
)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _clean(value):
    return str(value or "").strip()


def _url_key(value):
    value = _clean(value)
    if not value:
        return ""
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.rstrip("/")
    return urlunsplit((
        parsed.scheme.casefold(),
        parsed.netloc.casefold(),
        parsed.path.rstrip("/"),
        parsed.query,
        "",
    ))


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def discover_output_roots(repository_root):
    repository_root = Path(repository_root).resolve()
    package_root = repository_root / "PushShoppingList"
    candidates = []
    for path in package_root.rglob("output") if package_root.exists() else []:
        if not path.is_dir() or path.parent.name != "data" or path.parent.parent.name != "recipe-extractor":
            continue
        relative_parts = path.relative_to(package_root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if any("backup" in part.casefold() for part in relative_parts):
            continue
        candidates.append(path.resolve())
    return sorted(set(candidates), key=lambda path: str(path).casefold())


def workspace_id_for_output_root(output_root):
    parts = list(Path(output_root).parts)
    lowered = [part.casefold() for part in parts]
    if "users" in lowered:
        index = lowered.index("users")
        if index + 1 < len(parts):
            return parts[index + 1]
    if "guests" in lowered:
        index = lowered.index("guests")
        if index + 1 < len(parts):
            return f"guest:{parts[index + 1]}"
    return "local"


def output_identity(payload):
    payload = payload if isinstance(payload, dict) else {}
    return _clean(
        payload.get("recipe_record_url")
        or payload.get("source_url")
        or payload.get("url")
        or payload.get("original_url")
    )


def output_equipment(payload):
    payload = payload if isinstance(payload, dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    raw_equipment = raw.get("equipment")
    if isinstance(raw_equipment, list) and raw_equipment:
        return raw_equipment
    return payload.get("equipment") if isinstance(payload.get("equipment"), list) else []


def output_instructions(payload):
    payload = payload if isinstance(payload, dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    raw_instructions = raw.get("instructions")
    if isinstance(raw_instructions, list) and raw_instructions:
        return raw_instructions
    return payload.get("instructions") if isinstance(payload.get("instructions"), list) else []


def _semantic_recipe_fingerprint(payload):
    payload = payload if isinstance(payload, dict) else {}
    semantic = {
        "recipe_id": payload.get("recipe_id"),
        "recipe_record_url": payload.get("recipe_record_url"),
        "recipe_title": payload.get("recipe_title") or payload.get("display_name"),
        "menu_item_id": payload.get("menu_item_id"),
        "ingredients": payload.get("ingredients"),
        "equipment": output_equipment(payload),
        "instructions": output_instructions(payload),
    }
    serialized = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _readonly_connection(db_path):
    db_path = Path(db_path).resolve()
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_names(connection):
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _parse_accumulator():
    return Counter({
        "source_rows": 0,
        "requirements": 0,
        "options": 0,
        "alternative_requirements": 0,
        "conjoined_requirements": 0,
        "review_requirements": 0,
        "supply_options": 0,
        "facility_options": 0,
        "ingredient_options": 0,
    })


def _accumulate_parse(accumulator, requirements):
    summary = requirement_summary(requirements)
    accumulator["source_rows"] += 1
    accumulator["requirements"] += summary["requirement_count"]
    accumulator["options"] += summary["option_count"]
    accumulator["alternative_requirements"] += summary["alternative_requirement_count"]
    accumulator["conjoined_requirements"] += summary["conjoined_requirement_count"]
    accumulator["review_requirements"] += summary["review_requirement_count"]
    accumulator["supply_options"] += summary["supply_option_count"]
    accumulator["facility_options"] += summary["facility_option_count"]
    accumulator["ingredient_options"] += summary["ingredient_option_count"]


def build_equipment_migration_preview(
    repository_root,
    *,
    db_path=None,
    output_roots=None,
    review_sample_limit=50,
):
    """Build a report without opening any writable database or output handle."""
    repository_root = Path(repository_root).resolve()
    db_path = Path(db_path or (
        repository_root / "PushShoppingList" / "user_data" / "recipe_master.sqlite3"
    )).resolve()
    output_roots = (
        [Path(path).resolve() for path in output_roots]
        if output_roots is not None
        else discover_output_roots(repository_root)
    )
    if not db_path.is_file():
        raise FileNotFoundError(f"Recipe master database not found: {db_path}")

    before_hash = _sha256_file(db_path)
    report = {
        "mode": "dry-run",
        "read_only": True,
        "write_operations_performed": False,
        "generated_at": _utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "database": {
            "path": str(db_path),
            "size_bytes": db_path.stat().st_size,
            "sha256_before": before_hash,
        },
        "outputs": {},
        "identity": {},
        "current_sql": {},
        "proposed": {},
        "review_sample": [],
        "blockers": [],
    }

    sql_recipe_keys = set()
    sql_parse = _parse_accumulator()
    canonical_keys = set()
    with _readonly_connection(db_path) as connection:
        tables = _table_names(connection)
        if {"equipment", "recipe_equipment"}.issubset(tables):
            counts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM equipment) AS equipment_count,
                    (SELECT COUNT(*) FROM recipe_equipment) AS link_count,
                    (SELECT COUNT(DISTINCT user_id || char(0) || recipe_id) FROM recipe_equipment) AS recipe_count
                """
            ).fetchone()
            report["current_sql"] = {
                "equipment_records": int(counts["equipment_count"] or 0),
                "recipe_equipment_links": int(counts["link_count"] or 0),
                "distinct_workspace_recipes": int(counts["recipe_count"] or 0),
            }
            rows = connection.execute(
                """
                SELECT
                    link.id AS link_id,
                    link.user_id,
                    link.recipe_id,
                    link.original_recipe_text,
                    link.optional,
                    link.sort_order,
                    equipment.id AS equipment_id,
                    equipment.name AS equipment_name
                FROM recipe_equipment AS link
                JOIN equipment ON equipment.id = link.equipment_id
                ORDER BY link.user_id, link.recipe_id, link.sort_order, link.id
                """
            )
            for row in rows:
                recipe_key = (str(row["user_id"]), _url_key(row["recipe_id"]))
                sql_recipe_keys.add(recipe_key)
                source_text = _clean(row["original_recipe_text"] or row["equipment_name"])
                requirements = parse_equipment_list(
                    [{
                        "equipment": source_text,
                        "optional": bool(row["optional"]),
                    }]
                )
                _accumulate_parse(sql_parse, requirements)
                for requirement in requirements:
                    for option in requirement.get("options", []):
                        canonical_keys.add((str(row["user_id"]), option.get("canonical_key")))
                if (
                    any(item.get("review_status") == "needs_review" for item in requirements)
                    and len(report["review_sample"]) < int(review_sample_limit)
                ):
                    report["review_sample"].append({
                        "source": "sql",
                        "user_id": str(row["user_id"]),
                        "recipe_id": str(row["recipe_id"]),
                        "legacy_link_id": int(row["link_id"]),
                        "legacy_equipment_id": int(row["equipment_id"]),
                        "source_text": source_text,
                        "requirements": requirements,
                    })
        else:
            report["blockers"].append("The equipment or recipe_equipment table is missing.")

    output_records = []
    malformed_files = []
    legacy_groups = defaultdict(list)
    stable_groups = defaultdict(list)
    workspace_file_counts = Counter()
    for output_root in output_roots:
        workspace_id = workspace_id_for_output_root(output_root)
        for json_path in sorted(output_root.glob("*.json"), key=lambda path: path.name.casefold()):
            if json_path.name == "sorted_ingredients.json":
                continue
            workspace_file_counts[workspace_id] += 1
            payload = _load_json(json_path)
            if payload is None:
                malformed_files.append(str(json_path))
                continue
            source_key = _url_key(payload.get("source_url"))
            stable_url = output_identity(payload)
            stable_key = _url_key(stable_url)
            record = {
                "workspace_id": workspace_id,
                "path": str(json_path),
                "payload": payload,
                "legacy_key": source_key,
                "stable_key": stable_key,
                "stable_url": stable_url,
            }
            output_records.append(record)
            if source_key:
                legacy_groups[(workspace_id, source_key)].append(record)
            if stable_key:
                stable_groups[(workspace_id, stable_key)].append(record)

    legacy_collisions = {
        key: records for key, records in legacy_groups.items() if len(records) > 1
    }
    stable_collisions = {
        key: records for key, records in stable_groups.items() if len(records) > 1
    }
    stable_divergent_collisions = {
        key: records
        for key, records in stable_collisions.items()
        if len({_semantic_recipe_fingerprint(record["payload"]) for record in records}) > 1
    }
    stable_unique_records = [
        records[0]
        for key, records in stable_groups.items()
        if key not in stable_collisions
    ]

    json_recipe_keys = set()
    json_parse = _parse_accumulator()
    json_equipment_recipe_count = 0
    json_equipment_row_count = 0
    for record in stable_unique_records:
        payload = record["payload"]
        equipment = output_equipment(payload)
        if not equipment:
            continue
        json_equipment_recipe_count += 1
        json_equipment_row_count += len(equipment)
        recipe_key = (record["workspace_id"], record["stable_key"])
        json_recipe_keys.add(recipe_key)
        requirements = parse_equipment_list(
            equipment,
            instructions=output_instructions(payload),
        )
        for item in equipment:
            item_requirements = parse_equipment_list(
                [item],
                instructions=output_instructions(payload),
            )
            _accumulate_parse(json_parse, item_requirements)
        for requirement in requirements:
            for option in requirement.get("options", []):
                canonical_keys.add((record["workspace_id"], option.get("canonical_key")))
        if (
            any(item.get("review_status") == "needs_review" for item in requirements)
            and len(report["review_sample"]) < int(review_sample_limit)
        ):
            report["review_sample"].append({
                "source": "json",
                "user_id": record["workspace_id"],
                "recipe_id": record["stable_url"],
                "source_text": " | ".join(
                    _clean(item.get("equipment") or item.get("name") or item.get("text"))
                    if isinstance(item, dict) else _clean(item)
                    for item in equipment
                ),
                "requirements": requirements,
            })

    report["outputs"] = {
        "roots": [str(path) for path in output_roots],
        "workspace_file_counts": dict(sorted(workspace_file_counts.items())),
        "json_files": len(output_records) + len(malformed_files),
        "valid_json_files": len(output_records),
        "malformed_json_files": len(malformed_files),
        "stable_unique_recipes": len(stable_unique_records),
        "recipes_with_equipment": json_equipment_recipe_count,
        "equipment_rows": json_equipment_row_count,
    }
    report["identity"] = {
        "legacy_unique_keys": len(legacy_groups),
        "legacy_collision_keys": len(legacy_collisions),
        "legacy_records_in_collisions": sum(len(records) for records in legacy_collisions.values()),
        "stable_unique_keys": len(stable_groups),
        "stable_collision_keys": len(stable_collisions),
        "stable_records_in_collisions": sum(len(records) for records in stable_collisions.values()),
        "stable_divergent_collision_keys": len(stable_divergent_collisions),
        "collision_examples": [
            {
                "workspace_id": key[0],
                "legacy_key": key[1],
                "record_count": len(records),
                "stable_keys": [record["stable_key"] for record in records[:10]],
            }
            for key, records in sorted(
                legacy_collisions.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )[:10]
        ],
        "stable_collision_examples": [
            {
                "workspace_id": key[0],
                "stable_key": key[1],
                "record_count": len(records),
                "divergent": key in stable_divergent_collisions,
                "records": [
                    {
                        "path": record["path"],
                        "recipe_title": _clean(
                            record["payload"].get("recipe_title")
                            or record["payload"].get("display_name")
                        ),
                        "recipe_id": _clean(record["payload"].get("recipe_id")),
                        "menu_item_id": _clean(record["payload"].get("menu_item_id")),
                    }
                    for record in records[:10]
                ],
            }
            for key, records in sorted(stable_collisions.items(), key=lambda item: item[0])[:10]
        ],
    }
    report["proposed"] = {
        "sql_parse": dict(sql_parse),
        "json_parse": dict(json_parse),
        "workspace_canonical_keys": len({key for key in canonical_keys if key[1]}),
        "json_recipes_missing_from_sql": len(json_recipe_keys - sql_recipe_keys),
        "sql_recipes_missing_from_json": len(sql_recipe_keys - json_recipe_keys),
    }

    if stable_divergent_collisions:
        report["blockers"].append(
            f"{len(stable_divergent_collisions)} stable recipe identities remain divergent."
        )
    if report["proposed"]["json_recipes_missing_from_sql"]:
        report["blockers"].append(
            "JSON-only recipes require an approved reconciliation backfill."
        )
    if sql_parse["review_requirements"] or json_parse["review_requirements"]:
        report["blockers"].append(
            "Uncertain equipment proposals require human review before apply mode."
        )
    if malformed_files:
        report["blockers"].append("Malformed recipe JSON files must be resolved.")

    after_hash = _sha256_file(db_path)
    report["database"]["sha256_after"] = after_hash
    report["database"]["unchanged"] = before_hash == after_hash
    if before_hash != after_hash:
        raise RuntimeError("Database changed while the read-only preview was running.")
    return report
