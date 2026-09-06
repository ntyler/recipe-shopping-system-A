import json
import sqlite3
import subprocess
import sys

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.services import recipe_master_data_service as md
from test_recipe_master_data_routes import configure_master_data_app, sign_in


@pytest.fixture
def registry(monkeypatch, tmp_path):
    app, database, _ = configure_master_data_app(monkeypatch, tmp_path)
    with md.recipe_master_connection(user_id='user-a') as conn:
        md.ensure_ingredient_store_sections_for_user(conn, 'user-a')
        for owner, name, section in [('user-a','Tomato','PRODUCE'), ('user-a','Carrot','PRODUCE'), ('user-a','Corn','PRODUCE'), ('user-a','Milk','DAIRY & EGGS'), ('user-b','Tomato','PRODUCE')]:
            conn.execute("INSERT INTO ingredients(user_id,name,normalized_name,store_section,created_at,updated_at) VALUES(?,?,?,?,?,?)", (owner,name,name.lower(),section,'2026-01-01','2026-01-02'))
    return app, database


def stored(database, owner='user-a', section='PRODUCE'):
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute('SELECT * FROM ingredients WHERE user_id=? AND store_section=? ORDER BY sort_order,id', (owner, section))]


def test_legacy_backfill_preserves_data_and_valid_order(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE ingredients(id INTEGER PRIMARY KEY, user_id TEXT, name TEXT, store_section TEXT, updated_at TEXT)')
        conn.executemany('INSERT INTO ingredients VALUES(?,?,?,?,?)', [(1,'a','Tomato','PRODUCE','2026-01'),(2,'a','Carrot','PRODUCE','2026-02'),(3,'a','Milk','DAIRY','2026-03'),(4,'b','Tomato','PRODUCE','2026-04')])
    before = path.read_bytes()
    command = [sys.executable, '-m', 'PushShoppingList.scripts.migrate_ingredient_order', '--database', str(path)]
    result = subprocess.run([*command, '--dry-run'], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['changed_rows'] == 4
    assert path.read_bytes() == before
    subprocess.run(command, check=True, capture_output=True)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert [row['id'] for row in conn.execute("SELECT * FROM ingredients WHERE user_id='a' AND store_section='PRODUCE' ORDER BY sort_order")] == [2, 1]
        assert md.migrate_ingredient_order(conn) == 0
        assert [tuple(row)[:5] for row in conn.execute('SELECT * FROM ingredients ORDER BY id')] == [(1,'a','Tomato','PRODUCE','2026-01'),(2,'a','Carrot','PRODUCE','2026-02'),(3,'a','Milk','DAIRY','2026-03'),(4,'b','Tomato','PRODUCE','2026-04')]


def test_manual_move_is_atomic_and_rejects_partial_or_stale_groups(registry):
    app, database = registry
    before = stored(database)
    ids = [row['id'] for row in before]
    other = stored(database, 'user-b')
    result = md.move_ingredient_master_record(ids[-1], 1, ids, user_id='user-a')
    assert result['ok']
    after = stored(database)
    assert [row['name'] for row in after] == ['Corn','Tomato','Carrot']
    assert [row['sort_order'] for row in after] == [0,1,2]
    assert {row['updated_at'] for row in after} == {'2026-01-02'}
    assert md.move_ingredient_master_record(ids[0], 1, ids, user_id='user-a')['status'] == 409
    assert md.move_ingredient_master_record(ids[0], 1, [ids[0]], user_id='user-a')['status'] == 409
    assert md.move_ingredient_master_record(ids[0], 1, ids, user_id='user-b')['status'] == 404
    assert stored(database) == after
    assert stored(database, 'user-b') == other


@pytest.mark.parametrize('position', [True, 0, -1, 1.5, '1', None])
def test_invalid_positions_do_not_write(registry, position):
    _, database = registry
    before = stored(database)
    assert md.move_ingredient_master_record(before[0]['id'], position, [row['id'] for row in before], user_id='user-a')['status'] == 400
    assert stored(database) == before


def test_alias_conflicts_rollback_all_fields_and_section_move(registry):
    _, database = registry
    before = stored(database)
    record = before[0]
    result = md.update_ingredient_master_record(record['id'], 'Roma tomato', 'roma tomato', 'DAIRY & EGGS', user_id='user-a', aliases=['Carrot'])
    assert result['status'] == 409
    assert stored(database) == before
    result = md.update_ingredient_master_record(record['id'], 'Roma tomato', 'roma tomato', 'DAIRY & EGGS', user_id='user-a', aliases=['tomatoes',' Tomatoes ','roma'])
    assert result['ok']
    assert result['aliases'] == ['roma','Tomatoes']
    assert [row['sort_order'] for row in stored(database)] == [0,1]
    assert [row['name'] for row in stored(database, section='DAIRY & EGGS')] == ['Milk','Roma tomato']
    assert result['sort_order'] == 1
    listed = md.list_ingredients(user_id='user-a', search='Roma tomato')[0]
    assert listed['aliases'] == ['roma', 'Tomatoes']
    assert md.update_ingredient_master_record(before[1]['id'], 'Carrot', 'carrot', 'PRODUCE', user_id='user-a', aliases=['ROMA'])['status'] == 409
    result = md.update_ingredient_master_record(record['id'], 'Roma tomato', 'roma tomato', 'DAIRY & EGGS', user_id='user-a', aliases=[])
    assert result['aliases'] == []


def test_all_write_paths_append_move_and_remove_atomically(registry):
    _, database = registry
    original = stored(database)
    with md.recipe_master_connection(user_id='user-a') as conn:
        conn.execute("INSERT INTO ingredients(user_id,name,normalized_name,store_section,created_at,updated_at) VALUES('user-a','Onion','onion','PRODUCE','old','old')")
        conn.execute("UPDATE ingredients SET store_section='DAIRY & EGGS' WHERE id=?", (original[1]['id'],))
    assert [row['name'] for row in stored(database)] == ['Tomato','Corn','Onion']
    assert [row['sort_order'] for row in stored(database)] == [0,1,2]
    assert [row['name'] for row in stored(database, section='DAIRY & EGGS')] == ['Milk','Carrot']
    with pytest.raises(RuntimeError):
        with md.recipe_master_connection(user_id='user-a') as conn:
            conn.execute('DELETE FROM ingredients WHERE id=?', (original[0]['id'],))
            raise RuntimeError('rollback')
    assert [row['name'] for row in stored(database)] == ['Tomato','Corn','Onion']
    with md.recipe_master_connection(user_id='user-a') as conn:
        conn.execute('DELETE FROM ingredients WHERE id=?', (original[0]['id'],))
    assert [row['sort_order'] for row in stored(database)] == [0,1]


def test_routes_filter_partial_groups_and_expose_six_columns(registry):
    app, database = registry
    with app.test_client() as client:
        sign_in(client, 'user-a')
        for query, enabled in [('sort=manual_order', True),('sort=name_asc',False),('sort=manual_order&search=Tomato',False),('sort=manual_order&limit=1',False)]:
            soup = BeautifulSoup(client.get('/admin/master-data/ingredients?'+query).data, 'html.parser')
            assert [th.text for th in soup.select('.master-data-ingredients-table thead th')] == ['Order','Item','Aliases','Store Section','Used In','Action']
            first = soup.select_one('[data-ingredient-master-row]')
            assert first['data-order-enabled'] == str(enabled).lower()
            assert first.select_one('[data-ingredient-order-handle]')['aria-disabled'] == str(not enabled).lower()
            assert not soup.select('[data-master-store-section-panel]')
            assert first.select_one('[data-ingredient-row-edit]')
            assert first.select_one('[data-ingredient-row-save]').has_attr('disabled')
            assert first.select_one('time[datetime]')
        soup = BeautifulSoup(client.get('/admin/master-data/ingredients?sort=manual_order&store_section=PRODUCE').data, 'html.parser')
        assert not soup.select('.master-data-section-row')
        assert len(soup.select('[data-order-enabled="true"]')) == 3
        rows = stored(database)
        ids = [row['id'] for row in rows]
        assert client.patch(f'/api/master-data/ingredients/{ids[-1]}/order', json={'position':1,'expected_ids':ids}).status_code == 200
        assert client.patch(f'/api/master-data/ingredients/{ids[-1]}/order', json={'position':1,'expected_ids':ids}).status_code == 409
        response = client.post(f'/admin/master-data/ingredients/{ids[0]}', json={'name':'Tomato','normalized_name':'tomato','store_section':'PRODUCE','aliases':['tomatoes']})
        assert response.status_code == 200
        assert response.json['result']['aliases'] == ['tomatoes']
        assert client.get('/admin/master-data/ingredients?search=tomatoes').data.count(b'data-ingredient-master-row ') == 1


def test_merge_and_restart_leave_dense_section_order(registry):
    app, database = registry
    rows = stored(database)
    merged = md.merge_ingredient_master_records(rows[0]['id'], rows[1]['id'], user_id='user-a')
    assert merged['ok']
    before = stored(database)
    assert [row['sort_order'] for row in before] == [0,1]
    script = '''
import sys
from pathlib import Path
from PushShoppingList.services import recipe_master_data_service as md
md.RECIPE_MASTER_DB_PATH = Path(sys.argv[1])
with md.recipe_master_connection(user_id='user-a'):
    pass
'''
    subprocess.run([sys.executable, '-c', script, str(database)], check=True, capture_output=True)
    assert stored(database) == before
    assert md.undo_last_ingredient_master_merge('user-a')['ok']
    assert {row['name'] for row in stored(database)} == {'Tomato', 'Carrot', 'Corn'}
    assert [row['sort_order'] for row in stored(database)] == [0, 1, 2]


def test_mid_reorder_database_failure_rolls_back_every_position(registry):
    _, database = registry
    before = stored(database)
    ids = [row['id'] for row in before]
    with sqlite3.connect(database) as conn:
        conn.execute(f"""CREATE TRIGGER reject_second_position BEFORE UPDATE OF sort_order ON ingredients
            WHEN NEW.id = {ids[0]} AND NEW.sort_order = 1
            BEGIN SELECT RAISE(ABORT, 'injected reorder failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='injected reorder failure'):
        md.move_ingredient_master_record(ids[-1], 1, ids, user_id='user-a')
    assert stored(database) == before


def test_concurrent_processes_append_without_duplicate_positions(registry):
    from concurrent.futures import ThreadPoolExecutor

    _, database = registry
    script = '''
import sys
from pathlib import Path
from PushShoppingList.services import recipe_master_data_service as md
md.RECIPE_MASTER_DB_PATH = Path(sys.argv[1])
for i in range(4):
    name = sys.argv[2] + str(i)
    with md.recipe_master_connection(user_id='user-a') as conn:
        conn.execute("INSERT INTO ingredients(user_id,name,normalized_name,store_section,created_at,updated_at) VALUES('user-a',?,?,'PRODUCE','old','old')", (name,name))
'''
    def append(prefix):
        subprocess.run([sys.executable, '-c', script, str(database), prefix], check=True, capture_output=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(append, ['first-', 'second-']))
    rows = stored(database)
    assert [row['name'] for row in rows[:3]] == ['Tomato', 'Carrot', 'Corn']
    assert [row['sort_order'] for row in rows] == list(range(11))


@pytest.mark.parametrize('aliases', ['invalid', {}, [''], [17], ['a' * 161], ['a'] * 101])
def test_invalid_alias_payload_preserves_record(registry, aliases):
    _, database = registry
    before = stored(database)
    result = md.update_ingredient_master_record(before[0]['id'], 'New name', 'new name', 'DAIRY & EGGS', user_id='user-a', aliases=aliases)
    assert result['status'] == 400
    assert stored(database) == before
