from bs4 import BeautifulSoup
from pathlib import Path
import shutil
import subprocess

import pytest

from test_recipe_master_data_routes import configure_master_data_app, seed_master_records, sign_in


def test_ingredient_page_name_and_controls_preserve_existing_endpoints(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    with app.test_client() as client:
        sign_in(client, 'user-a')
        response = client.get('/admin/master-data/ingredients')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.title.text == 'Ingredient'
    assert soup.select_one('#masterDataTitle').text == 'Ingredient'
    assert soup.select_one('.master-data-tabs [aria-current="page"]').get_text(strip=True) == 'Ingredient'
    assert soup.select_one('.master-data-home-link').text == 'Account'
    table = soup.select_one('table[aria-label="Ingredient"]')
    assert [th.text for th in table.select('thead th')] == ['Order', 'Item', 'Aliases', 'Store Section', 'Used In', 'Action']
    assert 'master-data-registry-category' in table.parent['class']
    filters = soup.select_one('.ingredient-master-registry .master-data-filter-form')
    assert filters['action'] == '/admin/master-data/ingredients'
    assert {control['name'] for control in filters.select('[name]')} == {'search', 'store_section', 'sort', 'limit'}
    assert filters.select_one('[data-master-thumbnail-size-controls]')
    assert filters.select_one('[data-master-thumbnail-size-value]').text == '48px'
    form = table.select_one('[data-master-record-form]')
    assert form['action'].startswith('/admin/master-data/ingredients/')
    assert form.select_one('input[name="name"]')['value'] == 'Tomato'
    assert form.select_one('input[name="normalized_name"]')
    assert form.select_one('input[name="store_section"]')
    assert soup.select_one('[data-ingredient-editor-section]')
    assert not table.select('[data-master-mobile-record-toggle]')
    assert soup.select_one('[data-ingredient-row-save]').has_attr('disabled')
    assert soup.select_one('[data-ingredient-editor-form]').has_attr('hidden')
    assert soup.select_one('[data-ingredient-editor-cancel]')
    assert soup.select_one('.ingredient-section-summary svg')
    assert table.select_one('time[datetime]')
    assert 'Ingredient Master Data' not in response.get_data(as_text=True)


def test_ingredient_name_is_used_in_shared_navigation(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    with app.test_client() as client:
        sign_in(client, 'user-a')
        for page, title in [('equipment', 'Equipment'), ('types', 'Types'), ('units', 'Units'), ('cuisine-categories', 'Cuisine Categories'), ('store-sections', 'Store Sections')]:
            soup = BeautifulSoup(client.get('/admin/master-data/'+page).data, 'html.parser')
            assert soup.title.text == title
            link = soup.select_one('.master-data-tabs a[href="/admin/master-data/ingredients"]')
            assert link.get_text(strip=True) == 'Ingredient'
            if page == 'equipment':
                assert soup.select_one('[data-master-thumbnail-size-value]').text == '64px'


def test_ingredient_editor_validates_complete_registry_and_semantic_changes():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for ingredient validation')
    source = Path('PushShoppingList/static/js/master-data.js').read_text(encoding='utf-8')
    helpers = source[source.index('    function ingredientText('):source.index('    function ingredientEditorControl(')]
    assertions = r'''const assert = require('node:assert/strict');
const registry = [{id:1,name:'Tomato',normalized_name:'tomato',aliases:['tomatoes']},
                  {id:2,name:'Carrot',normalized_name:'carrot',aliases:['carrots']}];
const sections = [{section_key:'PRODUCE'}];
const original = {name:'Tomato',normalized_name:'tomato',store_section:'PRODUCE',aliases:['tomatoes'],image_url:'/original.png'};
const validate = changes => validateIngredientDraft({...original,...changes},registry,1,sections);
assert.deepEqual(validate({}),{aliases:{}});
assert(validate({aliases:['tomatoes',' TOMATOES ']}).aliases[1]);
assert(validate({aliases:[' CARROTS ']}).aliases[0].includes('Carrot'));
assert(validate({aliases:[' Carrot ']}).aliases[0].includes('Carrot'));
assert(validate({name:'carrots'}).name.includes('Carrot'));
assert(validate({aliases:['tomato']}).aliases[0]);
assert(validate({store_section:'INVALID'}).section);
assert(validate({name:'   '}).name);
assert.equal(ingredientKey('  Sweet   Potatoes '),'sweet potatoes');
assert.equal(ingredientDraftSignature(original),ingredientDraftSignature({...original,name:' Tomato ',aliases:[' tomatoes ']}));
for (const changes of [{name:'Roma tomato'}, {store_section:'DAIRY & EGGS'}, {aliases:[]}, {image_url:''}])
    assert.notEqual(ingredientDraftSignature(original),ingredientDraftSignature({...original,...changes}));
'''
    subprocess.run([node, '-e', helpers + assertions], check=True,
                   capture_output=True, text=True, encoding='utf-8', timeout=30)
