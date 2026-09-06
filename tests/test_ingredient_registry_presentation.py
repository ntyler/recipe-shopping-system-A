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
    assert [th.text for th in table.select('thead th')] == ['Item', 'Store Section', 'Usage', 'Last Updated']
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
    assert table.select_one('[data-master-store-section-select]')['form'] == form['id']
    assert table.select_one('[data-master-mobile-record-toggle]')['aria-expanded'] == 'false'
    assert soup.select_one('[data-master-record-save]').has_attr('disabled')
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


def test_ingredient_bulk_save_captures_fields_and_tracks_external_section_changes():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the bulk editing interaction test')
    script = Path('PushShoppingList/static/js/master-data.js').read_text(encoding='utf-8')
    helpers = script[script.index('    function masterDataStoreSectionForms('):
                     script.index('    function initMasterDataStoreSectionIconPickers(')]
    harness = r'''
const assert = require('node:assert/strict');
const classes = () => ({toggle(){}, remove(){}, add(){}});
const control = (name, value, external = false) => ({
    name, value, external, disabled: false, dataset: {}, listeners: {},
    matches: () => true,
    addEventListener(type, handler) { this.listeners[type] = handler; },
});
const forms = ['Tomato', 'Carrot'].map(name => {
    const elements = [control('name', name), control('store_section', 'PRODUCE', true)];
    elements.namedItem = name => elements.find(field => field.name === name);
    const row = {classList: classes()};
    return {elements, action: '/save/' + name, method: 'POST', classList: classes(),
        contains: field => !field.external, closest: () => row,
        addEventListener(){}, checkValidity: () => true, reportValidity: () => true};
});
const button = {disabled: true, addEventListener(){}};
const panel = {classList: classes(), attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    getAttribute(name) { return this.attributes[name]; },
    querySelector: selector => selector.includes('-save]') ? button : {textContent: ''}};
global.document = {querySelectorAll: () => forms, querySelector: () => panel};
const text = value => String(value ?? '');
let syncCount = 0, reloads = 0, attempts = [], failCarrot = true, release;
const gate = new Promise(resolve => { release = resolve; });
const syncRecipeIngredientStoreSectionControl = field => {
    field.triggerDisabled = field.disabled; syncCount++;
};
global.FormData = class {
    constructor(form) { this.fields = Object.fromEntries(form.elements.filter(f => !f.disabled).map(f => [f.name, f.value])); }
};
global.fetch = async (url, options) => {
    attempts.push({url, fields: options.body.fields});
    assert(forms.every(form => form.elements.every(field => field.disabled)));
    assert(forms.every(form => form.elements[1].triggerDisabled));
    await gate;
    return {ok: !(url.endsWith('Carrot') && failCarrot), json: async () => ({message: 'Try again'})};
};
global.window = {fetch, FormData, setTimeout: () => { reloads++; }};
'''
    assertions = r'''
(async () => {
    initMasterDataStoreSectionBatchSave();
    assert.equal(button.disabled, true);
    const section = forms[0].elements[1];
    section.value = 'BAKERY';
    section.listeners.change();
    assert.equal(button.disabled, false, 'a section-only edit enables Save');
    forms[1].elements[0].value = 'Baby carrots';
    const saving = saveChangedStoreSections();
    assert.equal(button.textContent, 'Saving...');
    section.listeners.change();
    assert.equal(button.disabled, true, 'events cannot unlock a pending save');
    await saveChangedStoreSections();
    assert.equal(attempts.length, 1, 'concurrent submissions are ignored');
    release();
    await saving;
    assert.deepEqual(attempts.map(a => a.fields), [
        {name: 'Tomato', store_section: 'BAKERY'},
        {name: 'Baby carrots', store_section: 'PRODUCE'},
    ], 'all fields survive the saving lock');
    assert.equal(reloads, 0, 'failed edits remain available for retry');
    assert.deepEqual(changedStoreSectionForms(), [forms[1]]);
    assert(forms.every(form => form.elements.every(field => !field.disabled)));
    assert.equal(button.disabled, false);
    failCarrot = false;
    await saveChangedStoreSections();
    assert.equal(attempts.length, 3, 'retry submits only the failed record');
    assert.equal(reloads, 1);
    assert.equal(button.disabled, true);
    assert(syncCount >= 8, 'enhanced section controls follow the saving lock');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, '-e', harness + helpers + assertions], check=True,
                   capture_output=True, text=True, encoding='utf-8', timeout=30)
