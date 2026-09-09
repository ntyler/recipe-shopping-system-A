"""Equipment service boundaries use validated identity even for forged callers."""

from contextlib import contextmanager
import sqlite3

from flask import Flask, g, session
import pytest
from werkzeug.exceptions import Forbidden, NotFound

from PushShoppingList.services import recipe_master_data_service as md
from PushShoppingList.services import recipe_master_image_service as images


@pytest.fixture
def equipment_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(md, "RECIPE_MASTER_DB_PATH", tmp_path / "master.sqlite3")
    monkeypatch.setattr(images, "MASTER_IMAGE_PROGRESS_RUNS", {})
    app = Flask(__name__)
    app.secret_key = "equipment-scope-test"
    rows = {}
    for owner, name, section in (
        ("user-a", "Alpha stockpot", "COOKWARE"),
        ("user-b", "Beta whisk", "UTENSILS"),
        ("admin-user", "Admin pan", "COOKWARE"),
    ):
        md.sync_recipe_master_records(
            f"https://example.com/{owner}-private-recipe",
            recipe_data={"equipment": [{"equipment": name, "equipment_section": section}]},
            user_id=owner,
        )
        rows[owner] = md.master_record_for_name("equipment", owner, name)
    with md.recipe_master_connection() as connection:
        connection.execute("""CREATE TABLE equipment_aliases (
            user_id TEXT, equipment_id INTEGER, alias_name TEXT, alias_key TEXT, status TEXT
        )""")
        connection.executemany("INSERT INTO equipment_aliases VALUES (?, ?, ?, ?, 'active')", [
            ("user-a", rows["user-a"]["id"], "Own alias", "own alias"),
            ("user-b", rows["user-a"]["id"], "Foreign alias", "foreign alias"),
            ("user-a", rows["user-b"]["id"], "Forged foreign alias", "forged foreign alias"),
        ])
        # Historical malformed links must not import another owner's references.
        connection.executemany("""INSERT INTO recipe_equipment
            (user_id, recipe_id, equipment_id, original_recipe_text, optional, sort_order)
            VALUES (?, ?, ?, ?, 0, 0)""", [
                ("user-b", "https://example.com/beta-secret", rows["user-a"]["id"], "Beta secret"),
                ("user-a", "https://example.com/forged-reference", rows["user-b"]["id"], "Forged reference"),
                ("user-a", "https://example.com/user-a-private-recipe", rows["user-a"]["id"], "Duplicate line"),
            ])
    return app, rows


@contextmanager
def identity(app, owner):
    with app.test_request_context("/admin/master-data/equipment?scope=all&user_id=user-b"):
        g.session_identity_validated = True
        g.authenticated_user_id = owner
        g.authenticated_guest_session_id = ""
        # Validated identity must win even over stale/forged session data.
        session["user_id"] = "user-b"
        yield


@pytest.mark.parametrize("owner", ["user-a", "user-b", "admin-user"])
def test_equipment_reads_ignore_forged_owner_and_all_users(equipment_scope, owner):
    app, rows = equipment_scope
    foreign_owner = "user-b" if owner != "user-b" else "user-a"
    foreign = rows[foreign_owner]
    with identity(app, owner):
        for sort in ("name_asc", "usage_desc", "updated_at_desc"):
            found = md.list_equipment(user_id=foreign_owner, include_all_users=True, sort=sort)
            assert [row["id"] for row in found] == [rows[owner]["id"]]
            assert all(row["user_id"] == owner for row in found)
        assert md.count_equipment(user_id=foreign_owner, include_all_users=True) == 1
        assert md.equipment_summary_counts(user_id=foreign_owner, include_all_users=True) == {
            "total_count": 1, "type_count": 1, "in_use_count": 1, "unused_count": 0,
        }
        assert md.list_equipment(search=foreign["name"], include_all_users=True) == []
        assert md.count_equipment(search=foreign["name"], include_all_users=True) == 0
        assert md.list_equipment(offset=1, limit=1, include_all_users=True) == []
        assert md.master_record_for_id("equipment", foreign["id"], user_id=foreign_owner, include_all_users=True) is None
        assert md.master_record_for_name("equipment", foreign_owner, foreign["name"]) is None
        assert md.recipe_master_rows("recipe_equipment", f"https://example.com/{foreign_owner}-private-recipe", user_id=foreign_owner) == []
        assert md.count_equipment_usage(foreign["id"], user_id=foreign_owner) == 0
        references = md.list_master_record_recipe_references(
            "equipment", foreign["id"], user_id=foreign_owner, include_all_users=True,
        )
        assert references["record"] is None and references["references"] == []
        missing_images = images.missing_master_image_rows("equipment", user_id=foreign_owner, include_all_users=True)
        assert [row["id"] for row in missing_images] == [rows[owner]["id"]]


