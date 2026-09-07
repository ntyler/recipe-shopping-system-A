import json
import os
import sqlite3
import subprocess
import sys

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.services import recipe_master_data_service as md
from test_unit_registry_management import unit_registry_app, sign_in, registry_for


def group(registry, category="volume"):
    return [unit for unit in registry["units"] if unit["category"] == category]


def snapshot(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT * FROM workspace_units ORDER BY user_id, id").fetchall()


def test_category_order_persists_and_preserves_fields_and_other_groups(unit_registry_app):
    before = md.ensure_workspace_unit_registry("user-a")
    other = md.ensure_workspace_unit_registry("user-b")
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        result = client.patch('/api/master-data/units/volume_cup', json={"action": "move_to", "position": 1})
        assert result.status_code == 200
        changed = result.get_json()["registry"]
        assert [u["id"] for u in group(changed)][:4] == ["volume_cup", "volume_teaspoon", "volume_tablespoon", "volume_fluid_ounce"]
        assert [u["sort_order"] for u in group(changed)] == list(range(9))
        for old in before["units"]:
            new = next(u for u in changed["units"] if u["id"] == old["id"])
            for key in ("id", "name", "aliases", "category", "seeded"):
                assert new[key] == old[key]
            if old["category"] != "volume":
                assert new["sort_order"] == old["sort_order"]
        assert md.read_workspace_unit_registry("user-b") == other
        html = BeautifulSoup(client.get('/admin/master-data/units').data, 'html.parser')
        for category in html.select('[data-unit-master-category]'):
            rows = category.select('[data-unit-master-row]')
            assert [int(r.select_one('[data-unit-master-order-number]').text) for r in rows] == list(range(1, len(rows)+1))
            assert category.select_one('[role="table"]')['aria-colcount'] == '7'
            assert rows[0].select_one('[data-unit-master-order-action="up"]').has_attr('disabled')
            assert rows[-1].select_one('[data-unit-master-order-action="down"]').has_attr('disabled')
            assert rows[0].select_one('[data-unit-master-drag-handle]')['aria-keyshortcuts'] == 'ArrowUp ArrowDown Home End'
        client.get('/admin/master-data/types')
        assert group(registry_for(client))[0]['id'] == 'volume_cup'
    # A fresh process opens the same database, without request caches.
    env = {**os.environ, 'SHOPPING_APP_RECIPE_MASTER_DB': str(md.recipe_master_db_path())}
    result = subprocess.run([sys.executable, '-c', 'import json; from PushShoppingList.services import recipe_master_data_service as m; print(json.dumps(m.read_workspace_unit_registry("user-a")))'], env=env, capture_output=True, text=True, check=True)
    assert group(json.loads(result.stdout))[0]['id'] == 'volume_cup'


def test_append_and_rename_keep_positions_and_category_is_locked(unit_registry_app):
    md.ensure_workspace_unit_registry('user-a')
    md.move_workspace_unit('weight_gram', 1, 'user-a')
    result = md.save_workspace_unit({'canonical_name':'scoop', 'category':'volume', 'aliases':['scoops']}, user_id='user-a')
    unit_id = result['unit_id']
    assert group(result['registry'])[-1]['sort_order'] == 9
    md.move_workspace_unit(unit_id, 1, 'user-a')
    result = md.save_workspace_unit({'canonical_name':'measure', 'category':'volume', 'aliases':['measures']}, unit_id, 'user-a')
    assert group(result['registry'])[0]['id'] == unit_id
    result = md.save_workspace_unit({'canonical_name':'measure', 'category':'weight', 'aliases':['measures']}, unit_id, 'user-a')
    assert result['status'] == 422 and not result['ok']
    registry = md.read_workspace_unit_registry('user-a')
    assert group(registry)[0]['id'] == unit_id
    assert len(group(registry)) == 10
    assert len(group(registry, 'weight')) == 4



@pytest.mark.parametrize('position', [None, True, 1.2, [], {}, '', '1.5', 'bad'])
def test_invalid_position_is_rejected_without_changes(unit_registry_app, position):
    md.ensure_workspace_unit_registry('user-a')
    before = snapshot(md.recipe_master_db_path())
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        assert client.patch('/api/master-data/units/volume_cup', json={'action':'move_to','position':position}).status_code == 400
    assert snapshot(md.recipe_master_db_path()) == before


def test_scoped_noop_clamped_moves_and_atomic_rollback(unit_registry_app):
    md.ensure_workspace_unit_registry('user-a')
    foreign = md.save_workspace_unit({'canonical_name':'scoop','category':'volume'}, user_id='user-b')['unit_id']
    assert md.move_workspace_unit(foreign, 1, 'user-a')['status'] == 404
    md.move_workspace_unit('volume_cup', -10, 'user-a')
    before = snapshot(md.recipe_master_db_path())
    assert not md.move_workspace_unit('volume_cup', 1, 'user-a')['changed']
    assert snapshot(md.recipe_master_db_path()) == before
    md.move_workspace_unit('volume_cup', 999, 'user-a')
    assert group(md.read_workspace_unit_registry('user-a'))[-1]['id'] == 'volume_cup'
    before = snapshot(md.recipe_master_db_path())
    with sqlite3.connect(md.recipe_master_db_path()) as db:
        db.execute("CREATE TRIGGER fail_order BEFORE UPDATE OF sort_order ON workspace_units WHEN NEW.id = 'volume_fluid_ounce' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
        md.move_workspace_unit('volume_cup', 1, 'user-a')
    assert snapshot(md.recipe_master_db_path()) == before


@pytest.mark.parametrize('legacy_order', ['missing', 0, None, -1, 'bad'])
def test_backfill_is_safe_and_idempotent(tmp_path, legacy_order):
    path = tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        order_column = '' if legacy_order == 'missing' else ', sort_order INTEGER'
        db.execute(f'CREATE TABLE workspace_units (user_id TEXT, id TEXT, name TEXT, normalized_name TEXT, category TEXT, created_at TEXT, updated_at TEXT {order_column})')
        seeds = md.canonical_unit_options()
        for unit in reversed(seeds):
            values = ['mine', unit['id'], unit['name'], unit['name'], unit['category'], 'created', 'updated']
            if legacy_order != 'missing': values.append(legacy_order)
            db.execute('INSERT INTO workspace_units VALUES (' + ','.join('?' for _ in values) + ')', values)
        db.commit()
        before = db.execute('SELECT user_id,id,name,normalized_name,category,created_at,updated_at FROM workspace_units ORDER BY id').fetchall()
        assert md.migrate_workspace_unit_order(db) > 0
        assert md.migrate_workspace_unit_order(db) == 0
        assert db.execute('SELECT user_id,id,name,normalized_name,category,created_at,updated_at FROM workspace_units ORDER BY id').fetchall() == before
        for key, _label in md.UNIT_REGISTRY_CATEGORIES:
            rows = db.execute('SELECT id,sort_order FROM workspace_units WHERE category=? ORDER BY sort_order', (key,)).fetchall()
            assert [r['id'] for r in rows] == [u['id'] for u in seeds if u['category'] == key]
            assert [r['sort_order'] for r in rows] == list(range(len(rows)))


def test_valid_order_survives_migration_and_dry_run(unit_registry_app):
    md.ensure_workspace_unit_registry('user-a')
    md.move_workspace_unit('weight_gram', 1, 'user-a')
    path = md.recipe_master_db_path()
    before = snapshot(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert md.migrate_workspace_unit_order(db) == 0
    assert snapshot(path) == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE workspace_units SET sort_order=0 WHERE category='volume'")
    before_bytes = path.read_bytes()
    command = [sys.executable, '-m', 'PushShoppingList.scripts.migrate_workspace_unit_order', '--database', str(path)]
    result = subprocess.run(command + ['--dry-run'], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['changed_rows'] == 8
    assert path.read_bytes() == before_bytes
    subprocess.run(command, check=True, capture_output=True)
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['changed_rows'] == 0


def test_separate_processes_serialize_category_appends_and_moves(unit_registry_app):
    md.ensure_workspace_unit_registry('user-a')
    env = {**os.environ, 'SHOPPING_APP_RECIPE_MASTER_DB': str(md.recipe_master_db_path())}
    script = """
import sys
from PushShoppingList.services import recipe_master_data_service as m
assert m.save_workspace_unit({'canonical_name':sys.argv[1], 'category':'volume'}, user_id='user-a')['ok']
assert m.move_workspace_unit(sys.argv[2], 1, user_id='user-a')['ok']
"""
    processes = [subprocess.Popen(
        [sys.executable, '-c', script, name, unit_id], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for name, unit_id in [('Concurrent A', 'volume_cup'), ('Concurrent B', 'volume_liter')]]
    for process in processes:
        stdout, stderr = process.communicate(timeout=40)
        assert process.returncode == 0, stdout + stderr
    units = group(md.read_workspace_unit_registry('user-a'))
    assert len(units) == 11
    assert len({unit['id'] for unit in units}) == 11
    assert [unit['sort_order'] for unit in units] == list(range(11))
