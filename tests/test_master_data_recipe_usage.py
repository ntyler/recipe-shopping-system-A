import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from test_recipe_master_data_routes import configure_master_data_app, seed_master_records, sign_in
from PushShoppingList.services import recipe_master_data_service as md


def test_both_pages_use_one_shared_usage_modal_and_ingredient_editor_stays_separate(monkeypatch, tmp_path):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    with app.test_client() as client:
        sign_in(client, 'user-a')
        for kind in ('ingredients', 'equipment'):
            soup = BeautifulSoup(client.get('/admin/master-data/' + kind).data, 'html.parser')
            dialogs = soup.select('[data-master-usage-dialog]')
            assert len(dialogs) == 1
            dialog = dialogs[0]
            assert dialog['data-record-type'] == kind
            assert dialog['aria-modal'] == 'true' and not dialog.has_attr('open')
            assert dialog.select_one('[data-master-usage-results]')['aria-label'] == 'Recipe list'
            assert len(dialog.select('[data-master-usage-close]')) == 2
            assert 'Recipe links open in a new tab.' in dialog.text
            assert not soup.select('[data-master-reference-row]')
            trigger = soup.select_one('[data-master-usage-button]')
            assert trigger['aria-haspopup'] == 'dialog' and trigger['aria-controls'] == dialog['id']
            assert trigger['data-master-usage-button'] == kind
            if kind == 'ingredients':
                editor = soup.select_one('[data-ingredient-editor-form]')
                assert editor.has_attr('hidden') and editor['id'] != dialog['id']
                assert soup.select_one('[data-ingredient-row-edit]')['aria-controls'] == editor['id']


@pytest.mark.parametrize('kind', ['ingredients', 'equipment'])
def test_usage_pages_preserve_distinct_totals_and_complete_reference_details(monkeypatch, tmp_path, kind):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    for index in range(3):
        md.sync_recipe_master_records(f'https://example.test/usage-{index}', recipe_data={
            'ingredients': [{'ingredient': 'Butter', 'buy_as': 'Butter' if index != 1 else 'Ghee'},
                            {'ingredient': 'Unsalted Butter', 'buy_as': 'Butter' if index == 2 else 'Other'}],
            'equipment': [{'equipment': 'Large pot'}],
        }, user_id='user-a')
    record = md.master_record_for_name(kind, 'user-a', 'butter' if kind == 'ingredients' else 'large pot')
    with app.test_client() as client:
        sign_in(client, 'user-a')
        offset = 0
        references = []
        while True:
            response = client.get(f'/api/master-data/{kind}/{record["id"]}/references?limit=1&offset={offset}')
            assert response.status_code == 200
            page = response.json
            assert page['total'] == 3
            if kind == 'ingredients':
                assert page['ingredient_name_recipe_count'] == 3
                assert page['buy_as_recipe_count'] == 2  # Overlap does not inflate the total.
            references.extend(page['references'])
            if page['next_offset'] is None:
                break
            assert page['next_offset'] > offset
            offset = page['next_offset']
        assert len(references) == page['total_reference_count']
        assert len({r['id'] for r in references}) == len(references)
        assert len({r['recipe_id'] for r in references}) == 3
        assert all(r['edit_url'].startswith('/recipe/edit?') for r in references)
        sign_in(client, 'user-b')
        assert client.get(f'/api/master-data/{kind}/{record["id"]}/references?offset=1').status_code == 404


