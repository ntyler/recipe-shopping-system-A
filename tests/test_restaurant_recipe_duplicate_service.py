import json
from contextlib import nullcontext
from pathlib import Path

from PushShoppingList.services import restaurant_recipe_duplicate_service as duplicates


def recipe_record(path, title, url, **values):
    data = {
        "recipe_id": values.pop("recipe_id", f"recipe-{path.stem}"),
        "recipe_title": title,
        "source_url": url,
        "restaurant_id": "restaurant-1",
        **values,
    }
    return {
        "identity": f"file:{path.name}",
        "path": path,
        "url": url,
        "data": data,
        "match_kind": "normalized",
    }


def test_duplicate_name_normalization_and_exact_source_detection(monkeypatch, tmp_path):
    records = [
        recipe_record(tmp_path / "a.json", "  Alfajores!!! ", "https://example.test/menu?item=alfajores", recipe_id="a", menu_item_id="item-a"),
        recipe_record(tmp_path / "b.json", "alfajores", "https://example.test/menu?item=alfajores", recipe_id="b", menu_item_id="item-b"),
    ]
    monkeypatch.setattr(duplicates, "_usage_records", lambda _restaurant_id: ({"ok": True}, records))
    monkeypatch.setattr(duplicates, "load_duplicate_state", lambda: {"ignored_groups": {}, "audit": []})

    result = duplicates.restaurant_recipe_duplicate_groups("restaurant-1")

    assert duplicates.normalize_duplicate_recipe_name("  ALFAJORES...  ") == "alfajores"
    assert result["ok"] is True
    assert len(result["groups"]) == 1
    assert result["groups"][0]["match_type"] == "exact"
    assert result["groups"][0]["badge_label"] == "Exact duplicate"
    assert duplicates._record_key(records[0]) != duplicates._record_key(records[1])


def test_usage_rows_show_one_group_badge_and_keep_group_id_on_every_match(monkeypatch, tmp_path):
    records = [
        recipe_record(tmp_path / "a.json", "Alfajores", "https://example.test/a"),
        recipe_record(tmp_path / "b.json", "Alfajores", "https://example.test/b"),
        recipe_record(tmp_path / "c.json", "Alfajores", "https://example.test/c"),
    ]
    monkeypatch.setattr(duplicates, "_usage_records", lambda _restaurant_id: ({"ok": True}, records))
    monkeypatch.setattr(duplicates, "load_duplicate_state", lambda: {"ignored_groups": {}, "audit": []})
    usage = {"ok": True, "recipes": [{"url": record["url"]} for record in records]}

    result = duplicates.decorate_restaurant_usage_with_duplicates(usage, "restaurant-1")

    assert {row["duplicate_group_id"] for row in result["recipes"]} == {result["recipes"][0]["duplicate_group_id"]}
    assert [row.get("duplicate_badge") for row in result["recipes"]] == ["3 similar", None, None]


def test_keep_both_and_ignore_are_persistent_and_user_scoped(monkeypatch, tmp_path):
    state_path = tmp_path / "duplicates.json"
    monkeypatch.setattr(duplicates, "DUPLICATE_STATE_FILE", state_path)
    monkeypatch.setattr(duplicates, "active_user_id", lambda: "user-42")
    monkeypatch.setattr(duplicates, "restaurant_recipe_duplicate_group_detail", lambda *_args: {
        "ok": True,
        "signature": "signature-1",
        "records": [{"source_url": "https://example.test/a"}, {"source_url": "https://example.test/b"}],
    })

    result = duplicates.set_restaurant_recipe_duplicate_disposition("restaurant-1", "group-1", "keep_both")
    saved = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert saved["ignored_groups"]["signature-1"]["disposition"] == "keep_both"
    assert saved["ignored_groups"]["signature-1"]["user_id"] == "user-42"


