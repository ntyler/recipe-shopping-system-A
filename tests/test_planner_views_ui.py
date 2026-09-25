"""Planner view and shopping-trip behavior at a mocked DOM boundary.

The production scripts are executed; no browser layout verification is claimed.
"""

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "PushShoppingList/static/js/planner-views.js"
requires_node = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for interaction checks")


def run_planner(script):
    bootstrap = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const plain=value=>JSON.parse(JSON.stringify(value));
const decode=value=>String(value??'').replace(/&(?:amp|lt|gt|quot|#39);/g,value=>({'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"}[value]));
const camel=value=>value.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
const events=()=>({listeners:{},addEventListener(type,handler){(this.listeners[type] ||= []).push(handler);},
 dispatch(type,event={}){for(const handler of this.listeners[type]||[])handler(event);}});
function element(tag='button',attrs={}) {
 const classes=new Set();
 const el={...events(),tag,attrs,dataset:Object.fromEntries(Object.entries(attrs).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[camel(key.slice(5)),value])),
  checked:'checked' in attrs,disabled:'disabled' in attrs,hidden:'hidden' in attrs,value:attrs.value||'',textContent:'',focused:false,
  classList:{toggle(value,on){if(on)classes.add(value);else classes.delete(value);},add(value){classes.add(value);},remove(value){classes.delete(value);},contains(value){return classes.has(value);}},
  setAttribute(key,value){this.attrs[key]=String(value);if(key.startsWith('data-'))this.dataset[camel(key.slice(5))]=String(value);},getAttribute(key){return this.attrs[key]??null;},removeAttribute(key){delete this.attrs[key];},
  focus(){this.focused=true;document.activeElement=this;},reportValidity(){return true;},
  matches(selector){return selector.split(',').some(part=>{part=part.trim();if(part.endsWith(':not(:disabled)')){if(this.disabled)return false;part=part.replace(/:not\(:disabled\)$/,'');}if(part===tag)return true;if(part.startsWith('#'))return attrs.id===part.slice(1);const match=part.match(/^\[([^=\]]+)(?:=["']([^"']*)["'])?\]$/);return !!match&&match[1] in attrs&&(match[2]===undefined||attrs[match[1]]===match[2]);});},
  closest(selector){return this.matches(selector)?this:null;},
 };
 Object.defineProperty(el,'href',{get(){return new URL(attrs.href||'',location.href).href;},set(value){attrs.href=value;}});
 return el;
}
function contentNode(tag='div',attrs={}){
 const root={...element(tag,attrs),elements:[],html:'',descendants(){return this.elements.flatMap(el=>[el,...(el.descendants?.()||[])]);},querySelector(selector){return this.querySelectorAll(selector)[0]||null;},querySelectorAll(selector){return this.descendants().filter(el=>el.matches(selector));}};
 Object.defineProperty(root,'innerHTML',{get(){return this.html;},set(html){
  this.html=html;this.elements=[];
  const tokens=html.matchAll(/<(button|input|select|label|option|div|article|p|a|form)\b([^>]*)>/g);let select=null;
  for(const [,tag,raw] of tokens){const attrs={};for(const [,key,value] of raw.matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[key]=decode(value??'');
   const el='data-trip-sources' in attrs?contentNode(tag,attrs):element(tag,attrs);if(tag==='select'){select=el;select.hasOption=false;}
   if(tag==='option'&&select&&(!select.hasOption||'selected' in attrs)){select.value=el.value;select.hasOption=true;}
   this.elements.push(el);
  }
 }});return root;
}
const location=new URL('https://example.test/?meal_week=2026-09-21&planner_view=meals&viewer_user_id=account-1#mealPlannerPage');
const historyCalls=[],navigations=[];
const history={state:null,replaceState(state,title,url){historyCalls.push(String(url));location.href=new URL(url,location.href).href;},pushState(state,title,url){this.replaceState(state,title,url);}};
const tabs=['meals','prep','shopping'].map(view=>element('button',{'data-planner-view':view}));
const panels=['meals','prep','shopping'].map(view=>contentNode('div',{'data-planner-panel':view}));
const links=['2026-09-14','2026-09-28','2026-09-21'].map(date=>element('a',{'data-planner-week-link':'',href:'?meal_week='+date+'#mealPlannerPage'}));
const title=element('h2',{'data-planner-title':''}),description=element('p',{'data-planner-description':''}),addMeal=element('button',{'data-planner-add-meal':''}),addTrip=element('button',{'data-planner-add-trip':''});
const page={...element('section',{'data-meal-week':'2026-09-21'}),
 querySelectorAll(selector){return [...tabs,...panels,...links,title,description,addMeal,addTrip,...panels.flatMap(panel=>panel.elements)].filter(el=>el.matches(selector));},
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;},
 contains(target){return this.querySelectorAll('button, input, a').includes(target);}
};
const tripContent=contentNode(),tripStatus=element('p'),tripTitle=element('h3'),tripClose=element('button',{'data-trip-close':''});
const trip={...element('dialog'),open:false,
 querySelector(selector){if(selector==='[data-trip-content]')return tripContent;if(selector==='[data-trip-status]')return tripStatus;if(selector==='#shoppingTripDialogTitle')return tripTitle;return this.querySelectorAll(selector)[0]||null;},
 querySelectorAll(selector){return [tripClose,...tripContent.descendants()].filter(el=>el.matches(selector));},showModal(){this.open=true;},close(){this.open=false;},
};
const document={...events(),readyState:'loading',activeElement:null,getElementById(id){return {mealPlannerPage:page,shoppingTripDialog:trip,shoppingTripDialogTitle:tripTitle}[id]||null;},
 querySelector(selector){return selector==='#mealPlannerPage'?page:page.querySelector(selector);},createElement:element};