def test_recipe_usage_grouping_combines_badges_and_keeps_each_matching_line():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for recipe card grouping')
    source = Path('PushShoppingList/static/js/master-data.js').read_text(encoding='utf-8')
    helpers = source[source.index('    function referenceDetailText('):source.index('    function renderReferenceItem(')]
    script = '''const assert = require('node:assert/strict');
const text = value => String(value || '');
''' + helpers + '''
const first = {user_id:'a',recipe_id:'recipe-1',recipe_title:'Soup',matches_ingredient_name:true,quantity:'1',unit:'cup'};
const otherLine = {...first,matches_ingredient_name:false,matches_buy_as:true,quantity:'2',preparation:'diced'};
const recipes = groupRecipeUsageReferences([first,otherLine,first,{...first,recipe_id:'recipe-2'}, {...first,user_id:'b'}]);
assert.equal(recipes.length,3);
assert.equal(recipes[0].matches_ingredient_name,true);
assert.equal(recipes[0].matches_buy_as,true);
assert.deepEqual(recipes[0].usage_details,['1 cup','2 cup | Preparation: diced']);
assert.deepEqual(groupRecipeUsageReferences([]),[]);
assert.equal(first.usage_details,undefined,'source data is not mutated');
'''
    subprocess.run([node, '-e', script], check=True, capture_output=True, text=True, timeout=30)


def test_zero_and_one_recipe_responses_keep_accurate_empty_and_single_states(monkeypatch, tmp_path):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    with md.recipe_master_connection(user_id='user-a') as connection:
        unused_id = md.upsert_master_record(connection, 'ingredients', 'user-a', 'Plum')['id']
    with app.test_client() as client:
        sign_in(client, 'user-a')
        empty = client.get(f'/api/master-data/ingredients/{unused_id}/references').json
        assert empty['total'] == empty['ingredient_name_recipe_count'] == empty['buy_as_recipe_count'] == 0
        assert empty['references'] == [] and empty['next_offset'] is None
        tomato = md.master_record_for_name('ingredients', 'user-a', 'tomato')
        single = client.get(f'/api/master-data/ingredients/{tomato["id"]}/references').json
        assert single['total'] == 1 and len(single['references']) == 1
        soup = BeautifulSoup(client.get('/admin/master-data/ingredients').data, 'html.parser')
        unused = soup.select_one(f'[data-ingredient-master-row][data-master-record-id="{unused_id}"]')
        assert 'Unused' in unused.text and not unused.select('[data-master-usage-button]')


def test_usage_loader_collects_all_pages_and_ignores_closed_dialog_responses():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for reference loading')
    source = Path('PushShoppingList/static/js/master-data.js').read_text(encoding='utf-8')
    loader = source[source.index('    async function loadReferenceData('):source.index('    function equipmentMasterDisplayNameElements(')]
    script = '''const assert = require('node:assert/strict');
global.window = {fetch:true};
const canonicalMasterDataUrl = raw => new URL(raw, 'http://localhost');
const setReferenceLoading = () => {};
const setReferenceError = (_, message) => { throw new Error(message); };
let rendered = null;
const renderLoadedReferenceData = (_, data) => { rendered = data; };
const first = {references:[{id:1}], total:2, next_offset:1};
const last = {references:[{id:2}], total:2, next_offset:null};
const requests = [];
global.fetch = async url => { requests.push(url);return {ok:true,json:async()=>url.includes('offset=1')?last:first}; };
''' + loader + '''
(async()=>{
    const button = {dataset:{referenceUrl:'/references'}}, panel = {};
    const data = await loadReferenceData(button,panel,{allReferences:true,shouldRender:()=>true});
    assert.equal(requests.length,2);
    assert.deepEqual(data.references,[{id:1},{id:2}]);
    assert.equal(rendered,data);
    await loadReferenceData(button,panel,{allReferences:true,shouldRender:()=>true});
    assert.equal(requests.length,2,'complete responses can be reused');
    rendered = null;
    const closed = {dataset:{referenceUrl:'/references'}};
    assert.equal(await loadReferenceData(closed,panel,{allReferences:true,shouldRender:()=>false}),null);
    assert.equal(requests.length,3,'closing prevents loading further pages');
    assert.equal(rendered,null);
    assert.equal(closed.masterDataReferenceData,undefined);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    subprocess.run([node, '-e', script], check=True, capture_output=True, text=True, timeout=30)