def test_merge_preview_requires_canonical_selection_and_exposes_conflicts(monkeypatch, tmp_path):
    primary = recipe_record(tmp_path / "a.json", "Alfajores", "https://example.test/a", description="Primary")
    secondary = recipe_record(tmp_path / "b.json", "Alfajores", "https://example.test/b", description="Secondary")
    group = {"ok": True, "group_id": "group-1"}
    monkeypatch.setattr(duplicates, "_group_records", lambda *_args: (group, [primary, secondary]))
    monkeypatch.setattr(duplicates, "_relationship_impacts", lambda _url: {"cookbook_count": 0})

    primary_key = duplicates._record_key(primary)
    secondary_key = duplicates._record_key(secondary)
    missing = duplicates.restaurant_recipe_merge_preview("restaurant-1", "group-1", "", [secondary_key])
    preview = duplicates.restaurant_recipe_merge_preview(
        "restaurant-1", "group-1", primary_key, [secondary_key]
    )

    assert missing == {"ok": False, "error": "Choose a canonical recipe."}
    assert preview["ok"] is True
    assert preview["primary_url"] == primary["url"]
    assert [item["field"] for item in preview["conflicts"]] == ["description"]


def configure_merge_transaction(monkeypatch, tmp_path, primary, secondary):
    state_path = tmp_path / "duplicate-state.json"
    monkeypatch.setattr(duplicates, "DUPLICATE_STATE_FILE", state_path)
    monkeypatch.setattr(duplicates, "active_user_id", lambda: "user-42")
    monkeypatch.setattr(duplicates, "workspace_write_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(duplicates, "_group_records", lambda *_args: ({"ok": True}, [primary, secondary]))
    monkeypatch.setattr(duplicates, "restaurant_recipe_merge_preview", lambda *_args, **_kwargs: {
        "ok": True,
        "primary_record_key": duplicates._record_key(primary),
        "secondary_record_keys": [duplicates._record_key(secondary)],
        "primary_url": primary["url"],
        "secondary_urls": [secondary["url"]],
    })
    monkeypatch.setattr(duplicates, "_transaction_paths", lambda _records: {primary["path"], secondary["path"], state_path})
    monkeypatch.setattr(duplicates, "_reassign_recipe_urls_and_meta", lambda *_args: None)
    monkeypatch.setattr(duplicates, "_reassign_menu_items", lambda *_args: None)
    monkeypatch.setattr(duplicates.recipe_master_data_service, "remove_recipe_master_records_for_recipe", lambda *_args: None)
    monkeypatch.setattr(duplicates.recipe_master_data_service, "sync_recipe_master_records", lambda *_args, **_kwargs: None)
    return state_path


def test_merge_rolls_back_recipe_files_when_any_relationship_step_fails(monkeypatch, tmp_path):
    primary = recipe_record(tmp_path / "a.json", "Alfajores", "https://example.test/a", description="Primary")
    secondary = recipe_record(tmp_path / "b.json", "Alfajores", "https://example.test/b", ingredients=["flour"])
    primary["path"].write_text(json.dumps(primary["data"]), encoding="utf-8")
    secondary["path"].write_text(json.dumps(secondary["data"]), encoding="utf-8")
    original_primary = primary["path"].read_bytes()
    original_secondary = secondary["path"].read_bytes()
    configure_merge_transaction(monkeypatch, tmp_path, primary, secondary)
    monkeypatch.setattr(duplicates, "_reassign_cookbooks", lambda *_args: (_ for _ in ()).throw(RuntimeError("relationship failure")))

    result = duplicates.commit_restaurant_recipe_merge(
        "restaurant-1", "group-1", duplicates._record_key(primary), [duplicates._record_key(secondary)]
    )

    assert result["ok"] is False
    assert "rolled back" in result["error"]
    assert primary["path"].read_bytes() == original_primary
    assert secondary["path"].read_bytes() == original_secondary


def test_successful_merge_preserves_primary_id_removes_secondary_and_audits(monkeypatch, tmp_path):
    primary = recipe_record(tmp_path / "a.json", "Alfajores", "https://example.test/a", recipe_id="canonical", description="Primary")
    secondary = recipe_record(tmp_path / "b.json", "Alfajores", "https://example.test/b", recipe_id="duplicate", ingredients=["flour"])
    primary["path"].write_text(json.dumps(primary["data"]), encoding="utf-8")
    secondary["path"].write_text(json.dumps(secondary["data"]), encoding="utf-8")
    state_path = configure_merge_transaction(monkeypatch, tmp_path, primary, secondary)
    monkeypatch.setattr(duplicates, "_reassign_cookbooks", lambda *_args: None)

    result = duplicates.commit_restaurant_recipe_merge(
        "restaurant-1", "group-1", duplicates._record_key(primary), [duplicates._record_key(secondary)]
    )
    merged = json.loads(primary["path"].read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert merged["recipe_id"] == "canonical"
    assert merged["source_url"] == primary["url"]
    assert merged["ingredients"] == ["flour"]
    assert not secondary["path"].exists()
    assert state["audit"][0]["action"] == "merge"
    assert state["audit"][0]["primary_recipe_id"] == "canonical"
    assert state["audit"][0]["removed_recipe_ids"] == ["duplicate"]
    assert state["audit"][0]["detail"]["removed_recipe_urls"] == [secondary["url"]]
    assert state["audit"][0]["user_id"] == "user-42"


def test_delete_removes_only_selected_recipe_relationships_and_records_audit(monkeypatch, tmp_path):
    selected = recipe_record(tmp_path / "selected.json", "Alfajores", "https://example.test/selected", recipe_id="delete-me")
    untouched = recipe_record(tmp_path / "untouched.json", "Alfajores", "https://example.test/untouched", recipe_id="keep-me")
    selected["path"].write_text(json.dumps(selected["data"]), encoding="utf-8")
    untouched["path"].write_text(json.dumps(untouched["data"]), encoding="utf-8")
    state_path = tmp_path / "duplicate-state.json"
    menu_store = {"items": [{"recipe_url": selected["url"]}, {"recipe_url": untouched["url"]}]}
    calls = {"cookbook": [], "url": [], "master": []}
    monkeypatch.setattr(duplicates, "DUPLICATE_STATE_FILE", state_path)
    monkeypatch.setattr(duplicates, "active_user_id", lambda: "user-42")
    monkeypatch.setattr(duplicates, "workspace_write_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(duplicates, "restaurant_recipe_delete_preview", lambda *_args: {"ok": True})
    monkeypatch.setattr(duplicates, "_group_records", lambda *_args: ({"ok": True}, [selected, untouched]))
    monkeypatch.setattr(duplicates, "_transaction_paths", lambda _records: {selected["path"], untouched["path"], state_path})
    monkeypatch.setattr(duplicates.cookbook_service, "purge_recipe_from_all_cookbooks", lambda url: calls["cookbook"].append(url))
    monkeypatch.setattr(duplicates.recipe_ingredient_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(duplicates.recipe_ingredient_service, "recipe_ingredients_for_key", lambda *_args: [])
    monkeypatch.setattr(duplicates.recipe_ingredient_service, "remove_recipe_and_unused_ingredients", lambda *_args: None)
    monkeypatch.setattr(duplicates.recipe_url_service, "remove_recipe_url", lambda url: calls["url"].append(url))
    monkeypatch.setattr(duplicates.menu_store_service, "load_menu_store", lambda: menu_store)
    monkeypatch.setattr(duplicates.menu_store_service, "save_menu_store", lambda store: store)
    monkeypatch.setattr(duplicates.recipe_master_data_service, "remove_recipe_master_records_for_recipe", lambda url: calls["master"].append(url))

    result = duplicates.commit_restaurant_recipe_delete(
        "restaurant-1", "group-1", duplicates._record_key(selected)
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result == {"ok": True, "deleted": True, "deleted_url": selected["url"]}
    assert not selected["path"].exists()
    assert untouched["path"].exists()
    assert calls == {"cookbook": [selected["url"]], "url": [selected["url"]], "master": [selected["url"]]}
    assert menu_store["items"] == [{"recipe_url": None}, {"recipe_url": untouched["url"]}]
    assert state["audit"][0]["removed_recipe_ids"] == ["delete-me"]
    assert state["audit"][0]["detail"]["removed_recipe_urls"] == [selected["url"]]


def test_delete_of_shared_url_record_keeps_relationships_for_remaining_record(monkeypatch, tmp_path):
    shared_url = "https://example.test/shared"
    selected = recipe_record(tmp_path / "selected.json", "Alfajores", shared_url, recipe_id="delete-me")
    remaining = recipe_record(tmp_path / "remaining.json", "Alfajores", shared_url, recipe_id="keep-me")
    selected["path"].write_text(json.dumps(selected["data"]), encoding="utf-8")
    remaining["path"].write_text(json.dumps(remaining["data"]), encoding="utf-8")
    state_path = tmp_path / "duplicate-state.json"
    calls = []
    monkeypatch.setattr(duplicates, "DUPLICATE_STATE_FILE", state_path)
    monkeypatch.setattr(duplicates, "active_user_id", lambda: "user-42")
    monkeypatch.setattr(duplicates, "workspace_write_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(duplicates, "restaurant_recipe_delete_preview", lambda *_args: {"ok": True})
    monkeypatch.setattr(duplicates, "_group_records", lambda *_args: ({"ok": True}, [selected, remaining]))
    monkeypatch.setattr(duplicates, "_transaction_paths", lambda _records: {selected["path"], remaining["path"], state_path})
    monkeypatch.setattr(duplicates.cookbook_service, "purge_recipe_from_all_cookbooks", lambda *_args: calls.append("cookbook"))
    monkeypatch.setattr(duplicates.recipe_ingredient_service, "remove_recipe_and_unused_ingredients", lambda *_args: calls.append("ingredients"))
    monkeypatch.setattr(duplicates.recipe_url_service, "remove_recipe_url", lambda *_args: calls.append("url"))
    monkeypatch.setattr(duplicates.recipe_master_data_service, "remove_recipe_master_records_for_recipe", lambda *_args: calls.append("master"))

    result = duplicates.commit_restaurant_recipe_delete(
        "restaurant-1", "group-1", duplicates._record_key(selected)
    )

    assert result["ok"] is True
    assert not selected["path"].exists()
    assert remaining["path"].exists()
    assert calls == []


def test_same_url_merge_keeps_primary_recipe_metadata(monkeypatch):
    shared_url = "https://example.test/shared"
    key = duplicates.recipe_url_service.normalize_recipe_url_key(shared_url)
    stored = {key: {"url": shared_url, "ingredients": ["flour"]}}
    saved = {}
    monkeypatch.setattr(duplicates.recipe_url_service, "load_recipe_urls", lambda: [shared_url])
    monkeypatch.setattr(duplicates.recipe_url_service, "save_recipe_urls", lambda urls: saved.update(urls=urls))
    monkeypatch.setattr(duplicates.recipe_ingredient_service, "load_recipe_ingredients", lambda: stored)
    monkeypatch.setattr(duplicates.recipe_ingredient_service, "save_recipe_ingredients", lambda data: saved.update(meta=data))

    duplicates._reassign_recipe_urls_and_meta(
        shared_url, [shared_url], {"recipe_title": "Alfajores", "ingredients": ["flour"]}
    )

    assert saved["urls"] == [shared_url]
    assert saved["meta"][key]["url"] == shared_url
    assert saved["meta"][key]["ingredients"] == ["flour"]
