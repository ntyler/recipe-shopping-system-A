"""Workspace-scoped registry for recipe cuisine categories."""

import json
import re
import threading
import unicodedata
import uuid
from copy import deepcopy
from pathlib import Path

from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key


CUISINE_CATEGORY_SEEDS = (
    ("american", "🇺🇸 American"),
    ("mexican", "🇲🇽 Mexican"),
    ("peruvian", "🇵🇪 Peruvian"),
    ("italian", "🇮🇹 Italian"),
    ("japanese", "🇯🇵 Japanese"),
    ("thai", "🇹🇭 Thai"),
    ("chinese", "🇨🇳 Chinese"),
    ("indian", "🇮🇳 Indian"),
    ("french", "🇫🇷 French"),
    ("other_fusion", "🌍 Other / Fusion"),
)
CUISINE_CATEGORY_SEED_VERSION = "cuisine_categories_v1"
CUISINE_CATEGORY_NAME_LIMIT = 60
_CUISINE_CATEGORY_DATA_LOCK = threading.RLock()


def clean_cuisine_category_name(value):
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).strip(),
    )


def cuisine_category_key(value):
    """Return a comparison key that treats a leading flag as presentation."""
    value = clean_cuisine_category_name(value).casefold()
    value = re.sub(r"^[^\w]+", "", value, flags=re.UNICODE)
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"\s*/\s*", " / ", value)
    return re.sub(r"\s+", " ", value).strip()


# Cuisine labels are intentionally matched exactly. National labels get a
# helpful flag, while regional or stylistic labels (for example Mediterranean,
# Cajun, or Fusion) remain untouched rather than receiving a guessed identity.
NATIONAL_CUISINE_COUNTRY_CODES = {
    "american": "US",
    "united states": "US",
    "canada": "CA",
    "canadian": "CA",
    "mexican": "MX",
    "mexico": "MX",
    "peru": "PE",
    "peruvian": "PE",
    "argentina": "AR",
    "argentine": "AR",
    "argentinian": "AR",
    "brazil": "BR",
    "brazilian": "BR",
    "chile": "CL",
    "chilean": "CL",
    "colombia": "CO",
    "colombian": "CO",
    "venezuela": "VE",
    "venezuelan": "VE",
    "cuba": "CU",
    "cuban": "CU",
    "jamaica": "JM",
    "jamaican": "JM",
    "united kingdom": "GB",
    "british": "GB",
    "english": "GB",
    "scottish": "GB",
    "welsh": "GB",
    "northern irish": "GB",
    "ireland": "IE",
    "irish": "IE",
    "france": "FR",
    "french": "FR",
    "italy": "IT",
    "italian": "IT",
    "spain": "ES",
    "spanish": "ES",
    "portugal": "PT",
    "portuguese": "PT",
    "germany": "DE",
    "german": "DE",
    "austria": "AT",
    "austrian": "AT",
    "switzerland": "CH",
    "swiss": "CH",
    "belgium": "BE",
    "belgian": "BE",
    "netherlands": "NL",
    "dutch": "NL",
    "denmark": "DK",
    "danish": "DK",
    "sweden": "SE",
    "swedish": "SE",
    "norway": "NO",
    "norwegian": "NO",
    "finland": "FI",
    "finnish": "FI",
    "poland": "PL",
    "polish": "PL",
    "greece": "GR",
    "greek": "GR",
    "czechia": "CZ",
    "czech": "CZ",
    "hungary": "HU",
    "hungarian": "HU",
    "ukraine": "UA",
    "ukrainian": "UA",
    "russia": "RU",
    "russian": "RU",
    "turkey": "TR",
    "turkish": "TR",
    "lebanon": "LB",
    "lebanese": "LB",
    "israel": "IL",
    "israeli": "IL",
    "iran": "IR",
    "iranian": "IR",
    "egypt": "EG",
    "egyptian": "EG",
    "morocco": "MA",
    "moroccan": "MA",
    "ethiopia": "ET",
    "ethiopian": "ET",
    "nigeria": "NG",
    "nigerian": "NG",
    "south africa": "ZA",
    "south african": "ZA",
    "india": "IN",
    "indian": "IN",
    "pakistan": "PK",
    "pakistani": "PK",
    "bangladesh": "BD",
    "bangladeshi": "BD",
    "sri lanka": "LK",
    "sri lankan": "LK",
    "nepal": "NP",
    "nepalese": "NP",
    "china": "CN",
    "chinese": "CN",
    "hong kong": "HK",
    "taiwan": "TW",
    "taiwanese": "TW",
    "japan": "JP",
    "japanese": "JP",
    "south korea": "KR",
    "south korean": "KR",
    "korea": "KR",
    "korean": "KR",
    "vietnam": "VN",
    "vietnamese": "VN",
    "thailand": "TH",
    "thai": "TH",
    "indonesia": "ID",
    "indonesian": "ID",
    "malaysia": "MY",
    "malaysian": "MY",
    "philippines": "PH",
    "filipino": "PH",
    "singapore": "SG",
    "singaporean": "SG",
    "australia": "AU",
    "australian": "AU",
    "new zealand": "NZ",
}