const calls=[],openedLists=[],editedPrep=[],shoppingBatches=[],prepCompletions=[],workspaceRefreshes=[];let respond=async()=>{throw new Error('Unexpected request');};
const window={...events(),document,location,history,withCanonicalViewerUserId:url=>{const parsed=new URL(url,location.href);parsed.searchParams.set('viewer_user_id','account-1');return parsed.pathname+parsed.search+parsed.hash;},
 MealPlanShopping:{openList(id,opener){openedLists.push({id,opener});}},
 openMealPlannerEditDialog(trigger,scope){editedPrep.push({dataset:plain(trigger.dataset),scope});},
 openMealPlanShopping(id,opener){shoppingBatches.push({id,opener});},
 async toggleMealPlannerPrepStep(input){prepCompletions.push({batch:input.dataset.batchId,step:input.dataset.stepId,checked:input.checked});},
 async refreshMealPlannerWorkspace({date}){assert.equal(trip.open,false,'Close a committed trip before refreshing its workspace');workspaceRefreshes.push(date);return true;}
};
const ctx={window,document,location,history,console,URL,AbortController,fetch:async(url,options={})=>{const parsed=new URL(url,location.href);const call={url:String(url),path:parsed.pathname,params:parsed.searchParams,options,body:options.body?JSON.parse(options.body):undefined};calls.push(call);return respond(call);}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const UI=window.PlannerViews;
const flush=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
const ok=data=>({ok:true,status:200,json:async()=>({ok:true,...data})});
const fail=(error,status=500)=>({ok:false,status,json:async()=>({ok:false,error})});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const source=(id='batch:batch-1',name='Corn <bread>')=>({id,kind:id.split(':')[0],record_id:id.split(':')[1],recipe_name:name,recipe_url:'recipe://bread',servings:12,meal_ids:['meal-1'],date_from:'2026-09-25',date_to:'2026-10-02'});
const savedTrip=(extra={})=>({id:'trip/1',date:'2026-09-25',list_id:'saved/1',list_name:'Weekend <prep>',is_current:false,list_available:true,
 store_key:'store/1',store_label:'Store <north>',status:'planned',source_ids:['batch:batch-1'],sources:[source()],...extra});
const options=()=>({lists:[{id:'current',name:'Current shopping list',is_current:true,sources:[]},{id:'saved/1',name:'Weekend <prep>',is_current:false,sources:[source(),source('meal:meal-2','Soup')]},
 {id:'saved-2',name:'Other list',is_current:false,sources:[source('meal:meal-3','Salad')]}],
 stores:[{key:'store/1',label:'Store <north>'},{key:'store-2',label:'Store south'}],statuses:[{value:'planned',label:'Planned'},{value:'in_progress',label:'In progress'},{value:'completed',label:'Completed'}]});
const week=(extra={})=>({week_start:'2026-09-21',week_end:'2026-09-27',days:[{date:'2026-09-25',weekday:'Fri',day_label:'9/25',is_today:true},{date:'2026-09-26',weekday:'Sat',day_label:'9/26'}],
 prep_steps_by_day:{'2026-09-25':[{id:'step/1',batch_id:'batch-1',meal_id:'meal-1',date:'2026-09-25',recipe_name:'Corn <bread>',recipe_url:'recipe://bread',instruction:'Chop <onions>',completed:false}]},
 unscheduled_prep_batches:[{id:'unscheduled-1',batch_id:'unscheduled-1',meal_id:'meal-2',recipe_name:'Soup',batch_servings:8,allocations:[]}],
 shopping_trips_by_day:{'2026-09-25':[savedTrip()]},...extra});
respond=async call=>call.path==='/api/planning/week'?ok(week()):call.path==='/api/shopping-trips/options'?ok(options()):ok({trip:savedTrip()});
const clickTrip=action=>{const target=trip.querySelector('[data-trip-action="'+action+'"]');assert(target,'Trip action exists: '+action);trip.onclick({target,preventDefault(){}});};
const clickPanel=(view,action)=>{const panel=panels.find(panel=>panel.dataset.plannerPanel===view),target=panel.querySelector('[data-planner-action="'+action+'"]');assert(target,'Planner action exists: '+action);panel.onclick({target,preventDefault(){}});return target;};
const field=name=>trip.querySelector('[name="'+name+'"]');
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", str(SCRIPT)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_planner_tabs_panels_week_navigation_and_trip_dialog_contract():
    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = []

        def handle_starttag(self, tag, attrs):
            self.elements.append((tag, dict(attrs)))

    source = (ROOT / "PushShoppingList/templates/sections/app_workspaces.html").read_text(encoding="utf-8")
    parser = Elements()
    parser.feed(source)
    tabs = [attrs for _, attrs in parser.elements if "data-planner-view" in attrs]
    panels = [attrs for _, attrs in parser.elements if "data-planner-panel" in attrs]
    assert [tab["data-planner-view"] for tab in tabs] == ["meals", "prep", "shopping"]
    assert len(panels) == 3
    for tab in tabs:
        panel = next(panel for panel in panels if panel["data-planner-panel"] == tab["data-planner-view"])
        assert tab["role"] == "tab" and panel["role"] == "tabpanel"
        assert tab["aria-controls"] == panel["id"]
        assert panel["aria-labelledby"] == tab["id"]
    links = [attrs for tag, attrs in parser.elements if "data-planner-week-link" in attrs]
    assert len(links) == 3
    assert all("meal_week=" in link["href"] and link["href"].endswith("#mealPlannerPage") for link in links)
    dialog = next(attrs for tag, attrs in parser.elements if tag == "dialog" and attrs.get("id") == "shoppingTripDialog")
    assert any(attrs.get("id") == dialog["aria-labelledby"] for _, attrs in parser.elements)
    assert any("data-trip-content" in attrs for _, attrs in parser.elements)
    status = next(attrs for _, attrs in parser.elements if "data-trip-status" in attrs)
    assert status["role"] == "status" and status["aria-live"] == "polite"
    close = next(attrs for _, attrs in parser.elements if "data-trip-close" in attrs)
    assert close["aria-label"] and close["onclick"] == "return PlannerViews.closeTrip()"


@requires_node
def test_view_selection_and_keyboard_navigation_preserve_week_and_user_context():
    run_planner(r"""
document.dispatch('DOMContentLoaded');assert.equal(title.textContent,'Meal Planner');assert.equal(calls.length,0);
UI.select('shopping');await flush();
assert.equal(title.textContent,'Shopping Planner');assert.equal(addMeal.hidden,true);assert.equal(addTrip.hidden,false);
assert.deepEqual(panels.map(panel=>panel.hidden),[true,true,false]);
assert.deepEqual(tabs.map(tab=>tab.attrs['aria-selected']),['false','false','true']);assert.deepEqual(tabs.map(tab=>tab.tabIndex),[-1,-1,0]);
assert.equal(location.searchParams.get('planner_view'),'shopping');assert.equal(location.searchParams.get('meal_week'),'2026-09-21');
assert.equal(location.searchParams.get('viewer_user_id'),'account-1');assert.equal(location.hash,'#mealPlannerPage');
assert.deepEqual(links.map(link=>new URL(link.href).searchParams.get('meal_week')),['2026-09-14','2026-09-28','2026-09-21']);
for(const link of links){const url=new URL(link.href);assert.equal(url.searchParams.get('planner_view'),'shopping');assert.equal(url.searchParams.get('viewer_user_id'),'account-1');}
assert.equal(calls[0].path,'/api/planning/week');assert.equal(calls[0].params.get('week_start'),'2026-09-21');assert.equal(calls[0].params.get('viewer_user_id'),'account-1');
let prevented=false;tabs[2].onkeydown({key:'ArrowLeft',preventDefault(){prevented=true;}});await flush();
assert.equal(prevented,true);assert.equal(tabs[1].focused,true);assert.equal(title.textContent,'Meal Prep Planner');
tabs[1].onkeydown({key:'Home',preventDefault(){}});assert.equal(tabs[0].focused,true);assert.equal(title.textContent,'Meal Planner');
const count=calls.length;UI.select('invalid');assert.equal(title.textContent,'Meal Planner');assert.equal(calls.length,count);
location.searchParams.set('planner_view','prep');UI.init(page);await flush();assert.equal(title.textContent,'Meal Prep Planner','A restored URL selects its saved view');
""")


@requires_node
def test_prep_and_shopping_cards_escape_text_and_route_to_existing_features():
    run_planner(r"""
UI.init();UI.select('prep');await flush();const prep=panels[1];
assert(prep.innerHTML.includes('Corn &lt;bread&gt;'));assert(prep.innerHTML.includes('Chop &lt;onions&gt;'));assert(!prep.innerHTML.includes('<onions>'));
assert(prep.innerHTML.includes('Needs a prep date'));assert(prep.innerHTML.includes('8 prepared servings'));
const edit=clickPanel('prep','edit-prep');assert.deepEqual(editedPrep,[{dataset:plain(edit.dataset),scope:'batch'}]);
clickPanel('prep','shop-batch');assert.equal(shoppingBatches[0].id,'unscheduled-1');
const checkbox=prep.querySelector('[data-step-id]');checkbox.checked=true;await checkbox.onchange();
assert.deepEqual(prepCompletions,[{batch:'batch-1',step:'step/1',checked:true}]);assert.equal(page.dataset.mealPlannerStale,'1');
respond=async()=>ok(week({shopping_trips_by_day:{'2026-09-25':[savedTrip(),savedTrip({id:'current-trip',list_id:'current',list_name:'Current list'}),savedTrip({id:'gone',list_id:'missing',list_name:'Deleted list',list_available:false})]}}));
UI.select('shopping');await flush();const shopping=panels[2];
assert(shopping.innerHTML.includes('Weekend &lt;prep&gt;'));assert(shopping.innerHTML.includes('Store &lt;north&gt;'));assert(shopping.innerHTML.includes('Linked list is unavailable.'));
const openers=shopping.querySelectorAll('[data-planner-action="open-list"]');
openers.forEach(target=>shopping.onclick({target}));assert.deepEqual(openedLists.map(entry=>entry.id),['saved/1','current']);assert.equal(openedLists[0].opener,openers[0]);
assert.equal(calls.filter(call=>call.options.method!=='GET').length,0);
""")


@requires_node
def test_trip_card_add_edit_and_remove_actions_use_the_selected_date_and_trip_identity():
    run_planner(r"""
UI.init();UI.select('shopping');await flush();
const add=clickPanel('shopping','add-trip');await flush();
assert.equal(field('date').value,'2026-09-25');assert.equal(field('list_id').value,'current');
assert(trip.querySelector('[data-trip-sources]').innerHTML.includes('live Current shopping list'));
assert.equal(trip.querySelectorAll('[data-trip-source]').length,0);UI.closeTrip();assert.equal(add.focused,true);
const edit=clickPanel('shopping','edit-trip');await flush();
assert.equal(tripTitle.textContent,'Edit shopping trip');assert.equal(field('list_id').value,'saved/1');
assert(calls.some(call=>call.path==='/api/shopping-trips/trip%2F1'));UI.closeTrip();assert.equal(edit.focused,true);
const before=calls.length,remove=clickPanel('shopping','delete-trip');await flush();
assert.equal(tripTitle.textContent,'Remove shopping trip');assert.equal(trip.querySelector('[data-trip-form]'),null);
assert.equal(calls.length,before+1,'Removal refreshes the target trip, without unnecessarily loading form options');
assert.equal(calls[calls.length-1].path,'/api/shopping-trips/trip%2F1');
clickTrip('back');assert.equal(trip.open,false);assert.equal(remove.focused,true);assert.equal(calls.filter(call=>call.options.method!=='GET').length,0);
""")


@requires_node
def test_week_load_races_and_errors_do_not_replace_the_selected_view():
    run_planner(r"""
UI.init();const older=deferred(),newer=deferred();let index=0;respond=()=>[older.promise,newer.promise][index++];
UI.select('prep');const oldCall=calls[0];UI.select('shopping');assert.equal(oldCall.options.signal.aborted,true);
newer.resolve(ok(week()));await flush();const rendered=panels[2].innerHTML;
older.resolve(fail('Stale <error>'));await flush();assert.equal(panels[2].innerHTML,rendered);assert(!panels[2].innerHTML.includes('Stale'));
respond=async()=>fail('Unable to load <trips>.');await UI.refresh();
assert(panels[2].innerHTML.includes('Unable to load &lt;trips&gt;.'));assert.equal(panels[2].attrs['aria-busy'],undefined);
respond=async()=>ok(week());clickPanel('shopping','retry');await flush();assert(panels[2].innerHTML.includes('shopping trips this week'));
const pending=deferred();respond=()=>pending.promise;const refresh=UI.refresh();const pendingCall=calls[calls.length-1];UI.select('meals');
assert.equal(pendingCall.options.signal.aborted,true);pending.resolve(ok(week()));await refresh;assert.equal(panels[0].hidden,false);assert.equal(panels[2].hidden,true);
""")


@requires_node
def test_new_trip_payload_preserves_selected_coverage_and_cannot_submit_twice():
    run_planner(r"""
UI.init();const opener=element();await UI.openTrip({date:'2026-09-26',list_id:'saved/1',source_ids:['meal:meal-2']},opener);
assert.equal(trip.open,true);assert.equal(field('date').value,'2026-09-26');assert.equal(field('list_id').value,'saved/1');
assert.deepEqual(trip.querySelectorAll('[data-trip-source]').map(input=>[input.value,input.checked]),[['batch:batch-1',false],['meal:meal-2',true]]);
assert(tripContent.innerHTML.includes('Weekend &lt;prep&gt;'));assert(tripContent.innerHTML.includes('Store &lt;north&gt;'));
field('store_key').value='store/1';field('status').value='in_progress';field('date').value='2026-10-03';
const pending=deferred();respond=()=>pending.promise;clickTrip('save');clickTrip('save');UI.closeTrip();await UI.openTrip({date:'2026-10-04'});
assert.equal(trip.open,true);assert(trip.querySelectorAll('input,select,button').every(control=>control.disabled));
const writes=calls.filter(call=>call.options.method==='POST');assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/shopping-trips');
assert.deepEqual(writes[0].body,{date:'2026-10-03',list_id:'saved/1',store_key:'store/1',status:'in_progress',source_ids:['meal:meal-2']});
assert.equal(writes[0].params.get('viewer_user_id'),'account-1');
pending.resolve(ok({trip:savedTrip({date:'2026-10-03'})}));await flush();
assert.equal(trip.open,false);assert.equal(opener.focused,true);assert.deepEqual(workspaceRefreshes,['2026-10-03']);assert.equal(title.textContent,'Shopping Planner');
assert.equal(calls.filter(call=>call.options.method==='POST').length,1);
""")


@requires_node
def test_existing_trip_hydrates_fresh_data_and_list_change_resets_coverage_before_patch():
    run_planner(r"""
UI.init();const retired=source('batch:retired','Older prep');respond=async call=>call.path.endsWith('/options')?ok(options()):ok({trip:savedTrip({source_ids:['batch:retired'],sources:[retired]})});
await UI.openTrip({id:'trip/1'});
assert(calls.some(call=>call.path==='/api/shopping-trips/trip%2F1'&&call.options.method==='GET'));
assert.equal(field('store_key').value,'store/1');assert.equal(field('date').value,'2026-09-25');
assert.deepEqual(trip.querySelectorAll('[data-trip-source]').filter(input=>input.checked).map(input=>input.value),['batch:retired'],'Verified historical coverage remains editable on its original list');
field('list_id').value='saved-2';trip.onchange({target:field('list_id')});
assert.deepEqual(trip.querySelectorAll('[data-trip-source]').map(input=>[input.value,input.checked]),[['meal:meal-3',true]]);
field('status').value='completed';respond=async()=>ok({trip:savedTrip({list_id:'saved-2',status:'completed'})});clickTrip('save');await flush();
const patch=calls.find(call=>call.options.method==='PATCH');assert.equal(patch.path,'/api/shopping-trips/trip%2F1');
assert.deepEqual(patch.body,{date:'2026-09-25',store_key:'store/1',list_id:'saved-2',status:'completed',source_ids:['meal:meal-3']});
assert.equal(calls.filter(call=>call.options.method==='POST').length,0);
""")


@requires_node
def test_trip_load_validation_and_save_errors_require_explicit_retry_without_losing_fields():
    run_planner(r"""
UI.init();respond=async()=>fail('Options unavailable.');await UI.openTrip({date:'2026-09-26'});
assert.equal(tripStatus.textContent,'Options unavailable.');assert(tripStatus.classList.contains('error'));
assert.equal(trip.querySelector('[data-trip-action="save"]'),null);
respond=async()=>ok(options());clickTrip('retry');await flush();
const form=trip.querySelector('[data-trip-form]');form.reportValidity=()=>false;clickTrip('save');assert.equal(calls.filter(call=>call.options.method==='POST').length,0);
form.reportValidity=()=>true;field('list_id').value='saved/1';trip.onchange({target:field('list_id')});field('date').value='2026-09-27';
trip.querySelectorAll('[data-trip-source]')[0].checked=false;
respond=async()=>fail('Could not save this trip.');clickTrip('save');await flush();
assert.equal(tripStatus.textContent,'Could not save this trip.');assert.equal(field('date').value,'2026-09-27');
assert.deepEqual(trip.querySelectorAll('[data-trip-source]').map(input=>input.checked),[false,true]);
assert.equal(trip.querySelector('[data-trip-action="save"]').disabled,false);assert.equal(calls.filter(call=>call.options.method==='POST').length,1);
respond=async()=>ok({trip:savedTrip({date:'2026-09-27'})});clickTrip('save');await flush();assert.equal(trip.open,false);
assert.equal(calls.filter(call=>call.options.method==='POST').length,2);
""")


@requires_node
def test_remove_trip_requires_confirmation_and_deletes_only_the_trip():
    run_planner(r"""
UI.init();const opener=element();await UI.openTrip({id:'trip/1',remove:true},opener);
assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/shopping-trips/trip%2F1');
assert(tripContent.innerHTML.includes('Weekend &lt;prep&gt;'));assert(tripContent.innerHTML.includes('shopping list, meals, and prep batches will be kept'));
assert.equal(calls.filter(call=>call.options.method==='DELETE').length,0);clickTrip('back');assert.equal(trip.open,false);assert.equal(opener.focused,true);
await UI.openTrip({id:'trip/1',remove:true});const pending=deferred();respond=()=>pending.promise;
clickTrip('confirm-delete');clickTrip('confirm-delete');UI.closeTrip();assert.equal(trip.open,true);
const deletions=calls.filter(call=>call.options.method==='DELETE');assert.equal(deletions.length,1);assert.equal(deletions[0].path,'/api/shopping-trips/trip%2F1');assert.equal(deletions[0].body,undefined);
pending.resolve(ok({removed_id:'trip/1'}));await flush();assert.equal(trip.open,false);
assert(!calls.some(call=>call.path.includes('/lists/')&&call.options.method==='DELETE'));
""")


@requires_node
def test_failed_trip_removal_keeps_confirmation_and_only_retries_on_explicit_action():
    run_planner(r"""
UI.init();await UI.openTrip({id:'trip/1',remove:true});respond=async()=>fail('Trip could not be removed.');
clickTrip('confirm-delete');await flush();
assert.equal(trip.open,true);assert.equal(tripStatus.textContent,'Trip could not be removed.');assert(tripStatus.classList.contains('error'));
assert.equal(trip.querySelector('[data-trip-action="confirm-delete"]').disabled,false);
assert.equal(calls.filter(call=>call.options.method==='DELETE').length,1,'A failed removal is not retried automatically');
respond=async()=>ok({removed_id:'trip/1'});clickTrip('confirm-delete');await flush();
assert.equal(trip.open,false);assert.equal(calls.filter(call=>call.options.method==='DELETE').length,2);
""")


@requires_node
def test_canceling_trip_removal_preserves_unsaved_edit_fields_and_coverage():
    run_planner(r"""
UI.init();await UI.openTrip({id:'trip/1'});
field('date').value='2026-10-03';field('store_key').value='store-2';field('status').value='in_progress';
field('list_id').value='saved-2';trip.onchange({target:field('list_id')});trip.querySelector('[data-trip-source]').checked=false;
clickTrip('delete');clickTrip('back');
assert.equal(field('date').value,'2026-10-03');assert.equal(field('store_key').value,'store-2');assert.equal(field('status').value,'in_progress');assert.equal(field('list_id').value,'saved-2');
assert.deepEqual(trip.querySelectorAll('[data-trip-source]').map(input=>input.checked),[false]);
assert.equal(calls.filter(call=>['PATCH','POST','DELETE'].includes(call.options.method)).length,0);
""")


@requires_node
def test_reopening_and_canceling_trip_loads_ignore_stale_response_and_restore_focus():
    run_planner(r"""
UI.init();const old=deferred(),fresh=deferred();let index=0;respond=()=>[old.promise,fresh.promise][index++];
const oldLoad=UI.openTrip({date:'2026-09-25'}),first=calls[0];
const opener=element(),newLoad=UI.openTrip({date:'2026-09-26'},opener);assert.equal(first.options.signal.aborted,true);
fresh.resolve(ok(options()));await newLoad;assert.equal(field('date').value,'2026-09-26');
old.resolve(fail('Obsolete error.'));await oldLoad;assert.equal(field('date').value,'2026-09-26');assert.notEqual(tripStatus.textContent,'Obsolete error.');
UI.closeTrip();assert.equal(opener.focused,true);
const pending=deferred();respond=()=>pending.promise;const pendingLoad=UI.openTrip({date:'2026-09-27'},opener),last=calls[calls.length-1];
let prevented=false;trip.oncancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(last.options.signal.aborted,true);
pending.resolve(ok(options()));await pendingLoad;assert.equal(trip.open,false);assert.equal(calls.filter(call=>call.options.method!=='GET').length,0);
""")
