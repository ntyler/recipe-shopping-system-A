import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_unit_registry_management import unit_registry_app, sign_in, registry_for
from test_unit_edit_usage_flow import seed_usage, reference_measurements
from PushShoppingList.services import recipe_master_data_service as master
from PushShoppingList.services import unit_category_service as categories
from PushShoppingList.services.ingredient_unit_service import canonical_unit


URL = '/api/master-data/unit-categories'


def create(client, name='Portions'):
    response = client.post(URL, json={'name': name, 'description': 'Serving measures'})
    assert response.status_code == 201, response.get_json()
    return response.get_json()['category_id']


def test_add_rename_order_and_refresh_preserve_ids_and_normalization(unit_registry_app):
    seed_usage()
    before = reference_measurements()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        key = create(client)
        assert key != 'Portions'
        saved = client.put('/api/master-data/units/volume_teaspoon', json={
            'canonical_name': 'teaspoon', 'category': key, 'aliases': ['tsp', 'tsps', 'teaspoons']})
        assert saved.status_code == 200
        initial = registry_for(client)
        renamed = client.put(URL + '/' + key, json={'name': 'Serving Sizes', 'description': 'Updated description'})
        assert renamed.status_code == 200
        assert renamed.get_json()['registry']['units'] == initial['units']
        moved = client.patch(URL + '/' + key, json={'action': 'move_to', 'position': 1})
        assert moved.status_code == 200
        assert moved.get_json()['registry']['categories'][0] == {
            'id': key, 'key': key, 'label': 'Serving Sizes', 'description': 'Updated description',
            'required': False, 'sort_order': 0, 'unit_count': 1}
        assert moved.get_json()['registry']['units'] == initial['units']
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        registry = registry_for(client)
        assert registry['categories'][0]['key'] == key
        assert 'Serving Sizes' in client.get('/admin/master-data/units').get_data(as_text=True)
    assert canonical_unit('tsp', user_id='user-a')['category'] == key
    assert canonical_unit('tsp', user_id='user-a')['id'] == 'volume_teaspoon'
    assert reference_measurements() == before


@pytest.mark.parametrize('name', ['', '  \t\n', 'VOLUME', '  volume  ', 'Ｖｏｌｕｍｅ', 'x' * 61])
def test_names_validated_on_server(unit_registry_app, name):
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        response = client.post(URL, json={'name': name})
        assert response.status_code == 422
        assert response.get_json()['errors']['name']
        assert len(registry_for(client)['categories']) == 4


def test_unicode_casefold_duplicates_and_concurrent_creation(unit_registry_app):
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        key = create(client, 'Straße')
        assert client.post(URL, json={'name': 'STRASSE'}).status_code == 422
        assert client.put(URL + '/' + key, json={'name': 'Weight'}).status_code == 422
        assert client.put(URL + '/' + key, json={'name': 'STRASSE'}).status_code == 200
        assert client.post(URL, json={'name': 'Long', 'description': 'x' * 301}).status_code == 422
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda name: categories.mutate_category({'name': name}, user_id='user-a'), ['Concurrent', 'CONCURRENT']))
    assert sum(bool(r['ok']) for r in results) == 1


@pytest.mark.parametrize('name', [True, 123, ['Portions'], {'name': 'Portions'}])
def test_category_names_must_be_text(unit_registry_app, name):
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        key = create(client)
        before = registry_for(client)
        for response in [client.post(URL, json={'name': name}),
                         client.put(URL + '/' + key, json={'name': name})]:
            assert response.status_code == 422
            assert response.get_json()['errors']['name']
        assert registry_for(client) == before


@pytest.mark.parametrize('description', [True, 123, ['details'], {'text': 'details'}])
def test_category_descriptions_must_be_text(unit_registry_app, description):
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        response = client.post(URL, json={'name': 'Portions', 'description': description})
        assert response.status_code == 422
        assert response.get_json()['errors']['description']
        assert len(registry_for(client)['categories']) == 4


def test_required_categories_rename_and_reorder_without_reseeding(unit_registry_app):
    master.ensure_workspace_unit_registry('user-a')
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        before = registry_for(client)['units']
        for key in ['volume', 'weight', 'count_package', 'optional']:
            assert client.delete(URL + '/' + key, json={'reassign_to': 'weight'}).status_code == 409
        assert client.put(URL + '/volume', json={'name': 'Liquids'}).status_code == 200
        # A previous display name is free to use; later schema/seeding cannot restore it.
        key = create(client, 'Volume')
        assert client.patch(URL + '/volume', json={'action': 'move_to', 'position': 3}).status_code == 200
        master.ensure_workspace_unit_registry('user-a')
        registry = registry_for(client)
        assert registry['units'] == before
        assert registry['categories'][2]['key'] == 'volume'
        assert registry['categories'][2]['label'] == 'Liquids'
        assert next(c for c in registry['categories'] if c['key'] == key)['label'] == 'Volume'


