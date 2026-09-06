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
    assert table.select_one('[data-master-store-section-select]')['form'] == form['id']
    assert not table.select('[data-master-mobile-record-toggle]')
    assert soup.select_one('[data-ingredient-row-save]').has_attr('disabled')
    assert soup.select_one('[data-ingredient-row-cancel]').has_attr('hidden')
    assert soup.select_one('[data-recipe-edit-store-section-trigger] svg')
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


def test_row_save_snapshots_external_fields_locks_pending_and_preserves_failed_drafts():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the row editing interaction test')
    source = Path('PushShoppingList/static/js/master-data.js').read_text(encoding='utf-8')
    controller = source[source.index('    let ingredientEditingRow = null;'):
                        source.index('    function initIngredientRegistry()')]
    harness = r'''
const assert = require('node:assert/strict');
const classes = () => ({toggle(){}, remove(){}, add(){}});
const control = (value='') => ({value, disabled:false, hidden:false, classList:classes(),
    setAttribute(){}, focus(){}, textContent:''});
const fields = Object.fromEntries(['name','normalized_name','store_section'].map(name => [name,control()]));
Object.assign(fields.name,{value:'Tomato'});
Object.assign(fields.normalized_name,{value:'tomato'});
Object.assign(fields.store_section,{value:'PRODUCE'});
const controls = Object.fromEntries(['alias-input','alias-empty','row-edit','row-save','row-cancel','order-handle','row-status'].map(name=>[name,control()]));
const up=control(),down=control(),merge=control(),status=control();
const form={action:'/admin/master-data/ingredients/1',reportValidity:()=>true};
const row={dataset:{masterRecordId:'1',orderEnabled:'true',sortOrder:'0',sectionCount:'3'},
    aliases:['tomatoes'], classList:classes(),setAttribute(){},removeAttribute(){},
    querySelector(selector){
        if(selector==='form')return form;
        if(selector.startsWith('[name='))return fields[selector.match(/"(.*?)"/)[1]];
        if(selector==='[data-master-merge-open]')return merge;
        if(selector.includes('order-action'))return selector.includes('up')?up:down;
        return controls[selector.replace('[data-ingredient-','').replace(']','')];
    },
    querySelectorAll(selector){
        if(selector==='[data-ingredient-alias]')return this.aliases.map(alias=>({dataset:{ingredientAlias:alias}}));
        if(selector==='button, input, select')return [...Object.values(fields),...Object.values(controls),up,down,merge];
        return [];
    }};
global.document={querySelectorAll:()=>[row],querySelector:selector=>selector.includes('registry-status')?status:controls['row-edit']};
global.window={location:{href:'http://localhost/admin/master-data/ingredients'}};
const syncRecipeIngredientStoreSectionControl=()=>{};
let refreshes=0,attempts=[],fail=true,release;
const gate=new Promise(resolve=>{release=resolve;});
const refreshMasterDataRecordResults=async()=>{refreshes++;};
global.fetch=async(url,options)=>{
    const payload=JSON.parse(options.body);attempts.push(payload);
    assert([...Object.values(fields),controls['row-cancel']].every(c=>c.disabled));
    await gate;
    return {ok:!fail,json:async()=>fail?{ok:false,message:'Alias conflict'}:{ok:true,result:payload}};
};
'''
    assertions = r'''
// Alias DOM creation is covered in browser QA; here keep real save/cancel/dirty logic
// while modelling the external section select and chip collection.
renderIngredientAliases = (row,aliases)=>{row.aliases=[...aliases];syncIngredientRowControls();};
(async()=>{
    row.ingredientOriginal=ingredientRowValues(row);
    editIngredientRow(row);
    assert.equal(controls['row-save'].disabled,true);
    fields.store_section.value='DAIRY & EGGS';
    syncIngredientRowControls();
    assert.equal(controls['row-save'].disabled,false,'a section-only edit enables Save');
    cancelIngredientRow(row);
    assert.equal(fields.store_section.value,'PRODUCE');
    editIngredientRow(row);
    fields.name.value='Roma tomato';fields.normalized_name.value='roma tomato';
    fields.store_section.value='DAIRY & EGGS';controls['alias-input'].value='Roma';
    const saving=saveIngredientRow(row);
    assert.equal(controls['row-save'].disabled,true);
    await saveIngredientRow(row);
    cancelIngredientRow(row);
    assert.equal(fields.name.value,'Roma tomato','Cancel cannot erase a pending request');
    assert.equal(attempts.length,1,'duplicate submission is ignored');
    release();await saving;
    assert.deepEqual(attempts[0],{name:'Roma tomato',normalized_name:'roma tomato',store_section:'DAIRY & EGGS',aliases:['Roma','tomatoes'],redirect_url:window.location.href});
    assert.equal(ingredientRowIsDirty(row),true);
    assert.equal(controls['row-status'].textContent,'Alias conflict');
    assert.equal(controls['row-save'].disabled,false);
    assert.equal(refreshes,0,'a failed save keeps the draft in place');
    fail=false;await saveIngredientRow(row);
    assert.equal(refreshes,1);assert.equal(ingredientRowIsDirty(row),false);
    assert.equal(controls['row-save'].disabled,true);
    editIngredientRow(row);row.aliases=[];fields.store_section.value='PRODUCE';
    cancelIngredientRow(row);
    assert.deepEqual(row.aliases,['Roma','tomatoes']);
    assert.equal(fields.store_section.value,'DAIRY & EGGS');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    subprocess.run([node, '-e', harness + controller + assertions], check=True,
                   capture_output=True, text=True, encoding='utf-8', timeout=30)