def test_equipment_aliases_usage_metadata_and_filters_are_owner_scoped(equipment_scope, monkeypatch):
    app, rows = equipment_scope
    metadata_owners = []

    def metadata(owner):
        metadata_owners.append(owner)
        return {f"https://example.com/{owner}-private-recipe": {"name": f"{owner} title"}}

    monkeypatch.setattr(md, "recipe_reference_metadata", metadata)
    with identity(app, "user-a"):
        found = md.list_equipment(user_id="user-b", include_all_users=True)
        assert found[0]["aliases"] == ["Own alias"]
        assert found[0]["usage_count"] == 1
        assert md.count_equipment_usage(rows["user-a"]["id"], user_id="user-b") == 1
        assert md.list_equipment(equipment_section=rows["user-b"]["equipment_section"], include_all_users=True) == []
        assert md.count_equipment(equipment_section=rows["user-b"]["equipment_section"], include_all_users=True) == 0
        result = md.list_master_record_recipe_references("equipment", rows["user-a"]["id"], user_id="user-b", include_all_users=True)
        assert result["total"] == 1
        assert result["total_reference_count"] == 2
        assert {row["recipe_title"] for row in result["references"]} == {"user-a title"}
        assert {row["user_id"] for row in result["references"]} == {"user-a"}
        assert metadata_owners == ["user-a"]


def test_equipment_writes_reject_foreign_ids_and_owner_values(equipment_scope):
    app, rows = equipment_scope
    # A normal edit must not incidentally normalize another account's legacy row.
    with sqlite3.connect(md.recipe_master_db_path()) as connection:
        connection.execute("UPDATE equipment SET equipment_section = 'Legacy private type' WHERE id = ?", (rows["user-b"]["id"],))
    rows["user-b"] = md.master_record_for_name("equipment", "user-b", "Beta whisk")
    with identity(app, "user-a"):
        before = md.recipe_master_db_path().read_bytes()
        for name in ("Stolen", "", "x" * 161):
            denied = md.update_equipment_display_name(rows["user-b"]["id"], name, user_id="user-b")
            assert denied["status"] == 404
        assert md.recipe_master_db_path().read_bytes() == before
        saved = md.update_equipment_display_name(rows["user-a"]["id"], "My pot", user_id="user-b")
        assert saved["ok"] and saved["record"]["name"] == "My pot"
        with pytest.raises(Forbidden), md.recipe_master_connection() as connection:
            md.upsert_master_record(connection, "equipment", "user-b", "Injected equipment")
        assert not images.attach_master_record_image(rows["user-b"], "/stolen.png", "/stolen.png", "equipment")
        with pytest.raises(NotFound):
            images.save_master_record_image(rows["user-b"], b"not an image", "equipment")
        with pytest.raises(NotFound):
            images.request_master_image_bytes("Do not generate", rows["user-b"], "equipment")
    assert md.master_record_for_name("equipment", "user-b", "Beta whisk") == rows["user-b"]
    assert md.master_record_for_name("equipment", "user-b", "Injected equipment") is None


def test_equipment_image_jobs_capture_owner_and_protect_foreign_progress(equipment_scope, monkeypatch):
    app, _rows = equipment_scope
    images.start_master_image_progress("foreign", record_type="equipment", user_id="user-b")
    images.start_master_image_progress("global", record_type="equipment", include_all_users=True)
    captured = []

    class Worker:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def start(self):
            pass

    monkeypatch.setattr(images.threading, "Thread", Worker)
    with identity(app, "user-a"):
        assert images.master_image_progress("foreign") is None
        assert images.master_image_progress("global") is None
        assert images.master_image_progress() is None
        for record_type in ("equipment", "ingredients"):
            with pytest.raises(Forbidden):
                images.start_master_image_progress("foreign", record_type=record_type, user_id="user-b")
        with pytest.raises(Forbidden):
            images.update_master_image_progress("foreign", "complete")
        result = images.start_master_image_generation_job("own", record_type="equipment", user_id="user-b", include_all_users=True)
        assert result["user_id"] == "user-a" and result["include_all_users"] is False
        assert captured[0]["kwargs"]["user_id"] == "user-a"
        assert captured[0]["kwargs"]["include_all_users"] is False


def test_equipment_request_without_identity_never_falls_back_to_local(equipment_scope):
    app, _rows = equipment_scope
    with identity(app, ""):
        with pytest.raises(Forbidden):
            md.list_equipment(user_id="user-b", include_all_users=True)
    # Administrative offline tooling retains its explicit all-owner capability.
    assert len(md.list_equipment(include_all_users=True)) == 3