def test_guarded_delete_reassigns_atomically_and_preserves_references(unit_registry_app):
    seed_usage()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        key = create(client)
        for unit in registry_for(client)['units'][:2]:
            assert client.put('/api/master-data/units/' + unit['id'], json={
                'canonical_name': unit['name'], 'category': key, 'aliases': unit['aliases']}).status_code == 200
        before = registry_for(client)
        references = reference_measurements()
        blocked = client.delete(URL + '/' + key)
        assert blocked.status_code == 409 and blocked.get_json()['unit_count'] == 2
        assert registry_for(client) == before
        for target in [key, 'missing']:
            assert client.delete(URL + '/' + key, json={'reassign_to': target}).status_code == 422
            assert registry_for(client) == before
        deleted = client.delete(URL + '/' + key, json={'reassign_to': 'weight'})
        assert deleted.status_code == 200
        registry = deleted.get_json()['registry']
        assert key not in [c['key'] for c in registry['categories']]
        weight = [u for u in registry['units'] if u['category'] == 'weight']
        moved_ids = [u['id'] for u in before['units'] if u['category'] == key]
        assert [u['id'] for u in weight][-2:] == moved_ids
        assert [u['sort_order'] for u in weight] == list(range(len(weight)))
        for old in before['units']:
            new = next(u for u in registry['units'] if u['id'] == old['id'])
            assert {k: v for k, v in old.items() if k not in ('category', 'sort_order', 'updated_at')} == {
                k: v for k, v in new.items() if k not in ('category', 'sort_order', 'updated_at')}
        assert reference_measurements() == references
        assert registry_for(client) == registry
        assert client.post('/api/master-data/units', json={'name': 'stale category unit', 'category': key}).status_code == 422
        empty = create(client, 'Unused')
        assert client.delete(URL + '/' + empty).status_code == 200


def test_workspace_scope_and_invalid_positions(unit_registry_app):
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        key = create(client)
        for position in [None, 0, -1, 6, '2', 1.5, True]:
            assert client.patch(URL + '/' + key, json={'action': 'move_to', 'position': position}).status_code == 422
        sign_in(client, 'user-b')
        assert key not in [c['key'] for c in registry_for(client)['categories']]
        assert client.put(URL + '/' + key, json={'name': 'Foreign'}).status_code == 404
        assert client.delete(URL + '/' + key).status_code == 404
        assert client.post('/api/master-data/units', json={'name': 'foreign scoop', 'category': key}).status_code == 422
        assert create(client) != key


def test_old_database_category_migration_is_idempotent_and_read_compatible(unit_registry_app):
    master.ensure_workspace_unit_registry('user-a')
    master.ensure_workspace_unit_registry('user-b')
    with sqlite3.connect(master.recipe_master_db_path()) as connection:
        connection.execute('DROP TABLE workspace_unit_categories')
    database_before_read = master.recipe_master_db_path().read_bytes()
    before = master.read_workspace_unit_registry('user-a')
    before_other = master.read_workspace_unit_registry('user-b')
    assert master.recipe_master_db_path().read_bytes() == database_before_read
    assert len(before['units']) == 35
    assert before['categories'][0]['key'] == 'volume'
    master.ensure_workspace_unit_registry('user-a')
    first = master.read_workspace_unit_registry('user-a')
    master.ensure_workspace_unit_registry('user-a')
    assert master.read_workspace_unit_registry('user-a') == first
    assert first['units'] == before['units']
    assert master.read_workspace_unit_registry('user-b') == before_other
    with sqlite3.connect(master.recipe_master_db_path()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM workspace_unit_categories').fetchone()[0] == 8


@pytest.mark.parametrize('value,expected', [
    (' VOLUME ', 'volume'), ('Count Package', 'count_package'),
    ('count-package', 'count_package'), ('Ｗｅｉｇｈｔ', 'weight'),
])
def test_legacy_builtin_category_keys_still_save(unit_registry_app, value, expected):
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        response = client.post('/api/master-data/units', json={
            'name': 'legacy scoop', 'category': value})
        assert response.status_code == 201, response.get_json()
        assert next(u for u in registry_for(client)['units'] if u['name'] == 'legacy scoop')['category'] == expected


def test_failed_category_delete_rolls_back_unit_reassignment(unit_registry_app):
    seed_usage()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        key = create(client)
        response = client.put('/api/master-data/units/volume_teaspoon', json={
            'name': 'teaspoon', 'category': key, 'aliases': ['tsp', 'tsps', 'teaspoons']})
        assert response.status_code == 200
        before = registry_for(client)
        references = reference_measurements()
        with sqlite3.connect(master.recipe_master_db_path()) as connection:
            connection.execute("""
                CREATE TRIGGER reject_category_delete BEFORE DELETE ON workspace_unit_categories
                BEGIN SELECT RAISE(ABORT, 'injected delete failure'); END
            """)
        with pytest.raises(sqlite3.IntegrityError, match='injected delete failure'):
            client.delete(URL + '/' + key, json={'reassign_to': 'weight'})
        assert registry_for(client) == before
        assert reference_measurements() == references
