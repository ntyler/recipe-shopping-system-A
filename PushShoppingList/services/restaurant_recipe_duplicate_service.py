"""User-scoped duplicate review and safe resolution for restaurant recipes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import threading

from flask import g, has_request_context

from PushShoppingList.services import cookbook_service
from PushShoppingList.services import menu_store_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services import recipe_master_data_service
from PushShoppingList.services import recipe_url_service
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services.file_lock_service import workspace_write_lock
from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import scoped_package_path


DUPLICATE_STATE_FILE = scoped_package_path("restaurant_recipe_duplicates.json")
DUPLICATE_LOCK = threading.RLock()
MERGE_SCALAR_FIELDS = (
    "recipe_title", "display_name", "description", "menu_description", "servings", "level",
    "total_time", "prep_time", "cook_time", "inactive_time", "nutrition", "cover_image",
    "menu_section", "meal_type", "cuisine", "main_ingredient", "cooking_method", "occasion",
    "dietary_preference", "rating", "menu_item_url", "source_pdf_path", "generated_pdf_path",
)
MERGE_LIST_FIELDS = ("ingredients", "instructions", "equipment", "tags", "custom_categories")


def _clean(value):
    return " ".join(str(value or "").strip().split())


def normalize_duplicate_recipe_name(value):
    text = _clean(value).casefold()
    text = re.sub(r"^[*#]+\s*", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _record_title(record):
    data = record.get("data") if isinstance(record, dict) else {}
    return recipe_edit_service.first_recipe_menu_text(
        data.get("recipe_title"), data.get("menu_item_name"), data.get("display_name"), "Untitled Recipe"
    )


def _record_url(record):
    return _clean(record.get("url") if isinstance(record, dict) else "")


def _record_recipe_id(record):
    data = record.get("data") if isinstance(record, dict) else {}
    return recipe_edit_service.first_recipe_menu_text(
        data.get("recipe_id"), data.get("id"), _record_url(record)
    )


def _record_source_identifier(record):
    data = record.get("data") if isinstance(record, dict) else {}
    metadata = recipe_edit_service.recipe_menu_source_metadata(data)
    stable_id = recipe_edit_service.first_recipe_menu_text(
        data.get("menu_item_id"), data.get("source_id"),
        metadata.get("menu_item_id"), metadata.get("source_id"),
    )
    if stable_id:
        return f"id:{stable_id.casefold()}"
    url = recipe_edit_service.first_recipe_menu_text(
        data.get("menu_item_url"), metadata.get("menu_item_url"),
        data.get("source_url"), metadata.get("source_url"), _record_url(record),
    )
    key = recipe_url_service.normalize_recipe_url_key(url)
    return f"url:{key}" if key else f"file:{record.get('path', '')}"


def _record_exact_source_keys(record):
    data = record.get("data") if isinstance(record, dict) else {}
    metadata = recipe_edit_service.recipe_menu_source_metadata(data)
    keys = set()
    stable_id = recipe_edit_service.first_recipe_menu_text(
        data.get("menu_item_id"), data.get("source_id"),
        metadata.get("menu_item_id"), metadata.get("source_id"),
    )
    if stable_id:
        keys.add(f"id:{stable_id.casefold()}")
    for value in (
        data.get("menu_item_url"), metadata.get("menu_item_url"),
        data.get("source_url"), metadata.get("source_url"), _record_url(record),
    ):
        key = recipe_url_service.normalize_recipe_url_key(value)
        if key:
            keys.add(f"url:{key}")
    return keys


def _record_group_identifier(record):
    recipe_id = _record_recipe_id(record)
    if recipe_id and recipe_id != _record_url(record):
        return f"recipe:{recipe_id.casefold()}"
    path = record.get("path") if isinstance(record, dict) else None
    return f"file:{Path(path).name.casefold()}" if path else _record_source_identifier(record)


def _record_key(record):
    identifier = _record_group_identifier(record)
    return f"record_{hashlib.sha256(identifier.encode('utf-8')).hexdigest()[:20]}"


def _group_signature(restaurant_id, records):
    payload = "|".join([_clean(restaurant_id), *sorted(_record_group_identifier(record) for record in records)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _group_id(signature):
    return f"dup_{signature[:20]}"


def load_duplicate_state():
    path = Path(DUPLICATE_STATE_FILE)
    if not path.exists():
        return {"ignored_groups": {}, "audit": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return {
        "ignored_groups": payload.get("ignored_groups") if isinstance(payload.get("ignored_groups"), dict) else {},
        "audit": payload.get("audit") if isinstance(payload.get("audit"), list) else [],
    }


def save_duplicate_state(payload):
    path = Path(DUPLICATE_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _usage_records(restaurant_id):
    inventory = None
    if has_request_context():
        cache = getattr(g, "_editable_restaurant_usage_inventories", {})
        inventory = cache.get(_clean(restaurant_id)) if isinstance(cache, dict) else None
    inventory = inventory or recipe_edit_service.editable_restaurant_usage_inventory(restaurant_id)
    if not inventory.get("ok"):
        return inventory, []
    records = [
        {**record, "match_kind": match_kind}
        for match_kind in ("normalized", "legacy_clear")
        for record in inventory.get("buckets", {}).get(match_kind, [])
    ]
    return inventory, records


def _similar_name_components(name_groups):
    keys = sorted(name_groups)
    parents = {key: key for key in keys}

    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    buckets = {}
    for key in keys:
        bucket = (key[:1], len(key) // 4)
        buckets.setdefault(bucket, []).append(key)
    for bucket_keys in buckets.values():
        for index, left in enumerate(bucket_keys):
            for right in bucket_keys[index + 1:]:
                if abs(len(left) - len(right)) <= 3 and SequenceMatcher(None, left, right).ratio() >= 0.94:
                    union(left, right)
    components = {}
    for key in keys:
        components.setdefault(find(key), []).extend(name_groups[key])
    return list(components.values())


def restaurant_recipe_duplicate_groups(restaurant_id, include_ignored=False):
    inventory, records = _usage_records(restaurant_id)
    if not inventory.get("ok"):
        return inventory
    name_groups = {}
    for record in records:
        name_key = normalize_duplicate_recipe_name(_record_title(record))
        if name_key:
            name_groups.setdefault(name_key, []).append(record)
    ignored = load_duplicate_state()["ignored_groups"]
    groups = []
    for component in _similar_name_components(name_groups):
        unique = {}
        for record in component:
            unique[record.get("identity") or f"{_record_url(record)}|{record.get('path', '')}"] = record
        component = list(unique.values())
        if len(component) < 2:
            continue
        signature = _group_signature(restaurant_id, component)
        ignored_record = ignored.get(signature)
        if ignored_record and not include_ignored:
            continue
        seen_source_keys = set()
        exact = False
        for record in component:
            source_keys = _record_exact_source_keys(record)
            if seen_source_keys.intersection(source_keys):
                exact = True
                break
            seen_source_keys.update(source_keys)
        groups.append({
            "group_id": _group_id(signature),
            "signature": signature,
            "restaurant_id": _clean(restaurant_id),
            "normalized_name": normalize_duplicate_recipe_name(_record_title(component[0])),
            "display_name": _record_title(component[0]),
            "count": len(component),
            "match_type": "exact" if exact else "possible",
            "badge_label": "Exact duplicate" if exact else f"{len(component)} similar",
            "ignored": bool(ignored_record),
            "records": component,
        })
    groups.sort(key=lambda group: (-group["count"], group["display_name"].casefold()))
    return {"ok": True, "restaurant_id": _clean(restaurant_id), "groups": groups}


def decorate_restaurant_usage_with_duplicates(result, restaurant_id):
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    grouped = restaurant_recipe_duplicate_groups(restaurant_id)
    if not grouped.get("ok"):
        return result
    group_by_url = {}
    for group in grouped["groups"]:
        for record in group["records"]:
            group_by_url[recipe_url_service.normalize_recipe_url_key(_record_url(record))] = group
    visible_groups = set()
    for row in result.get("recipes", []):
        group = group_by_url.get(recipe_url_service.normalize_recipe_url_key(row.get("url")))
        if not group:
            continue
        row["duplicate_group_id"] = group["group_id"]
        row["duplicate_group_count"] = group["count"]
        if group["group_id"] not in visible_groups:
            row["duplicate_badge"] = group["badge_label"]
            visible_groups.add(group["group_id"])
    result["duplicate_group_count"] = len(grouped["groups"])
    return result


def _ingredient_name(item):
    if isinstance(item, dict):
        return _clean(item.get("ingredient") or item.get("name") or item.get("display_name") or item.get("original_text"))
    return _clean(item)


def _instruction_text(item):
    if isinstance(item, dict):
        return _clean(item.get("instruction") or item.get("text") or item.get("description"))
    return _clean(item)


def _similarity_details(records):
    ingredient_sets = [
        {normalize_duplicate_recipe_name(_ingredient_name(item)) for item in record["data"].get("ingredients", []) if _ingredient_name(item)}
        for record in records
    ]
    instruction_texts = [" ".join(_instruction_text(item) for item in record["data"].get("instructions", [])) for record in records]
    sections = [normalize_duplicate_recipe_name(record["data"].get("menu_section")) for record in records]
    descriptions = [_clean(record["data"].get("description") or record["data"].get("menu_description")) for record in records]
    strongest = 0.0
    evidence = set()
    for index, left in enumerate(records):
        for right_index in range(index + 1, len(records)):
            left_ingredients, right_ingredients = ingredient_sets[index], ingredient_sets[right_index]
            if left_ingredients and right_ingredients:
                score = len(left_ingredients & right_ingredients) / max(1, len(left_ingredients | right_ingredients))
                strongest = max(strongest, score)
                if score >= 0.6:
                    evidence.add("ingredients")
            if instruction_texts[index] and instruction_texts[right_index]:
                score = SequenceMatcher(None, instruction_texts[index].casefold(), instruction_texts[right_index].casefold()).ratio()
                strongest = max(strongest, score)
                if score >= 0.72:
                    evidence.add("instructions")
            if descriptions[index] and descriptions[right_index]:
                score = SequenceMatcher(None, descriptions[index].casefold(), descriptions[right_index].casefold()).ratio()
                strongest = max(strongest, score)
                if score >= 0.72:
                    evidence.add("description")
            if sections[index] and sections[index] == sections[right_index]:
                evidence.add("menu section")
                strongest = max(strongest, 0.65)
    return {
        "match_type": "likely" if strongest >= 0.65 else "possible",
        "confidence": round(strongest, 2),
        "evidence": sorted(evidence),
    }


def _cookbook_assignments_for_url(recipe_url):
    target = recipe_url_service.normalize_recipe_url_key(recipe_url)
    assignments = []
    payload = cookbook_service.load_cookbooks_raw_payload()
    for cookbook in payload.get("cookbooks", []):
        for recipe in cookbook.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            if recipe_url_service.normalize_recipe_url_key(raw_url) == target:
                assignments.append({
                    "cookbook_id": _clean(cookbook.get("id")),
                    "cookbook_name": _clean(cookbook.get("name")),
                })
                break
    return assignments


def _record_detail(record, restaurant_name):
    data = record["data"]
    path = record.get("path")
    ingredients = [_ingredient_name(item) for item in data.get("ingredients", []) if _ingredient_name(item)]
    instructions = [_instruction_text(item) for item in data.get("instructions", []) if _instruction_text(item)]
    row = recipe_edit_service.editable_restaurant_usage_row(record)
    created = recipe_edit_service.first_recipe_menu_text(data.get("created_at"), data.get("imported_at"))
    updated = recipe_edit_service.first_recipe_menu_text(data.get("updated_at"), data.get("last_updated"))
    if path and Path(path).exists():
        modified = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()
        updated = updated or modified
        created = created or modified
    return {
        **row,
        "record_key": _record_key(record),
        "record_id": _record_recipe_id(record),
        "restaurant_name": restaurant_name,
        "menu_section": _clean(data.get("menu_section") or data.get("section")),
        "source_url": _record_url(record),
        "menu_item_url": _clean(data.get("menu_item_url") or data.get("source_url")),
        "cookbooks": _cookbook_assignments_for_url(_record_url(record)),
        "ingredients_summary": ", ".join(ingredients[:8]),
        "ingredients_count": len(ingredients),
        "instructions_summary": " ".join(instructions[:3]),
        "instructions_count": len(instructions),
        "created_at": created,
        "updated_at": updated,
    }


def restaurant_recipe_duplicate_group_detail(restaurant_id, group_id):
    grouped = restaurant_recipe_duplicate_groups(restaurant_id, include_ignored=True)
    if not grouped.get("ok"):
        return grouped
    group = next((item for item in grouped["groups"] if item["group_id"] == _clean(group_id)), None)
    if not group:
        return {"ok": False, "error": "Duplicate group was not found."}
    restaurant = recipe_edit_service.get_editable_restaurant(restaurant_id).get("restaurant", {})
    details = [_record_detail(record, restaurant.get("restaurant_name") or "Restaurant") for record in group["records"]]
    similarity = _similarity_details(group["records"])
    return {
        "ok": True,
        "group_id": group["group_id"],
        "signature": group["signature"],
        "restaurant_id": _clean(restaurant_id),
        "restaurant_name": _clean(restaurant.get("restaurant_name")),
        "display_name": group["display_name"],
        "count": group["count"],
        "match_type": "exact" if group["match_type"] == "exact" else similarity["match_type"],
        "confidence": 1.0 if group["match_type"] == "exact" else similarity["confidence"],
        "evidence": similarity["evidence"],
        "ignored": group["ignored"],
        "records": details,
    }


def set_restaurant_recipe_duplicate_disposition(restaurant_id, group_id, disposition):
    if disposition not in {"keep_both", "ignore"}:
        return {"ok": False, "error": "Duplicate disposition is invalid."}
    detail = restaurant_recipe_duplicate_group_detail(restaurant_id, group_id)
    if not detail.get("ok"):
        return detail
    with DUPLICATE_LOCK:
        state = load_duplicate_state()
        state["ignored_groups"][detail["signature"]] = {
            "restaurant_id": _clean(restaurant_id),
            "group_id": _clean(group_id),
            "disposition": disposition,
            "recipe_urls": [record["source_url"] for record in detail["records"]],
            "user_id": _clean(active_user_id()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        save_duplicate_state(state)
    return {"ok": True, "group_id": group_id, "disposition": disposition}


def _group_records(restaurant_id, group_id):
    grouped = restaurant_recipe_duplicate_groups(restaurant_id, include_ignored=True)
    if not grouped.get("ok"):
        return grouped, []
    group = next((item for item in grouped["groups"] if item["group_id"] == _clean(group_id)), None)
    if not group:
        return {"ok": False, "error": "Duplicate group was not found."}, []
    return group, group["records"]


def _record_for_key(records, record_key):
    key = _clean(record_key)
    return next((record for record in records if _record_key(record) == key), None)


def _nonempty(value):
    return value not in (None, "", [], {})


def _display_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _clean(value)


def _merge_conflicts(records):
    conflicts = []
    for field in MERGE_SCALAR_FIELDS:
        options = []
        seen = set()
        for record in records:
            value = record["data"].get(field)
            if not _nonempty(value):
                continue
            key = _display_value(value)
            if key in seen:
                continue
            seen.add(key)
            options.append({
                "record_key": _record_key(record),
                "recipe_url": _record_url(record),
                "recipe_title": _record_title(record),
                "value": value,
                "display_value": key[:500],
            })
        if len(options) > 1:
            conflicts.append({"field": field, "label": field.replace("_", " ").title(), "options": options})
    return conflicts


def _relationship_impacts(recipe_url):
    cookbooks = _cookbook_assignments_for_url(recipe_url)
    menu_relationships = 0
    store = menu_store_service.load_menu_store()
    target = recipe_url_service.normalize_recipe_url_key(recipe_url)
    for item in store.get("items", []):
        if recipe_url_service.normalize_recipe_url_key(item.get("recipe_url")) == target:
            menu_relationships += 1
    meta = recipe_ingredient_service.load_recipe_ingredients().get(target, {})
    ingredients = meta.get("ingredients") if isinstance(meta, dict) and isinstance(meta.get("ingredients"), list) else []
    return {
        "cookbook_count": len(cookbooks),
        "cookbooks": cookbooks,
        "menu_relationship_count": menu_relationships,
        "ingredient_relationship_count": len(ingredients),
    }


def restaurant_recipe_merge_preview(restaurant_id, group_id, primary_record_key, secondary_record_keys):
    group, records = _group_records(restaurant_id, group_id)
    if not records:
        return group
    primary = _record_for_key(records, primary_record_key)
    secondary_keys = {_clean(key) for key in secondary_record_keys or []}
    secondaries = [record for record in records if _record_key(record) in secondary_keys]
    if not primary:
        return {"ok": False, "error": "Choose a canonical recipe."}
    if not secondaries or any(record is primary for record in secondaries):
        return {"ok": False, "error": "Choose at least one different duplicate recipe to merge."}
    selected = [primary, *secondaries]
    return {
        "ok": True,
        "mode": "preview",
        "group_id": group_id,
        "primary_record_key": _record_key(primary),
        "secondary_record_keys": [_record_key(record) for record in secondaries],
        "primary_url": _record_url(primary),
        "secondary_urls": [_record_url(record) for record in secondaries],
        "conflicts": _merge_conflicts(selected),
        "impacts": {
            "primary": _relationship_impacts(_record_url(primary)),
            "secondaries": [
                {"recipe_url": _record_url(record), **_relationship_impacts(_record_url(record))}
                for record in secondaries
            ],
        },
    }


def restaurant_recipe_delete_preview(restaurant_id, group_id, recipe_record_key):
    group, records = _group_records(restaurant_id, group_id)
    if not records:
        return group
    record = _record_for_key(records, recipe_record_key)
    if not record:
        return {"ok": False, "error": "The duplicate recipe was not found."}
    target_url = recipe_url_service.normalize_recipe_url_key(_record_url(record))
    shared_source_record_count = sum(
        1 for item in records
        if item is not record and recipe_url_service.normalize_recipe_url_key(_record_url(item)) == target_url
    )
    impacts = _relationship_impacts(_record_url(record))
    if shared_source_record_count:
        impacts = {
            **impacts,
            "cookbook_count": 0,
            "cookbooks": [],
            "menu_relationship_count": 0,
            "ingredient_relationship_count": 0,
            "relationships_retained": True,
            "shared_source_record_count": shared_source_record_count,
        }
    return {
        "ok": True,
        "mode": "preview",
        "group_id": group_id,
        "recipe": _record_detail(record, recipe_edit_service.get_editable_restaurant(restaurant_id).get("restaurant", {}).get("restaurant_name")),
        "impacts": impacts,
    }


def _unique_list(values, normalizer=None):
    result, seen = [], set()
    for value in values:
        key = normalizer(value) if callable(normalizer) else _display_value(value).casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(deepcopy(value))
    return result


def _merge_recipe_payload(primary, secondaries, field_choices):
    merged = deepcopy(primary["data"])
    primary_url = _record_url(primary)
    preserved_identity = {field: deepcopy(merged.get(field)) for field in ("id", "recipe_id", "source_url") if field in merged}
    by_key = {_record_key(record): record for record in [primary, *secondaries]}
    for field in MERGE_SCALAR_FIELDS:
        choice_key = _clean((field_choices or {}).get(field))
        choice = by_key.get(choice_key) if choice_key else None
        if choice and _nonempty(choice["data"].get(field)):
            merged[field] = deepcopy(choice["data"][field])
        elif not _nonempty(merged.get(field)):
            for record in secondaries:
                if _nonempty(record["data"].get(field)):
                    merged[field] = deepcopy(record["data"][field])
                    break
    normalizers = {
        "ingredients": lambda value: normalize_duplicate_recipe_name(_ingredient_name(value)),
        "instructions": lambda value: normalize_duplicate_recipe_name(_instruction_text(value)),
        "equipment": lambda value: normalize_duplicate_recipe_name(value.get("equipment") or value.get("name") if isinstance(value, dict) else value),
    }
    for field in MERGE_LIST_FIELDS:
        combined = []
        for record in [primary, *secondaries]:
            values = record["data"].get(field)
            if isinstance(values, list):
                combined.extend(values)
        if combined:
            merged[field] = _unique_list(combined, normalizer=normalizers.get(field))
    merged["merged_source_urls"] = _unique_list([
        *(merged.get("merged_source_urls") if isinstance(merged.get("merged_source_urls"), list) else []),
        *[_record_url(record) for record in secondaries],
    ])
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    merged.update(preserved_identity)
    merged["source_url"] = preserved_identity.get("source_url") or primary_url
    return merged


def _transaction_paths(records):
    paths = {Path(record["path"]) for record in records if record.get("path")}
    paths.update({
        Path(cookbook_service.COOKBOOKS_FILE),
        Path(recipe_url_service.URLS_FILE),
        Path(recipe_ingredient_service.RECIPE_INGREDIENTS_FILE),
        Path(menu_store_service.MENU_STORE_FILE),
        Path(DUPLICATE_STATE_FILE),
        Path(shopping_list_service.SHOPPING_LIST_FILE),
    })
    db_path = recipe_master_data_service.recipe_master_db_path()
    paths.update({db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")})
    return paths


def _snapshot_paths(paths):
    return {path: (path.exists(), path.read_bytes() if path.exists() else b"") for path in paths}


def _restore_paths(snapshot):
    for path, (existed, data) in snapshot.items():
        if existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        elif path.exists():
            path.unlink()


def _reassign_cookbooks(primary_url, secondary_urls, primary_title):
    primary_key = recipe_url_service.normalize_recipe_url_key(primary_url)
    secondary_keys = {
        recipe_url_service.normalize_recipe_url_key(url) for url in secondary_urls
        if recipe_url_service.normalize_recipe_url_key(url) != primary_key
    }
    payload = cookbook_service.load_cookbooks()
    for cookbook in payload.get("cookbooks", []):
        next_recipes, primary_record = [], None
        for recipe in cookbook.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            key = recipe_url_service.normalize_recipe_url_key(raw_url)
            if key == primary_key:
                if primary_record is None:
                    primary_record = deepcopy(recipe) if isinstance(recipe, dict) else {"url": primary_url}
                continue
            if key in secondary_keys:
                if primary_record is None:
                    primary_record = deepcopy(recipe) if isinstance(recipe, dict) else {"url": primary_url}
                continue
            next_recipes.append(recipe)
        if primary_record is not None:
            primary_record["url"] = primary_url
            if isinstance(primary_record, dict) and primary_title:
                primary_record["name"] = primary_title
            next_recipes.append(primary_record)
        cookbook["recipes"] = next_recipes
    cookbook_service.save_cookbooks(payload)


def _reassign_recipe_urls_and_meta(primary_url, secondary_urls, merged):
    primary_key = recipe_url_service.normalize_recipe_url_key(primary_url)
    secondary_keys = {
        recipe_url_service.normalize_recipe_url_key(url) for url in secondary_urls
        if recipe_url_service.normalize_recipe_url_key(url) != primary_key
    }
    urls = [url for url in recipe_url_service.load_recipe_urls() if recipe_url_service.normalize_recipe_url_key(url) not in secondary_keys]
    if not any(recipe_url_service.normalize_recipe_url_key(url) == recipe_url_service.normalize_recipe_url_key(primary_url) for url in urls):
        urls.append(primary_url)
    recipe_url_service.save_recipe_urls(urls)
    data = recipe_ingredient_service.load_recipe_ingredients()
    primary_meta = deepcopy(data.get(primary_key, {}))
    secondary_meta = [data.get(key, {}) for key in secondary_keys]
    for meta in secondary_meta:
        for key, value in meta.items():
            if key not in {"url", "ingredients", "ingredient_details"} and not _nonempty(primary_meta.get(key)) and _nonempty(value):
                primary_meta[key] = deepcopy(value)
    primary_meta["url"] = primary_url
    primary_meta["name"] = merged.get("recipe_title") or merged.get("display_name") or primary_meta.get("name")
    primary_meta["ingredients"] = deepcopy(merged.get("ingredients") or primary_meta.get("ingredients") or [])
    data[primary_key] = primary_meta
    for key in secondary_keys:
        data.pop(key, None)
    recipe_ingredient_service.save_recipe_ingredients(data)


def _reassign_menu_items(primary_url, secondary_urls):
    primary_key = recipe_url_service.normalize_recipe_url_key(primary_url)
    secondary_keys = {
        recipe_url_service.normalize_recipe_url_key(url) for url in secondary_urls
        if recipe_url_service.normalize_recipe_url_key(url) != primary_key
    }
    store = menu_store_service.load_menu_store()
    for item in store.get("items", []):
        if recipe_url_service.normalize_recipe_url_key(item.get("recipe_url")) in secondary_keys:
            item["recipe_url"] = primary_url
    menu_store_service.save_menu_store(store)


def _append_audit(action, restaurant_id, primary_recipe_id="", removed_recipe_ids=None, detail=None):
    state = load_duplicate_state()
    state["audit"].append({
        "action": action,
        "restaurant_id": _clean(restaurant_id),
        "primary_recipe_id": _clean(primary_recipe_id),
        "removed_recipe_ids": [_clean(recipe_id) for recipe_id in removed_recipe_ids or []],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": _clean(active_user_id()),
        "detail": detail or {},
    })
    save_duplicate_state(state)


def commit_restaurant_recipe_merge(restaurant_id, group_id, primary_record_key, secondary_record_keys, field_choices=None):
    preview = restaurant_recipe_merge_preview(
        restaurant_id, group_id, primary_record_key, secondary_record_keys
    )
    if not preview.get("ok"):
        return preview
    group, records = _group_records(restaurant_id, group_id)
    primary = _record_for_key(records, preview["primary_record_key"])
    secondaries = [_record_for_key(records, key) for key in preview["secondary_record_keys"]]
    secondaries = [record for record in secondaries if record]
    selected = [primary, *secondaries]
    with workspace_write_lock("restaurant-recipe-duplicates"), DUPLICATE_LOCK:
        snapshot = _snapshot_paths(_transaction_paths(selected))
        try:
            merged = _merge_recipe_payload(primary, secondaries, field_choices or {})
            primary["path"].write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
            secondary_urls = [_record_url(record) for record in secondaries]
            _reassign_cookbooks(_record_url(primary), secondary_urls, merged.get("recipe_title"))
            _reassign_recipe_urls_and_meta(_record_url(primary), secondary_urls, merged)
            _reassign_menu_items(_record_url(primary), secondary_urls)
            for record in secondaries:
                if recipe_url_service.normalize_recipe_url_key(_record_url(record)) != recipe_url_service.normalize_recipe_url_key(_record_url(primary)):
                    recipe_master_data_service.remove_recipe_master_records_for_recipe(_record_url(record))
                record["path"].unlink(missing_ok=True)
            recipe_master_data_service.sync_recipe_master_records(
                _record_url(primary), ingredients=merged.get("ingredients", []), recipe_data=merged
            )
            _append_audit(
                "merge",
                restaurant_id,
                _record_recipe_id(primary),
                [_record_recipe_id(record) for record in secondaries],
                {
                    "field_choices": field_choices or {},
                    "primary_recipe_url": _record_url(primary),
                    "removed_recipe_urls": secondary_urls,
                },
            )
        except Exception as exc:
            _restore_paths(snapshot)
            return {"ok": False, "error": f"Merge failed and was rolled back: {exc}"}
    if has_request_context():
        g.pop("_recipe_edit_output_index", None)
        g.pop("_cookbook_recipe_index", None)
        g.pop("_editable_restaurant_usage_inventories", None)
    return {
        "ok": True,
        "merged": True,
        "primary_url": _record_url(primary),
        "removed_urls": [_record_url(record) for record in secondaries],
    }


def commit_restaurant_recipe_delete(restaurant_id, group_id, recipe_record_key):
    preview = restaurant_recipe_delete_preview(restaurant_id, group_id, recipe_record_key)
    if not preview.get("ok"):
        return preview
    group, records = _group_records(restaurant_id, group_id)
    record = _record_for_key(records, recipe_record_key)
    recipe_url = _record_url(record)
    target = recipe_url_service.normalize_recipe_url_key(recipe_url)
    shared_source_record_count = sum(
        1 for item in records
        if item is not record and recipe_url_service.normalize_recipe_url_key(_record_url(item)) == target
    )
    with workspace_write_lock("restaurant-recipe-duplicates"), DUPLICATE_LOCK:
        snapshot = _snapshot_paths(_transaction_paths([record]))
        try:
            removed_ingredients = []
            if not shared_source_record_count:
                cookbook_service.purge_recipe_from_all_cookbooks(recipe_url)
                meta_before = recipe_ingredient_service.load_recipe_ingredients()
                removed_ingredients = recipe_ingredient_service.recipe_ingredients_for_key(target, meta_before)
                recipe_ingredient_service.remove_recipe_and_unused_ingredients(recipe_url)
                recipe_url_service.remove_recipe_url(recipe_url)
                store = menu_store_service.load_menu_store()
                for item in store.get("items", []):
                    if recipe_url_service.normalize_recipe_url_key(item.get("recipe_url")) == target:
                        item["recipe_url"] = None
                menu_store_service.save_menu_store(store)
                recipe_master_data_service.remove_recipe_master_records_for_recipe(recipe_url)
            record["path"].unlink(missing_ok=True)
            _append_audit(
                "delete_duplicate",
                restaurant_id,
                "",
                [_record_recipe_id(record)],
                {
                    "removed_recipe_urls": [recipe_url],
                    "affected_ingredients": len(removed_ingredients),
                    "shared_source_record_count": shared_source_record_count,
                },
            )
        except Exception as exc:
            _restore_paths(snapshot)
            return {"ok": False, "error": f"Delete failed and was rolled back: {exc}"}
    if has_request_context():
        g.pop("_recipe_edit_output_index", None)
        g.pop("_cookbook_recipe_index", None)
        g.pop("_editable_restaurant_usage_inventories", None)
    return {"ok": True, "deleted": True, "deleted_url": _clean(recipe_url)}
