"""Meal-plan shopping interactions using production JS and a small DOM boundary.

These tests do not claim native-dialog or browser layout verification.
"""

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHOPPING_JS = ROOT / "PushShoppingList/static/js/meal-plan-shopping.js"
requires_node = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for interaction checks")


def run_shopping(script):
    bootstrap = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const plain=value=>JSON.parse(JSON.stringify(value));
const decode=value=>String(value??'').replace(/&(?:amp|lt|gt|quot|#39);/g,value=>({'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"}[value]));
const camel=value=>value.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
function element(tag='button',attrs={}) {
 const classes=new Set();
 return {tag,attrs,dataset:Object.fromEntries(Object.entries(attrs).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[camel(key.slice(5)),value])),
  checked:'checked' in attrs,disabled:'disabled' in attrs,hidden:'hidden' in attrs,value:attrs.value||'',textContent:'',focused:false,
  classList:{toggle(value,on){if(on)classes.add(value);else classes.delete(value);},contains(value){return classes.has(value);}},
  setAttribute(key,value){this.attrs[key]=value;},focus(){this.focused=true;document.activeElement=this;},
  matches(selector){return selector.split(',').some(part=>{part=part.trim();if(part.endsWith(':not(:disabled)')){if(this.disabled)return false;part=part.replace(/:not\(:disabled\)$/,'');}if(part===tag)return true;const match=part.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);return !!match&&match[1] in attrs&&(match[2]===undefined||attrs[match[1]]===match[2]);});},
  closest(selector){return this.matches(selector)?this:null;},
 };
}
function contentNode(){
 const root={elements:[],html:'',querySelector(selector){return this.elements.find(el=>el.matches(selector))||null;}};
 Object.defineProperty(root,'innerHTML',{get(){return this.html;},set(html){
  this.html=html;this.elements=[];
  const tokens=html.matchAll(/<(button|input|select|label|option)\b([^>]*)>/g);let select=null;
  for(const [,tag,raw] of tokens){const attrs={};for(const [,key,value] of raw.matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[key]=decode(value??'');
   const el=element(tag,attrs);if(tag==='select'){select=el;select.hasOption=false;}
   if(tag==='option'&&select&&!select.hasOption){select.value=el.value;select.hasOption=true;}
   this.elements.push(el);
  }
 }});return root;
}
function dialog(prefix){
 const content=contentNode(),status=element('p'),close=element('button',{[prefix+'-close']:''});
 return {...element('dialog'),open:false,content,status,closeButton:close,
  querySelector(selector){if(selector==='['+prefix+'-content]')return content;if(selector==='['+prefix+'-status]')return status;return this.querySelectorAll(selector)[0]||null;},
  querySelectorAll(selector){return [close,...content.elements].filter(el=>el.matches(selector));},
  showModal(){this.open=true;},close(){this.open=false;},
 };
}
const shopping=dialog('data-meal-shopping'),lists=dialog('data-meal-shopping-lists');
const document={activeElement:null,getElementById(id){return {mealPlanShoppingDialog:shopping,mealPlanShoppingListsDialog:lists}[id]||null;}};
const calls=[],navigations=[];let respond=async()=>{throw new Error('Unexpected request');};
const window={withCanonicalViewerUserId:url=>{const parsed=new URL(url,'https://example.test');parsed.searchParams.set('viewer_user_id','account-1');return parsed.pathname+parsed.search+parsed.hash;},location:{assign:url=>navigations.push(url)}};
const ctx={window,document,console,AbortController,fetch:async(url,options)=>{
 const call={url,path:url.split('?')[0],options,body:options.body?JSON.parse(options.body):undefined};calls.push(call);return respond(call);
}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const UI=window.MealPlanShopping;
const flush=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
const ok=data=>({ok:true,status:200,json:async()=>({ok:true,...data})});
const fail=(error,status=500)=>({ok:false,status,json:async()=>({ok:false,error})});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const source=(kind,id,extra={})=>({id:kind+':'+id,record_id:id,kind,recipe_name:'Corn <bread>',servings:12,date_from:'2026-09-25',date_to:'2026-10-02',meal_ids:['scheduled-1','scheduled-2'],...extra});
const review=(extra={})=>({selection:{batch_ids:['batch-1'],meal_ids:['meal-1']},review_token:'review-v1',
 sources:[source('batch','batch-1'),source('meal','meal-1',{recipe_name:'Soup',servings:2})],
 items:[{id:'butter',name:'Butter <unsalted>',quantity:'1/2 cup',included:true,pantry_matches:[{name:'Butter',quantity:2,unit:'cups'}],sources:[{recipe_name:'Corn <bread>',quantity:'1/2 cup'}]},
  {id:'corn',name:'Corn',quantity:'3 cups',included:true,pantry_matches:[],sources:[]}],
 warnings:['A batch spans multiple weeks.'],can_add:true,blockers:[],lists:[{id:'current',name:'Current shopping list'},{id:'saved/1',name:'Weekend <prep>'}],...extra});
const click=(action,dialog=shopping)=>{const target=dialog.querySelector('[data-shopping-action="'+action+'"]');assert(target,'Action exists: '+action);dialog.onclick({target});};
const change=(target,dialog=shopping)=>dialog.onchange({target});
const open=async(data=review(),selection={week_start:'2026-09-21'})=>{respond=async()=>ok(data);UI.open(selection,element());await flush();};
const reviewStep=async(data=review())=>{respond=async()=>ok(data);click('review');await flush();};
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", str(SHOPPING_JS)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shopping_dialogs_have_accessible_scoped_controls_and_workspace_entry_points():
    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = []

        def handle_starttag(self, tag, attrs):
            self.elements.append((tag, dict(attrs)))

    source = (ROOT / "PushShoppingList/templates/sections/app_workspaces.html").read_text(encoding="utf-8")
    for dialog_id, prefix, close_call in [
        ("mealPlanShoppingDialog", "data-meal-shopping", "MealPlanShopping.close()"),
        ("mealPlanShoppingListsDialog", "data-meal-shopping-lists", "MealPlanShopping.closeLists()"),
    ]:
        start = source.index(f'<dialog id="{dialog_id}"')
        parser = Elements()
        parser.feed(source[start:source.index("</dialog>", start)])
        dialog = parser.elements[0][1]
        ids = {attrs["id"] for _, attrs in parser.elements if "id" in attrs}
        assert dialog["aria-labelledby"] in ids
        assert any(f"{prefix}-content" in attrs for _, attrs in parser.elements)
        status = next(attrs for _, attrs in parser.elements if f"{prefix}-status" in attrs)
        assert status["role"] == "status" and status["aria-live"] == "polite"
        close = next(attrs for _, attrs in parser.elements if f"{prefix}-close" in attrs)
        assert close["aria-label"]
        assert close["onclick"] == f"return {close_call}"
    assert 'onclick="return openMealPlanShopping()"' in source
    assert 'onclick="return MealPlanShopping.openLists()"' in source
    assert 'data-meal-shopping-saved-lists' in source


@requires_node
def test_selected_sources_are_reviewed_by_raw_record_ids_before_any_commit():
    run_shopping(r"""
await open();
assert.equal(shopping.open,true);assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/meal-plan/shopping/review');
assert.deepEqual(calls[0].body,{selection:{week_start:'2026-09-21'}});
assert(calls[0].url.endsWith('?viewer_user_id=account-1'));
assert(shopping.content.innerHTML.includes('Corn &lt;bread&gt;'));assert(!shopping.content.innerHTML.includes('Corn <bread>'));
assert.equal(shopping.querySelector('[data-shopping-action="save"]'),null);
const sources=shopping.querySelectorAll('[data-shopping-source]');assert.equal(sources.length,2);
sources[1].checked=false;
await reviewStep(review({selection:{batch_ids:['batch-1'],meal_ids:[]},sources:[source('batch','batch-1')]}));
assert.deepEqual(calls[1].body,{selection:{batch_ids:['batch-1'],meal_ids:[]}},'Prefixed display IDs must not be sent as record IDs');
assert.equal(shopping.querySelectorAll('[data-shopping-item]').length,2);assert(shopping.content.innerHTML.includes('1/2 cup'));
assert(shopping.content.innerHTML.includes('A batch spans multiple weeks.'));
assert(shopping.content.innerHTML.includes('Butter &lt;unsalted&gt;'));assert(shopping.content.innerHTML.includes('In pantry: Butter 2 cups'));
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,0);
click('back');assert.deepEqual(shopping.querySelectorAll('[data-shopping-source]').map(input=>input.checked),[true,false]);
shopping.querySelectorAll('[data-shopping-source]').forEach(input=>input.checked=false);const count=calls.length;click('review');
assert.equal(calls.length,count);assert.match(shopping.status.textContent,/Choose at least one/);
""")


@requires_node
@pytest.mark.parametrize("destination", ["current", "saved/1", "__new__"])
def test_reviewed_pantry_exclusions_and_destination_are_committed_once(destination):
    run_shopping(r"""
await open();await reviewStep();
const inputs=shopping.querySelectorAll('[data-shopping-item]');assert.deepEqual(inputs.map(input=>input.checked),[true,true],'Pantry matches remain included until explicitly excluded');
click('exclude-pantry');assert.deepEqual(inputs.map(input=>input.checked),[false,true]);
assert.equal(shopping.querySelector('[data-shopping-action="save"]').textContent,'Add 1 item to list');
const destination=shopping.querySelector('[data-shopping-destination]');destination.value=__DESTINATION__;change(destination);
const name=shopping.querySelector('[data-shopping-name]');name.value='  Family weekend  ';
assert.equal(shopping.querySelector('[data-shopping-name-field]').hidden,__DESTINATION__!=='__new__');
const pending=deferred();respond=()=>pending.promise;click('save');click('save');UI.close();
assert.equal(shopping.open,true,'A saving dialog cannot close or repeat the commit');
const commits=calls.filter(call=>call.path.endsWith('/add'));assert.equal(commits.length,1);
assert.deepEqual(commits[0].body,{selection:{batch_ids:['batch-1'],meal_ids:['meal-1']},review_token:'review-v1',excluded_item_ids:['butter'],
 ...(__DESTINATION__==='__new__'?{new_list_name:'Family weekend'}:{list_id:__DESTINATION__})});
assert(shopping.querySelectorAll('button, input, select').every(control=>control.disabled));
pending.resolve(ok({list:{id:__DESTINATION__==='__new__'?'new-id':__DESTINATION__,name:'Family weekend'}}));await flush();
assert.match(shopping.status.textContent,/saved/i);assert.equal(shopping.querySelector('[data-shopping-action="save"]'),null);
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,1);
if(__DESTINATION__==='current'){
 click('view');assert.equal(shopping.open,false);assert.equal(navigations.length,1);
 const destination=new URL(navigations[0],'https://example.test/#mealPlannerPage');
 assert.equal(destination.pathname,'/');assert.equal(destination.hash,'#shoppingListsPage');
 assert.equal(destination.searchParams.get('viewer_user_id'),'account-1');
 assert.match(destination.searchParams.get('shopping_updated'),/^\d+$/,'Changing the query forces a fresh document instead of reusing stale shopping markup');
 assert(Number(destination.searchParams.get('shopping_updated'))>0);
}
else if(__DESTINATION__==='saved/1'){
 respond=async()=>ok({list:{id:'saved/1',name:'Family weekend',items:[]}});click('view');await flush();
 assert.equal(shopping.open,false);assert.equal(lists.open,true);assert.equal(calls[calls.length-1].path,'/api/meal-plan/shopping/lists/saved%2F1');
}else {click('cancel');assert.equal(shopping.open,false);}
""".replace("__DESTINATION__", repr(destination)))


@requires_node
def test_successful_shopping_save_schedules_selected_review_sources_on_the_saved_list():
    run_shopping(r"""
const scheduled=[],opener=element();window.PlannerViews={openTrip(initial,actualOpener){
 assert.equal(shopping.open,false,'Close the shopping review before opening the trip form');
 scheduled.push({initial:plain(initial),opener:actualOpener});
}};
respond=async()=>ok(review());UI.open({week_start:'2026-09-21'},opener);await flush();
assert.equal(shopping.querySelector('[data-shopping-action="schedule"]'),null);
shopping.querySelectorAll('[data-shopping-source]')[0].checked=false;
await reviewStep(review({selection:{batch_ids:[],meal_ids:['meal-1']},sources:[source('meal','meal-1')],items:[review().items[1]]}));
const destination=shopping.querySelector('[data-shopping-destination]');destination.value='saved/1';change(destination);
respond=async()=>ok({list:{id:'saved/1',name:'Weekend list',sources:[source('batch','older-batch'),source('meal','meal-1')]}});
click('save');await flush();
assert.equal(scheduled.length,0,'Saving ingredients does not implicitly schedule a trip');
assert(shopping.querySelector('[data-shopping-action="schedule"]'));assert(shopping.querySelector('[data-shopping-action="view"]'),'Opening the list remains available');
click('schedule');
assert.equal(scheduled.length,1);assert.equal(scheduled[0].opener,opener);
assert.deepEqual(scheduled[0].initial,{list_id:'saved/1',source_ids:['meal:meal-1']},'Use the reviewed source subset, not other provenance already on the destination list');
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,1);
assert(!calls.some(call=>call.path.startsWith('/api/shopping-trips')),'Trip persistence waits for its own form confirmation');
assert.equal(navigations.length,0);
""")


@requires_node
def test_empty_selection_blank_list_name_and_blocked_review_cannot_commit():
    run_shopping(r"""
await open();await reviewStep();
const inputs=shopping.querySelectorAll('[data-shopping-item]');inputs.forEach(input=>input.checked=false);change(inputs[0]);
assert.equal(shopping.querySelector('[data-shopping-action="save"]').disabled,true);click('save');
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,0);
inputs[0].checked=true;change(inputs[0]);
const destination=shopping.querySelector('[data-shopping-destination]');destination.value='__new__';change(destination);
const name=shopping.querySelector('[data-shopping-name]');name.value='   ';click('save');
assert.equal(name.focused,true);assert.match(shopping.status.textContent,/Enter a name/);assert.equal(calls.length,2);
UI.close();await open();await reviewStep(review({blockers:['Resolve butter alternatives first.'],can_add:false}));
assert(shopping.content.innerHTML.includes('Resolve butter alternatives first.'));assert.equal(shopping.querySelector('[data-shopping-action="save"]').disabled,true);
click('save');assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,0);
""")


@requires_node
def test_load_failures_retry_and_commit_failures_keep_review_for_explicit_retry():
    run_shopping(r"""
respond=async()=>fail('Could not calculate ingredients.');UI.open({meal_ids:['meal-1']});await flush();
assert.equal(shopping.status.textContent,'Could not calculate ingredients.');assert(shopping.status.classList.contains('error'));
assert.equal(shopping.querySelector('[data-shopping-action="save"]'),null);
respond=async()=>ok(review());click('retry');await flush();await reviewStep();
shopping.querySelectorAll('[data-shopping-item]')[0].checked=false;
respond=async()=>fail('List could not be saved.');click('save');await flush();
assert.equal(shopping.status.textContent,'List could not be saved.');assert.deepEqual(shopping.querySelectorAll('[data-shopping-item]').map(input=>input.checked),[false,true]);
assert.equal(shopping.querySelector('[data-shopping-action="save"]').disabled,false);
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,1,'Server failure must not silently retry');
respond=async()=>ok({list:{id:'current',name:'Current shopping list'}});click('save');await flush();
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,2);assert.match(shopping.status.textContent,/saved/i);
""")


@requires_node
def test_plan_changed_requires_a_new_review_token_before_retrying_commit():
    run_shopping(r"""
await open();await reviewStep();respond=async()=>fail('Plan changed',409);click('save');await flush();
assert.match(shopping.status.textContent,/review the ingredients/i);
assert.equal(shopping.querySelector('[data-shopping-action="save"]'),null);
const updated=review({selection:{batch_ids:[],meal_ids:['meal-1']},sources:[source('meal','meal-1',{recipe_name:'Only remaining meal'})],review_token:'review-v2',items:[review().items[1]]});
respond=async()=>ok(updated);click('retry');await flush();
assert.deepEqual(calls[calls.length-1].body,{selection:{week_start:'2026-09-21'}},'Refresh the initial scope to discover removed meals');
assert.equal(shopping.querySelectorAll('[data-shopping-source]').length,1);assert(shopping.content.innerHTML.includes('Only remaining meal'));
assert.equal(shopping.querySelector('[data-shopping-action="save"]'),null);
await reviewStep(updated);
respond=async()=>ok({list:{id:'current',name:'Current shopping list'}});click('save');await flush();
const commits=calls.filter(call=>call.path.endsWith('/add'));
assert.equal(commits.length,2);assert.equal(commits[0].body.review_token,'review-v1');assert.equal(commits[1].body.review_token,'review-v2');
assert.deepEqual(commits[1].body.excluded_item_ids,[]);
""")


@requires_node
def test_closing_or_reopening_aborts_load_and_ignores_stale_success_and_failure():
    run_shopping(r"""
const first=deferred(),second=deferred();let index=0;respond=()=>[first.promise,second.promise][index++];
const oldOpener=element(),newOpener=element();UI.open({batch_ids:['old']},oldOpener);const oldRequest=calls[0];
UI.open({batch_ids:['new']},newOpener);assert.equal(oldRequest.options.signal.aborted,true);
second.resolve(ok(review({sources:[source('batch','new',{recipe_name:'Newest recipe'})]})));await flush();
assert(shopping.content.innerHTML.includes('Newest recipe'));
first.resolve(ok(review({sources:[source('batch','old',{recipe_name:'Old recipe'})]})));await flush();
assert(!shopping.content.innerHTML.includes('Old recipe'));assert(shopping.content.innerHTML.includes('Newest recipe'));
const final=deferred();respond=()=>final.promise;click('review');const active=calls[calls.length-1];
let prevented=false;shopping.oncancel({preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(shopping.open,false);assert.equal(active.options.signal.aborted,true);assert.equal(newOpener.focused,true);
final.resolve(fail('Old failure'));await flush();assert.notEqual(shopping.status.textContent,'Old failure');
assert.equal(shopping.open,false);assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,0);
""")


@requires_node
def test_saved_lists_open_and_check_items_without_readding_shopping_quantities():
    run_shopping(r"""
const record={id:'saved/1',name:'Weekend <prep>',items:[{id:'item/1',name:'Corn',quantity:'3 cups',checked:false},{id:'butter',name:'Butter',quantity:'1/2 cup',checked:true}]};
respond=async call=>call.path.endsWith('/lists')?ok({lists:[{id:'current',name:'Current shopping list'},{id:'saved/1',name:'Weekend <prep>',item_count:2}]}):ok({list:record});
const opener=element();await UI.openLists('',opener);
assert.equal(lists.open,true);assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].body,undefined);
assert(!lists.content.innerHTML.includes('Current shopping list'));assert(lists.content.innerHTML.includes('Weekend &lt;prep&gt;'));
lists.onclick({target:lists.querySelector('[data-shopping-list-id]')});await flush();
assert.equal(calls[1].path,'/api/meal-plan/shopping/lists/saved%2F1');
let inputs=lists.querySelectorAll('[data-shopping-checked]');assert.deepEqual(inputs.map(input=>input.checked),[false,true]);
const pending=deferred();respond=()=>pending.promise;inputs[0].checked=true;
const first=change(inputs[0],lists);await change(inputs[0],lists);UI.closeLists();
assert.equal(lists.open,true,'A checked-item save remains attached to its list until it finishes');
assert(lists.querySelectorAll('button, input').every(control=>control.disabled));
const writes=calls.filter(call=>call.options.method==='PATCH');assert.equal(writes.length,1);
assert.equal(writes[0].path,'/api/meal-plan/shopping/lists/saved%2F1/items/item%2F1');assert.deepEqual(writes[0].body,{checked:true});
pending.resolve(ok({item:{id:'item/1',checked:true}}));await first;
assert.equal(inputs[0].checked,true);assert.equal(inputs[0].disabled,false);assert.equal(lists.status.textContent,'Saved.');
respond=async()=>ok({list:{...record,items:[{...record.items[0],checked:true},record.items[1]]}});
UI.closeLists();assert.equal(opener.focused,true);await UI.openLists('saved/1');
assert.deepEqual(lists.querySelectorAll('[data-shopping-checked]').map(input=>input.checked),[true,true]);
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,0,'Checking an existing list does not regenerate or append ingredients');
""")


@requires_node
def test_failed_saved_list_check_reverts_to_last_saved_state_and_retry_succeeds():
    run_shopping(r"""
respond=async()=>ok({list:{id:'saved-1',name:'Weekend',items:[{id:'item-1',name:'Corn',quantity:'3 cups',checked:true}]}});
await UI.openLists('saved-1');const input=lists.querySelector('[data-shopping-checked]');
respond=async()=>fail('Unable to update this item.');input.checked=false;await change(input,lists);
assert.equal(input.checked,true);assert.equal(input.disabled,false);assert.equal(lists.status.textContent,'Unable to update this item.');
assert(lists.status.classList.contains('error'));
respond=async()=>ok({item:{id:'item-1',checked:false}});input.checked=false;await change(input,lists);
assert.equal(input.checked,false);assert.equal(lists.status.textContent,'Saved.');assert(!lists.status.classList.contains('error'));
assert.deepEqual(calls.filter(call=>call.options.method==='PATCH').map(call=>call.body),[{checked:false},{checked:false}]);
""")


@requires_node
def test_saved_list_loading_can_retry_and_old_list_response_cannot_replace_newer_list():
    run_shopping(r"""
respond=async()=>fail('Saved list unavailable.');await UI.openLists('saved/1');
assert.equal(lists.status.textContent,'Saved list unavailable.');
respond=async()=>ok({list:{id:'saved/1',name:'Recovered',items:[]}});
lists.onclick({target:lists.querySelector('[data-shopping-list-retry]')});await flush();
assert.equal(calls[calls.length-1].path,'/api/meal-plan/shopping/lists/saved%2F1');assert(lists.content.innerHTML.includes('Recovered'));
const old=deferred(),fresh=deferred();let index=0;respond=()=>[old.promise,fresh.promise][index++];
const oldLoad=UI.openLists('old-list'),oldCall=calls[calls.length-1];
const newLoad=UI.openLists('new-list');assert.equal(oldCall.options.signal.aborted,true);
fresh.resolve(ok({list:{id:'new-list',name:'Newest list',items:[]}}));await newLoad;
old.resolve(ok({list:{id:'old-list',name:'Stale list',items:[]}}));await oldLoad;
assert(lists.content.innerHTML.includes('Newest list'));assert(!lists.content.innerHTML.includes('Stale list'));
UI.closeLists();assert.equal(lists.open,false);
""")


@requires_node
def test_source_errors_are_visible_and_escaped_before_selecting_meals():
    run_shopping(r"""
await open(review({sources:[source('batch','batch-1',{recipe_name:'Bread <script>',error:'Resolve <img src=x onerror=alert(1)> choices & retry.'})],items:[],can_add:false}));
assert(shopping.content.innerHTML.includes('Bread &lt;script&gt;'));
assert(shopping.content.innerHTML.includes('Resolve &lt;img src=x onerror=alert(1)&gt; choices &amp; retry.'));
assert(!shopping.content.innerHTML.includes('<img'));assert(!shopping.content.innerHTML.includes('<script>'));
assert.equal(shopping.querySelectorAll('[data-shopping-source]').length,1,'The blocked source remains visible so the user can deselect or fix it');
assert.equal(calls.filter(call=>call.path.endsWith('/add')).length,0);
""")


@requires_node
def test_planned_quantity_sources_are_read_only_while_regular_recipe_sources_remain_editable():
    run_shopping(r"""
function createNode(tag){
 const node=element(tag);node.children=[];node.handlers={};node.classList.add=()=>{};
 node.append=(...children)=>node.children.push(...children);node.appendChild=child=>node.children.push(child);
 node.replaceChildren=(...children)=>{node.children=children;};
 node.addEventListener=(event,handler)=>{node.handlers[event]=handler;};
 Object.defineProperty(node,'innerHTML',{set(){throw new Error('Quantity sources must use text nodes for recipe labels');}});
 return node;
}
document.createElement=createNode;
const saves=[],editorLinks=[];
ctx.openRecipeEditorFromItemQtySource=(url,ingredient)=>editorLinks.push({url,ingredient});
ctx.saveItemModalDefaultQuantity=(quantity,unit)=>saves.push({kind:'default',quantity:quantity.value,unit:unit.value});
ctx.saveItemModalRecipeQuantity=select=>saves.push({kind:'scale',value:select.value});
ctx.parseRecipeScaleMultiplier=value=>Number(value);
ctx.populateItemQtyScalingOptions=(select,options,value)=>{select.value=String(value);};
const app=fs.readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]),'app.js'),'utf8');
vm.runInContext(app.slice(app.indexOf('function renderItemQtySources('),app.indexOf('function populateItemQtyScalingOptions(')),ctx);
const container=createNode('div'),planned={meal_plan_source_id:'batch:batch-1',label:'Prep <bread>',url:'recipe://bread',ingredient:'Corn',quantity:'6 cups'},
 regular={label:'Soup',url:'recipe://soup',ingredient:'Corn',quantity:'2 cups',default_quantity_value:'1',default_unit:'cup',recipe_quantity:2,recipe_number:'recipe-2'};
ctx.renderItemQtySources(container,JSON.stringify([planned,regular]),'corn-key');
assert.equal(container.hidden,false);assert.equal(container.children.length,3);
const plannedRow=container.children[1],regularRow=container.children[2];
const descendants=node=>node.children.flatMap(child=>[child,...descendants(child)]);
assert.equal(descendants(plannedRow).filter(node=>['input','select','button','a'].includes(node.tag)).length,0,'A planned contribution cannot edit or rescale its saved recipe');
assert.deepEqual(plannedRow.children.map(node=>node.textContent),['Prep <bread>','Planned quantity','6 cups']);
const editable=descendants(regularRow),inputs=editable.filter(node=>node.tag==='input'),select=editable.find(node=>node.tag==='select'),link=editable.find(node=>node.tag==='button');
assert.equal(inputs.length,2);assert(select);assert(link);assert.equal(inputs[0].dataset.itemKey,'corn-key');
assert.equal(select.dataset.recipeUrl,'recipe://soup');assert.equal(select.dataset.recipeNumber,'recipe-2');
link.handlers.click();assert.deepEqual(editorLinks,[{url:'recipe://soup',ingredient:'Corn'}]);
inputs[0].value='1.5';inputs[0].handlers.change();select.value='3';select.handlers.change();
assert.deepEqual(saves,[{kind:'default',quantity:'1.5',unit:'cup'},{kind:'scale',value:'3'}]);
ctx.renderItemQtySources(container,JSON.stringify([planned]),'corn-key');
assert.equal(descendants(container).some(node=>['input','select','button','a'].includes(node.tag)),false,'Reopening only planned sources removes prior editable controls');
ctx.renderItemQtySources(container,'invalid json','corn-key');assert.equal(container.hidden,true);assert.equal(container.children.length,0);
""")
