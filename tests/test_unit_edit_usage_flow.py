import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from PushShoppingList.services import recipe_master_data_service as md
from test_unit_registry_management import unit_registry_app, sign_in, registry_for, unit_named


def seed_usage():
    for index in range(3):
        md.sync_recipe_master_records(f'https://example.test/units-{index}', recipe_data={'ingredients': [
            {'recipe_ingredient_id': 'salt', 'ingredient': 'salt', 'quantity': '1/2', 'unit': 'tsp', 'original_text': '1/2 tsp salt'},
            {'recipe_ingredient_id': 'sugar', 'ingredient': 'sugar', 'quantity': '2', 'unit': 'cup', 'substitutions': [
                {'alternative_id': 'honey', 'ingredient': 'honey', 'quantity': '3', 'unit': 'tsp', 'original_text': '3 tsp honey'}]},
        ]}, user_id='user-a')


def reference_measurements():
    with md.existing_recipe_master_read_connection() as db:
        return {table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                for table in ('recipe_ingredients', 'recipe_ingredient_option_items')}


def test_rename_and_alias_removal_preserve_identity_amounts_and_saved_usage(unit_registry_app):
    seed_usage()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        unit = unit_named(registry_for(client), 'teaspoon')
        # Exercise legacy references without IDs, including a raw-text-only alias.
        with md.recipe_master_connection(user_id='user-a') as db:
            db.execute("UPDATE recipe_ingredients SET unit_id=NULL, unit='', unit_raw='tsp' WHERE unit_id=?", (unit['id'],))
            db.execute("UPDATE recipe_ingredient_option_items SET unit_id=NULL WHERE unit_id=?", (unit['id'],))
        before = reference_measurements()
        result = client.put(f'/api/master-data/units/{unit["id"]}', json={
            'canonical_name': 'measuring teaspoon', 'category': 'volume', 'aliases': [],
        })
        assert result.status_code == 200
        renamed = unit_named(result.json['registry'], 'measuring teaspoon')
        assert renamed['id'] == unit['id'] and renamed['recipe_count'] == 3
        assert renamed['category'] == unit['category'] and 'teaspoon' in renamed['aliases']
        after = reference_measurements()
        for table, rows in before.items():
            for old, new in zip(rows, after[table]):
                assert {k: v for k, v in old.items() if k not in ('unit', 'unit_id')} == {
                    k: v for k, v in new.items() if k not in ('unit', 'unit_id')}
        # Removing an alias alone also keeps already-saved legacy references.
        with md.recipe_master_connection(user_id='user-a') as db:
            db.execute("UPDATE recipe_ingredients SET unit_id=NULL, unit='teaspoon' WHERE unit_id=?", (unit['id'],))
        removed = client.put(f'/api/master-data/units/{unit["id"]}', json={
            'canonical_name': 'measuring teaspoon', 'aliases': [],
        })
        assert removed.status_code == 200
        assert unit_named(removed.json['registry'], 'measuring teaspoon')['recipe_count'] == 3
        assert client.delete(f'/api/master-data/units/{unit["id"]}/references').status_code == 405


@pytest.mark.parametrize('field,value', [('recipe_count', 88), ('usage_count', 0), ('references', []), ('quantity', 123), ('conversion_factor', 10)])
def test_unit_updates_cannot_override_usage_or_measurements(unit_registry_app, field, value):
    seed_usage()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        before = reference_measurements()
        response = client.patch('/api/master-data/units/volume_teaspoon', json={
            'canonical_name': 'teaspoon', 'category': 'volume', 'aliases': [], field: value,
        })
        assert response.status_code == 422
        assert reference_measurements() == before


def test_usage_paginates_distinct_recipes_and_links_each_saved_entry(unit_registry_app):
    seed_usage()
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        pages = [client.get(f'/api/master-data/units/volume_teaspoon/references?limit=1&offset={i}').json for i in range(3)]
        assert all(page['total'] == 3 and page['total_reference_count'] == 6 for page in pages)
        assert [page['next_offset'] for page in pages] == [1, 2, None]
        references = [page['references'][0] for page in pages]
        assert len({reference['recipe_id'] for reference in references}) == 3
        for reference in references:
            for match in reference['matches']:
                url = urlsplit(match['edit_url'])
                assert url.path == '/recipe/edit' and 'viewer_user_id=user-a' in url.query
                target = json.loads(unquote(url.fragment.removeprefix('unit-usage=')))
                if match['ingredient_name'] == 'salt':
                    assert target['parent_index'] == 0 and target['option_id'] == ''
                else:
                    assert target['parent_index'] == 1 and target['option_id'] == 'honey'
                assert match['ingredient_name'] in target['names']
        sign_in(client, 'user-b')
        assert client.get('/api/master-data/units/volume_teaspoon/references').json['total'] == 0


def test_alias_suggestions_work_for_unseeded_workspace_without_writing(unit_registry_app, monkeypatch):
    from PushShoppingList.services import unit_suggestion_service as ai
    seed_usage()
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(ai, 'request_openai_unit_suggestion', lambda *args, **kwargs: (
        {'canonical_name': 'BAD NAME', 'category': 'weight', 'recipe_count': 99, 'aliases': ['tea spoons']}, 'test', 'test'))
    with unit_registry_app.test_client() as client:
        sign_in(client, 'user-a')
        before = reference_measurements()
        response = client.post('/api/master-data/units/suggest', json={
            'unit_id': 'volume_teaspoon', 'canonical_name': 'teaspoon', 'category': 'volume', 'aliases': ['tsp'],
        })
        assert response.status_code == 200
        assert response.json['suggestion'] == {'aliases': ['tsp', 'tea spoons']}
        assert reference_measurements() == before
        assert md.read_workspace_unit_registry('user-a') is None


def test_recipe_usage_target_opens_correct_editor_and_rejects_stale_links():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for ingredient navigation checks')
    source = Path('PushShoppingList/static/js/app.js').read_text(encoding='utf-8')
    helper = source[source.index('function openRecipeIngredientUsageTarget('):source.index('function focusRecipeAiQualityIngredient(')]
    script = '''const assert = require('node:assert/strict');
let opened = null, error = '';
const option={ingredient:'honey',alternative_id:'honey-option',alternative_component_order:'0'};
const rows=[{ingredient:'salt',scrollIntoView:()=>{}},{ingredient:'sugar',scrollIntoView:()=>{},querySelectorAll:()=>[option]}];
const recipeEditIngredientRows=()=>rows, fieldValuesFromRow=row=>row;
const setRecipeEditActiveTab=()=>{},setRecipeIngredientsCollapsed=()=>{},setRecipeEditStatus=value=>error=value;
const setRecipeIngredientEditMode=row=>opened=row,openRecipeIngredientOptionModal=row=>opened=row;
const hash=target=>'#unit-usage='+encodeURIComponent(JSON.stringify(target));
''' + helper + '''
assert(openRecipeIngredientUsageTarget(hash({parent_index:0,names:['salt']})));
assert.equal(opened,rows[0]);
assert(openRecipeIngredientUsageTarget(hash({parent_index:1,names:['honey'],option_id:'honey-option',component_index:0})));
assert.equal(opened,option);
opened=null;
assert.equal(openRecipeIngredientUsageTarget(hash({parent_index:0,names:['changed ingredient']})),false);
assert.equal(opened,null);assert.match(error,/has changed/);
assert.equal(openRecipeIngredientUsageTarget('#unit-usage=invalid'),false);
'''
    subprocess.run([node, '-e', script], check=True, capture_output=True, text=True, timeout=30)