def country_flag_emoji(country_code):
    """Build a Unicode flag from a validated ISO alpha-2 country code."""
    country_code = str(country_code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        return ""
    return "".join(
        chr(0x1F1E6 + ord(character) - ord("A"))
        for character in country_code
    )


def decorate_recognized_cuisine_name(value):
    """Add a flag to exact national cuisine labels without guessing regions."""
    name = clean_cuisine_category_name(value)
    if not name or not name[0].isalnum():
        return name
    country_code = NATIONAL_CUISINE_COUNTRY_CODES.get(cuisine_category_key(name))
    flag = country_flag_emoji(country_code)
    return f"{flag} {name}" if flag else name


def _json_text_list(value):
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    result = []
    seen = set()
    for item in decoded:
        cleaned = clean_cuisine_category_name(item)
        key = cuisine_category_key(cleaned)
        if not cleaned or not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _seed_aliases(category_id):
    for seed_id, seed_name in CUISINE_CATEGORY_SEEDS:
        if seed_id != category_id:
            continue
        plain_name = re.sub(r"^[^\w]+", "", seed_name, flags=re.UNICODE).strip()
        return [seed_id, seed_name, plain_name]
    return []


def _category_item_from_row(row):
    seeded = bool(row["is_seeded"])
    category_id = str(row["id"])
    aliases = _json_text_list(row["aliases_json"])
    aliases.extend(_seed_aliases(category_id) if seeded else [])
    return {
        "id": category_id,
        "name": str(row["name"]),
        "seeded": seeded,
        "custom": not seeded,
        "active": bool(row["is_active"]),
        "sort_order": int(row["sort_order"] or 0),
        "updated_at": str(row["updated_at"] or ""),
        "_aliases": aliases,
    }


def _registry_from_connection(connection, user_id):
    rows = connection.execute(
        """
        SELECT id, name, normalized_name, aliases_json, is_seeded, is_active,
               sort_order, created_at, updated_at
          FROM workspace_cuisine_categories
         WHERE user_id = ?
         ORDER BY sort_order ASC, normalized_name ASC, id ASC
        """,
        (user_id,),
    ).fetchall()
    return {"categories": [_category_item_from_row(row) for row in rows]}


def _internal_default_registry():
    return {
        "categories": [
            {
                "id": category_id,
                "name": name,
                "seeded": True,
                "custom": False,
                "active": True,
                "sort_order": sort_order,
                "updated_at": "",
                "_aliases": _seed_aliases(category_id),
            }
            for sort_order, (category_id, name) in enumerate(CUISINE_CATEGORY_SEEDS)
        ]
    }


def _public_category(item, recipe_count=None):
    category = {
        key: value
        for key, value in item.items()
        if not str(key).startswith("_")
    }
    aliases = []
    seen_aliases = set()
    stored_name = clean_cuisine_category_name(item.get("name"))
    current_name = decorate_recognized_cuisine_name(stored_name)
    category["name"] = current_name
    category_id = str(item.get("id") or "")
    raw_aliases = list(item.get("_aliases", []))
    if stored_name and stored_name != current_name:
        raw_aliases.insert(0, stored_name)
    for raw_alias in raw_aliases:
        alias = clean_cuisine_category_name(raw_alias)
        alias_key = alias.casefold()
        if (
            not alias
            or alias == category_id
            or alias == current_name
            or alias_key in seen_aliases
        ):
            continue
        seen_aliases.add(alias_key)
        aliases.append(alias)
    category["aliases"] = aliases
    if recipe_count is not None:
        category["recipe_count"] = int(recipe_count or 0)
    return category


def _public_registry(registry, usage_counts=None):
    usage_counts = usage_counts if isinstance(usage_counts, dict) else None
    return {
        "categories": [
            _public_category(
                item,
                usage_counts.get(str(item["id"]), 0) if usage_counts is not None else None,
            )
            for item in registry.get("categories", [])
        ]
    }


def default_cuisine_category_registry_payload():
    """Return built-in cuisine categories without creating workspace rows."""
    return _public_registry(_internal_default_registry())


def _seed_registry(connection, user_id):
    marker = connection.execute(
        """
        SELECT seed_version
          FROM workspace_cuisine_category_registry_seeds
         WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if marker and str(marker["seed_version"]) == CUISINE_CATEGORY_SEED_VERSION:
        return False

    timestamp = master_data.utc_now_iso()
    for sort_order, (category_id, name) in enumerate(CUISINE_CATEGORY_SEEDS):
        connection.execute(
            """
            INSERT OR IGNORE INTO workspace_cuisine_categories (
                user_id, id, name, normalized_name, aliases_json, is_seeded,
                is_active, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '[]', 1, 1, ?, ?, ?)
            """,
            (
                user_id,
                category_id,
                name,
                cuisine_category_key(name),
                sort_order,
                timestamp,
                timestamp,
            ),
        )
    connection.execute(
        """
        INSERT INTO workspace_cuisine_category_registry_seeds (
            user_id, seed_version, seeded_at
        ) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            seed_version = excluded.seed_version,
            seeded_at = excluded.seeded_at
        """,
        (user_id, CUISINE_CATEGORY_SEED_VERSION, timestamp),
    )
    return True


def _category_lookup(registry):
    lookup = {}
    for item in registry.get("categories", []):
        category_id = str(item.get("id") or "")
        values = [category_id, item.get("name"), *item.get("_aliases", [])]
        for value in values:
            key = cuisine_category_key(value)
            if key:
                lookup.setdefault(key, category_id)
    return lookup


def _workspace_identity(user_id):
    if user_id.startswith(master_data.GUEST_RECIPE_OWNER_PREFIX):
        subject_id = user_id[len(master_data.GUEST_RECIPE_OWNER_PREFIX):]
        return user_id, "guest", subject_id
    return user_id, "user", user_id


def _workspace_cookbooks_path(user_id):
    if user_id == master_data.LOCAL_USER_ID:
        return storage_service.PACKAGE_DIR / "cookbooks.json"
    if user_id.startswith(master_data.GUEST_RECIPE_OWNER_PREFIX):
        subject_id = storage_service.safe_user_id(
            user_id[len(master_data.GUEST_RECIPE_OWNER_PREFIX):]
        )
        return storage_service.GUEST_DATA_DIR / subject_id / "cookbooks.json"
    return (
        storage_service.USER_DATA_DIR
        / storage_service.safe_user_id(user_id)
        / "cookbooks.json"
    )


def _load_workspace_cookbooks(user_id):
    path = _workspace_cookbooks_path(user_id)
    workspace_id, workspace_type, subject_id = _workspace_identity(user_id)

    mode = durable_runtime.durable_backend_mode()
    if mode in {"db_only", "db_preferred"}:
        state = durable_runtime.database_document_state(
            workspace_id=workspace_id,
            domain="cookbooks",
            document_key="catalog",
            source_key="cookbooks",
            source_ref="cookbooks.json",
        )
        if state == "deleted" or (mode == "db_only" and state == "absent"):
            return {"cookbooks": []}

    def legacy_loader():
        payload = master_data.load_json_file(path)
        return payload if isinstance(payload, dict) else {"cookbooks": []}

    payload = durable_runtime.load_json_document(
        legacy_loader,
        domain="cookbooks",
        document_key="catalog",
        source_key="cookbooks",
        source_ref="cookbooks.json",
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
    )
    return payload if isinstance(payload, dict) else {"cookbooks": []}


def _save_workspace_cookbooks(user_id, payload):
    path = _workspace_cookbooks_path(user_id)
    workspace_id, workspace_type, subject_id = _workspace_identity(user_id)

    def legacy_saver(value):
        path.parent.mkdir(parents=True, exist_ok=True)
        durable_runtime.atomic_write_json(path, value)
        return value

    return durable_runtime.save_json_document(
        payload,
        legacy_saver,
        domain="cookbooks",
        document_key="catalog",
        source_key="cookbooks",
        source_ref="cookbooks.json",
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
    )


def _workspace_recipe_output_folder(user_id):
    if user_id == master_data.LOCAL_USER_ID:
        return storage_service.LEGACY_EXTRACTOR_DIR / "data" / "output"
    if user_id.startswith(master_data.GUEST_RECIPE_OWNER_PREFIX):
        subject_id = storage_service.safe_user_id(
            user_id[len(master_data.GUEST_RECIPE_OWNER_PREFIX):]
        )
        return (
            storage_service.GUEST_DATA_DIR
            / subject_id
            / "recipe-extractor"
            / "data"
            / "output"
        )
    return (
        storage_service.USER_DATA_DIR
        / storage_service.safe_user_id(user_id)
        / "recipe-extractor"
        / "data"
        / "output"
    )


def _load_workspace_recipe_metadata(user_id):
    path = master_data.recipe_reference_metadata_path(user_id)
    workspace_id, workspace_type, subject_id = _workspace_identity(user_id)

    mode = durable_runtime.durable_backend_mode()
    if mode in {"db_only", "db_preferred"}:
        state = durable_runtime.database_document_state(
            workspace_id=workspace_id,
            domain="recipes",
            document_key="ingredients_index",
            source_key="recipe_metadata",
            source_ref="recipe-extractor/data/recipe_ingredients.json",
        )
        if state == "deleted" or (mode == "db_only" and state == "absent"):
            return {}

    def legacy_loader():
        payload = master_data.load_json_file(path)
        return payload if isinstance(payload, dict) else {}

    payload = durable_runtime.load_json_document(
        legacy_loader,
        domain="recipes",
        document_key="ingredients_index",
        source_key="recipe_metadata",
        source_ref="recipe-extractor/data/recipe_ingredients.json",
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
    )
    return payload if isinstance(payload, dict) else {}


def _save_workspace_recipe_metadata(user_id, payload):
    path = master_data.recipe_reference_metadata_path(user_id)
    workspace_id, workspace_type, subject_id = _workspace_identity(user_id)

    def legacy_saver(value):
        return durable_runtime.atomic_write_json(path, value)

    return durable_runtime.save_json_document(
        payload,
        legacy_saver,
        domain="recipes",
        document_key="ingredients_index",
        source_key="recipe_metadata",
        source_ref="recipe-extractor/data/recipe_ingredients.json",
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
    )


def _recipe_output_entry(recipe_edit, document, path, *, document_key="", source_ref=""):
    if not isinstance(document, dict):
        return None
    recipe_key = recipe_edit.recipe_output_identity_key(document)
    if not recipe_key:
        return None
    recipe_url = recipe_edit.recipe_output_identity_url(document)
    path = Path(path)
    try:
        resolved_document_key = str(document_key or recipe_edit.recipe_output_document_key(
            document,
            fallback_url=recipe_url or str(path),
        ))
        resolved_source_ref = str(
            source_ref or recipe_edit.recipe_output_source_ref(path)
        )
    except durable_runtime.DurableDocumentRuntimeError:
        return None
    return {
        "recipe_key": recipe_key,
        "recipe_url": recipe_url,
        "document": document,
        "path": path,
        "document_key": resolved_document_key,
        "source_ref": resolved_source_ref,
    }


def _add_recipe_output_entry(entries, collisions, entry):
    if not entry:
        return
    recipe_key = str(entry["recipe_key"])
    if recipe_key in collisions:
        return
    if recipe_key in entries:
        entries.pop(recipe_key, None)
        collisions.add(recipe_key)
        return
    entries[recipe_key] = entry


def _workspace_recipe_output_entries_unlocked(user_id, recipe_edit):
    mode = durable_runtime.durable_backend_mode()
    output_folder = _workspace_recipe_output_folder(user_id)
    entries = {}
    collisions = set()

    if mode != "db_only":
        for path in sorted(
            output_folder.glob("*.json"),
            key=lambda item: item.name.casefold(),
        ):
            if path.name == "sorted_ingredients.json":
                continue
            payload = master_data.load_json_file(path)
            _add_recipe_output_entry(
                entries,
                collisions,
                _recipe_output_entry(recipe_edit, payload, path),
            )

    # Shadow reads are intentionally legacy-authoritative, matching the recipe
    # editor. The shadow database is updated whenever a legacy output is saved.
    if mode in {"json", "shadow"}:
        return list(entries.values())

    workspace_id, _workspace_type, _subject_id = _workspace_identity(user_id)
    records = durable_runtime.list_database_documents(
        workspace_id=workspace_id,
        domain="recipes",
        source_key=recipe_edit.RECIPE_OUTPUT_SOURCE_KEY,
        require_schema=mode == "db_only",
        include_deleted=True,
    )
    legacy_keys_by_document = {
        str(entry["document_key"]): recipe_key
        for recipe_key, entry in entries.items()
    }
    for record in records:
        if record.get("status") != "deleted":
            continue
        legacy_key = legacy_keys_by_document.get(str(record.get("document_key") or ""))
        if legacy_key:
            entries.pop(legacy_key, None)

    database_entries = {}
    database_collisions = set()
    for record in records:
        document = record.get("document")
        if record.get("status") != "covered" or not isinstance(document, dict):
            continue
        source_ref = str(record.get("source_ref") or "")
        filename = Path(source_ref).name
        recipe_url = recipe_edit.recipe_output_identity_url(document)
        path = (
            output_folder / filename
            if filename.lower().endswith(".json")
            else recipe_edit.recipe_output_json_path(
                recipe_url,
                output_folder=output_folder,
            )
        )
        _add_recipe_output_entry(
            database_entries,
            database_collisions,
            _recipe_output_entry(
                recipe_edit,
                document,
                path,
                document_key=str(record.get("document_key") or ""),
                source_ref=source_ref,
            ),
        )
    for recipe_key in database_collisions:
        entries.pop(recipe_key, None)
    entries.update(database_entries)
    return list(entries.values())


def _workspace_recipe_output_entries(user_id):
    from PushShoppingList.services import recipe_edit_service as recipe_edit

    with recipe_edit._RECIPE_OUTPUT_WRITE_LOCK:
        return _workspace_recipe_output_entries_unlocked(user_id, recipe_edit)


def _save_workspace_recipe_output(user_id, entry, document, recipe_edit):
    path = Path(entry["path"])
    workspace_id, workspace_type, subject_id = _workspace_identity(user_id)

    def legacy_saver(value):
        return durable_runtime.atomic_write_json(path, value, newline=False)

    return durable_runtime.save_json_document(
        document,
        legacy_saver,
        domain="recipes",
        document_key=str(entry["document_key"]),
        source_key=recipe_edit.RECIPE_OUTPUT_SOURCE_KEY,
        source_ref=str(entry["source_ref"]),
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
        db_preferred_create_if_legacy_missing=lambda: not path.is_file(),
    )


def _category_text_values(value):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, (list, tuple, set)):
                yield from _category_text_values(item)
                continue
            cleaned = clean_cuisine_category_name(item)
            if cleaned:
                yield cleaned
        return
    cleaned = clean_cuisine_category_name(value)
    if not cleaned:
        return
    parts = [
        clean_cuisine_category_name(part)
        for part in re.split(r"[,;\r\n]+", str(value or ""))
    ]
    for part in parts:
        if part:
            yield part


def _category_containers(record):
    if not isinstance(record, dict):
        return []
    containers = [("", record)]
    for key in ("category_metadata", "raw"):
        nested = record.get(key)
        if isinstance(nested, dict):
            containers.append((f"{key}.", nested))
    return containers


def _record_category_matches(record, lookup, source):
    matches_by_category = {}
    seen = set()
    for prefix, container in _category_containers(record):
        for field in ("cuisine", "cuisine_tags"):
            for value in _category_text_values(container.get(field)):
                category_id = lookup.get(cuisine_category_key(value))
                match_key = (category_id, prefix + field, cuisine_category_key(value), source)
                if not category_id or match_key in seen:
                    continue
                seen.add(match_key)
                matches_by_category.setdefault(category_id, []).append({
                    "field": prefix + field,
                    "value": value,
                    "source": source,
                })
    return matches_by_category


def _reference_identity(recipe_id, record):
    recipe_id = master_data.clean_text(recipe_id)
    record = record if isinstance(record, dict) else {}
    recipe_url = master_data.clean_text(record.get("url")) or recipe_id
    normalized = normalize_recipe_url_key(recipe_url) if recipe_url else ""
    return normalized or recipe_url.casefold() or recipe_id.casefold(), recipe_url


def _merge_reference(
    references,
    *,
    recipe_id,
    record,
    source,
    matches_by_category,
):
    identity, recipe_url = _reference_identity(recipe_id, record)
    if not identity:
        return
    for category_id, matches in matches_by_category.items():
        category_references = references.setdefault(category_id, {})
        reference = category_references.setdefault(identity, {
            "recipe_id": master_data.clean_text(recipe_id) or recipe_url,
            "recipe_url": recipe_url,
            "recipe_title": master_data.recipe_reference_title(recipe_id, record),
            "cover_image": dict(record.get("cover_image"))
            if isinstance(record.get("cover_image"), dict)
            else {},
            "matches": [],
            "_match_keys": set(),
        })
        if (
            reference["recipe_title"] in {"", "Recipe"}
            and master_data.recipe_reference_title(recipe_id, record)
        ):
            reference["recipe_title"] = master_data.recipe_reference_title(
                recipe_id,
                record,
            )
        if not reference["cover_image"] and isinstance(record.get("cover_image"), dict):
            reference["cover_image"] = dict(record["cover_image"])
        for match in matches:
            match_key = (
                match.get("field"),
                cuisine_category_key(match.get("value")),
                match.get("source") or source,
            )
            if match_key in reference["_match_keys"]:
                continue
            reference["_match_keys"].add(match_key)
            reference["matches"].append(match)


def _usage_references(user_id, registry):
    lookup = _category_lookup(registry)
    references = {
        str(item["id"]): {}
        for item in registry.get("categories", [])
    }
    for entry in _workspace_recipe_output_entries(user_id):
        record = entry.get("document")
        if not isinstance(record, dict):
            continue
        recipe_url = str(entry.get("recipe_url") or "")
        _merge_reference(
            references,
            recipe_id=recipe_url,
            record=record,
            source="recipe",
            matches_by_category=_record_category_matches(record, lookup, "recipe"),
        )

    # Keep older category-bearing ingredient indexes readable while the full
    # recipe-output document remains the canonical assignment source.
    metadata = _load_workspace_recipe_metadata(user_id)
    if isinstance(metadata, dict):
        for recipe_id, record in metadata.items():
            if not isinstance(record, dict):
                continue
            _merge_reference(
                references,
                recipe_id=recipe_id,
                record=record,
                source="recipe",
                matches_by_category=_record_category_matches(record, lookup, "recipe"),
            )

    from PushShoppingList.services import cookbook_service

    with cookbook_service.COOKBOOKS_LOCK:
        cookbooks = _load_workspace_cookbooks(user_id)
    for cookbook in cookbooks.get("cookbooks", []):
        if not isinstance(cookbook, dict):
            continue
        for record in cookbook.get("recipes", []):
            if not isinstance(record, dict):
                continue
            recipe_id = master_data.clean_text(record.get("url"))
            _merge_reference(
                references,
                recipe_id=recipe_id,
                record=record,
                source="cookbook",
                matches_by_category=_record_category_matches(record, lookup, "cookbook"),
            )

    result = {}
    for category_id, references_by_recipe in references.items():
        category_references = []
        for reference in references_by_recipe.values():
            reference.pop("_match_keys", None)
            category_references.append(reference)
        result[category_id] = sorted(
            category_references,
            key=lambda item: (
                str(item.get("recipe_title") or "").casefold(),
                str(item.get("recipe_url") or "").casefold(),
            ),
        )
    return result


def _usage_counts(user_id, registry):
    return {
        category_id: len(references)
        for category_id, references in _usage_references(user_id, registry).items()
    }


def _stored_registry(user_id):
    registry = _internal_default_registry()
    with master_data.existing_recipe_master_read_connection() as connection:
        if connection is not None and master_data.recipe_master_table_exists(
            connection,
            "workspace_cuisine_categories",
        ):
            stored = _registry_from_connection(connection, user_id)
            if stored.get("categories"):
                registry = stored
    return registry


def cuisine_category_registry_payload(user_id=None, include_usage=False):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    registry = _stored_registry(user_id)
    counts = _usage_counts(user_id, registry) if include_usage else None
    return _public_registry(registry, counts)


def active_workspace_cuisine_category_labels(user_id=None):
    registry = cuisine_category_registry_payload(user_id=user_id)
    return [
        str(item["name"])
        for item in registry.get("categories", [])
        if item.get("active")
    ]


def workspace_cuisine_category_recipe_references(
    category_id,
    user_id=None,
    limit=100,
):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    category_id = str(category_id or "").strip()
    try:
        limit = max(1, min(int(limit or 100), 500))
    except (TypeError, ValueError):
        limit = 100

    registry = _stored_registry(user_id)
    category = next(
        (
            item
            for item in registry.get("categories", [])
            if str(item.get("id")) == category_id
        ),
        None,
    )
    if not category:
        return {
            "category": None,
            "references": [],
            "total": 0,
            "total_reference_count": 0,
            "limit": limit,
        }
    references = _usage_references(user_id, registry).get(category_id, [])
    return {
        "category": _public_category(category, len(references)),
        "references": references[:limit],
        "total": len(references),
        # A recipe is one reference even when both cuisine fields contain it.
        "total_reference_count": len(references),
        "limit": limit,
    }


def _replace_category_value(value, previous_keys, replacement):
    if isinstance(value, list):
        updated = []
        changed = False
        for item in value:
            replacement_item, item_changed = _replace_category_value(
                item,
                previous_keys,
                replacement,
            )
            updated.append(replacement_item)
            changed = changed or item_changed
        if changed:
            deduplicated = []
            seen = set()
            for item in updated:
                key = cuisine_category_key(item) if isinstance(item, str) else ""
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                deduplicated.append(item)
            updated = deduplicated
        return updated, changed
    if not isinstance(value, str):
        return value, False
    if cuisine_category_key(value) in previous_keys:
        return replacement, value != replacement
    if not re.search(r"[,;\r\n]", value):
        return value, False
    parts = [
        clean_cuisine_category_name(part)
        for part in re.split(r"[,;\r\n]+", value)
    ]
    updated_parts = [
        replacement if cuisine_category_key(part) in previous_keys else part
        for part in parts
    ]
    deduplicated_parts = []
    seen = set()
    for part in updated_parts:
        key = cuisine_category_key(part)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduplicated_parts.append(part)
    updated_parts = deduplicated_parts
    updated = ", ".join(updated_parts)
    return updated, updated != value


def _replace_record_categories(record, previous_keys, replacement):
    if not isinstance(record, dict):
        return False
    changed = False
    for _prefix, container in _category_containers(record):
        for field in ("cuisine", "cuisine_tags"):
            if field not in container:
                continue
            updated, field_changed = _replace_category_value(
                container.get(field),
                previous_keys,
                replacement,
            )
            if field_changed:
                container[field] = updated
                changed = True
    return changed


def _migrate_workspace_category_values(user_id, previous_keys, replacement):
    summary = {"recipe_records": 0, "cookbook_records": 0}
    with _CUISINE_CATEGORY_DATA_LOCK:
        from PushShoppingList.services import cookbook_service
        from PushShoppingList.services import recipe_edit_service as recipe_edit

        recipe_backups = []
        metadata_backup = None
        metadata_saved = False
        changed_recipe_keys = set()
        try:
            with recipe_edit._RECIPE_OUTPUT_WRITE_LOCK:
                entries = _workspace_recipe_output_entries_unlocked(
                    user_id,
                    recipe_edit,
                )
                for entry in entries:
                    original = deepcopy(entry["document"])
                    updated = deepcopy(original)
                    if not _replace_record_categories(
                        updated,
                        previous_keys,
                        replacement,
                    ):
                        continue
                    _save_workspace_recipe_output(
                        user_id,
                        entry,
                        updated,
                        recipe_edit,
                    )
                    recipe_backups.append((entry, original))
                    changed_recipe_keys.add(str(entry["recipe_key"]))

                metadata = _load_workspace_recipe_metadata(user_id)
                updated_metadata = deepcopy(metadata)
                metadata_changed = False
                for recipe_id, record in updated_metadata.items():
                    if not _replace_record_categories(
                        record,
                        previous_keys,
                        replacement,
                    ):
                        continue
                    metadata_changed = True
                    identity, _recipe_url = _reference_identity(recipe_id, record)
                    if identity:
                        changed_recipe_keys.add(identity)
                if metadata_changed:
                    metadata_backup = metadata
                    _save_workspace_recipe_metadata(user_id, updated_metadata)
                    metadata_saved = True

            with cookbook_service.COOKBOOKS_LOCK:
                cookbooks = _load_workspace_cookbooks(user_id)
                updated_cookbooks = deepcopy(cookbooks)
                cookbooks_changed = False
                for cookbook in updated_cookbooks.get("cookbooks", []):
                    if not isinstance(cookbook, dict):
                        continue
                    for record in cookbook.get("recipes", []):
                        if _replace_record_categories(
                            record,
                            previous_keys,
                            replacement,
                        ):
                            summary["cookbook_records"] += 1
                            cookbooks_changed = True
                if cookbooks_changed:
                    _save_workspace_cookbooks(user_id, updated_cookbooks)
        except BaseException as migration_error:
            rollback_error = None
            try:
                with recipe_edit._RECIPE_OUTPUT_WRITE_LOCK:
                    if metadata_saved:
                        _save_workspace_recipe_metadata(user_id, metadata_backup)
                    for entry, original in reversed(recipe_backups):
                        _save_workspace_recipe_output(
                            user_id,
                            entry,
                            original,
                            recipe_edit,
                        )
            except BaseException as exc:
                rollback_error = exc
            if rollback_error is not None:
                raise rollback_error from migration_error
            raise
        summary["recipe_records"] = len(changed_recipe_keys)
    return summary


def _category_collision(registry, name, current_id=""):
    target_key = cuisine_category_key(name)
    for item in registry.get("categories", []):
        if str(item.get("id")) == current_id:
            continue
        values = [item.get("id"), item.get("name"), *item.get("_aliases", [])]
        if target_key in {cuisine_category_key(value) for value in values}:
            return item
    return None


def save_workspace_cuisine_category(values, category_id="", user_id=None):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    category_id = str(category_id or "").strip()
    values = values if isinstance(values, dict) else {}
    raw_name = values.get("name") or values.get("canonical_name")
    normalized_raw_name = unicodedata.normalize("NFKC", str(raw_name or ""))
    name = decorate_recognized_cuisine_name(normalized_raw_name)
    active = bool(values.get("active", True))
    errors = {}
    if not name:
        errors["name"] = "Enter a cuisine category name."
    elif len(name) > CUISINE_CATEGORY_NAME_LIMIT:
        errors["name"] = f"Use {CUISINE_CATEGORY_NAME_LIMIT} characters or fewer."
    elif re.search(r"[,;\r\n]", normalized_raw_name):
        errors["name"] = "Cuisine category names cannot contain commas, semicolons, or line breaks."
    elif not cuisine_category_key(name):
        errors["name"] = "Enter a cuisine category name containing letters or numbers."

    migration = {"recipe_records": 0, "cookbook_records": 0}
    migration_keys = set()
    with master_data.recipe_master_connection(user_id=user_id) as connection:
        _seed_registry(connection, user_id)
        registry = _registry_from_connection(connection, user_id)
        existing = None
        if category_id:
            existing = connection.execute(
                """
                SELECT * FROM workspace_cuisine_categories
                 WHERE user_id = ? AND id = ?
                """,
                (user_id, category_id),
            ).fetchone()
            if not existing:
                return {
                    "ok": False,
                    "status": 404,
                    "error": "Cuisine category not found.",
                }
            if bool(existing["is_seeded"]) and name != str(existing["name"]):
                errors["name"] = "Built-in cuisine category names cannot be changed."
        if name and _category_collision(registry, name, category_id):
            errors["name"] = "A cuisine category with that name already exists."
        if errors:
            return {
                "ok": False,
                "status": 422,
                "error": "Correct the highlighted cuisine category fields.",
                "errors": errors,
            }

        timestamp = master_data.utc_now_iso()
        if existing:
            previous_name = str(existing["name"])
            aliases = _json_text_list(existing["aliases_json"])
            if previous_name != name:
                migration_keys = {
                    cuisine_category_key(value)
                    for value in (
                        category_id,
                        previous_name,
                        *aliases,
                        *_seed_aliases(category_id),
                    )
                    if cuisine_category_key(value)
                }
                aliases = _json_text_list(json.dumps(
                    [*aliases, previous_name],
                    ensure_ascii=False,
                ))
            connection.execute(
                """
                UPDATE workspace_cuisine_categories
                   SET name = ?, normalized_name = ?, aliases_json = ?,
                       is_active = ?, updated_at = ?
                 WHERE user_id = ? AND id = ?
                """,
                (
                    name,
                    cuisine_category_key(name),
                    json.dumps(aliases, ensure_ascii=False),
                    1 if active else 0,
                    timestamp,
                    user_id,
                    category_id,
                ),
            )
        else:
            category_id = f"custom_{uuid.uuid4().hex}"
            sort_order = int(connection.execute(
                """
                SELECT COALESCE(MAX(sort_order), -1) + 1
                  FROM workspace_cuisine_categories
                 WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO workspace_cuisine_categories (
                    user_id, id, name, normalized_name, aliases_json, is_seeded,
                    is_active, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '[]', 0, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    category_id,
                    name,
                    cuisine_category_key(name),
                    1 if active else 0,
                    sort_order,
                    timestamp,
                    timestamp,
                ),
            )
        registry = _registry_from_connection(connection, user_id)

    # File-backed and durable cookbook metadata may use another SQLite
    # connection. Perform that compatibility migration after committing the
    # registry transaction so db-only deployments cannot self-deadlock.
    if migration_keys:
        migration = _migrate_workspace_category_values(
            user_id,
            migration_keys,
            name,
        )

    return {
        "ok": True,
        "created": not bool(existing),
        "category_id": category_id,
        "name": name,
        "message": f'{name} {"added" if not existing else "updated"}.',
        "migration": migration,
        "registry": _public_registry(registry),
    }


def delete_workspace_cuisine_category(category_id, user_id=None):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    category_id = str(category_id or "").strip()
    with master_data.recipe_master_connection(user_id=user_id) as connection:
        _seed_registry(connection, user_id)
        existing = connection.execute(
            """
            SELECT * FROM workspace_cuisine_categories
             WHERE user_id = ? AND id = ?
            """,
            (user_id, category_id),
        ).fetchone()
        if not existing:
            return {
                "ok": False,
                "status": 404,
                "error": "Cuisine category not found.",
            }
        if bool(existing["is_seeded"]):
            return {
                "ok": False,
                "status": 422,
                "error": (
                    "Built-in cuisine categories can be deactivated but not deleted."
                ),
            }
        registry = _registry_from_connection(connection, user_id)
        usage = _usage_counts(user_id, registry).get(category_id, 0)
        if usage:
            return {
                "ok": False,
                "status": 409,
                "error": (
                    f'{existing["name"]} is used by {usage} '
                    f'recipe{"s" if usage != 1 else ""}. Deactivate it instead.'
                ),
            }
        connection.execute(
            "DELETE FROM workspace_cuisine_categories WHERE user_id = ? AND id = ?",
            (user_id, category_id),
        )
        registry = _registry_from_connection(connection, user_id)
    return {
        "ok": True,
        "deleted": True,
        "category_id": category_id,
        "message": f'{existing["name"]} deleted.',
        "registry": _public_registry(registry),
    }


def import_workspace_cuisine_category_names(values, user_id=None):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    values = values if isinstance(values, list) else []
    imported = []
    skipped = []
    for value in values:
        name = clean_cuisine_category_name(value)
        if not name:
            continue
        result = save_workspace_cuisine_category(
            {"name": name, "active": True},
            user_id=user_id,
        )
        if result.get("ok") and result.get("created"):
            imported.append(str(result.get("name") or name))
        else:
            skipped.append(name)
    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "message": (
            f'Imported {len(imported)} cuisine '
            f'categor{"y" if len(imported) == 1 else "ies"}.'
            if imported
            else "No new cuisine categories were imported."
        ),
    }


# Naming aliases make the service easy to consume alongside the older type service.
workspace_cuisine_category_active_labels = active_workspace_cuisine_category_labels
import_workspace_cuisine_categories = import_workspace_cuisine_category_names
