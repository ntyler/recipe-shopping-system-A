"""Single-meal and prep-plan deletion through the production dialog handlers."""

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "PushShoppingList/static/js/app.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for dialog interaction checks")


def run_delete(script):
    bootstrap = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const plain=value=>JSON.parse(JSON.stringify(value));
function node(tag='div',extra={}){
 const classes=new Set(),attrs={};let text='';
 const value={tag,attrs,children:[],dataset:{},hidden:false,disabled:false,focused:false,value:'',handlers:{},
  classList:{add(value){classes.add(value);},remove(value){classes.delete(value);},toggle(value,on){if(on)classes.add(value);else classes.delete(value);},contains(value){return classes.has(value);}},
  setAttribute(key,value){attrs[key]=String(value);},removeAttribute(key){delete attrs[key];},getAttribute(key){return attrs[key]??null;},
  focus(){this.focused=true;document.activeElement=this;},
  append(...children){this.children.push(...children);},appendChild(child){this.children.push(child);return child;},replaceChildren(...children){this.children=children;text='';},
  addEventListener(event,handler){(this.handlers[event] ||= []).push(handler);},dispatch(event,detail={}){this['on'+event]?.(detail);for(const handler of this.handlers[event]||[])handler(detail);},
  ...extra};
 Object.defineProperty(value,'textContent',{get(){return text+this.children.map(child=>child.textContent??child).join('');},set(value){text=String(value);this.children=[];}});
 Object.defineProperty(value,'innerHTML',{set(){throw new Error('Deletion details must use text nodes, not insert recipe data as HTML');}});
 return value;
}
const selectors=['id','copy','summary','schedule','items','status','submit','retry','close','cancel'];
const fields=Object.fromEntries(selectors.map(key=>[key,node(['submit','retry','close','cancel'].includes(key)?'button':key==='id'?'input':key==='items'?'ul':key==='schedule'?'details':'div')]));
fields.schedule.hidden=true;fields.retry.hidden=true;const title=node('h3');
const dialog=node('dialog',{open:false,querySelector(selector){if(selector==='#mealPlannerDeleteTitle')return title;const match=selector.match(/^\[data-meal-delete-([^\]]+)\]$/);return match?fields[match[1]]||null:null;},
 querySelectorAll(selector){if(selector==='button')return Object.values(fields).filter(value=>value.tag==='button');return Object.values(fields).filter(value=>['button','input'].includes(value.tag));},
 showModal(){this.open=true;},close(){this.open=false;this.dispatch('close');}});
const form=node('form',{querySelector:selector=>dialog.querySelector(selector),closest:selector=>selector==='dialog'?dialog:null});
const plannerStatus=node('p'),selectedTab=node('button'),page={dataset:{mealWeek:'2026-09-21'},querySelector(selector){return selector==='[data-meal-planner-refresh-status]'?plannerStatus:selectedTab;}};
const document={activeElement:null,getElementById:id=>id==='mealPlannerDeleteDialog'?dialog:id==='mealPlannerDeleteTitle'?title:id==='mealPlannerPage'?page:null,
 querySelector:selector=>dialog.querySelector(selector),createElement:node};
const calls=[],refreshes=[];let previewRefreshes=0,reloads=0,respond=async()=>{throw new Error('Unexpected request');};
const canonical=url=>{const parsed=new URL(url,'https://example.test');parsed.searchParams.set('viewer_user_id','account-1');return parsed.pathname+parsed.search+parsed.hash;};
const window={location:{reload(){reloads++;}},refreshRecipePreviewMeals:async()=>{previewRefreshes++;}};
const ctx={window,document,console,AbortController,URL,withCanonicalViewerUserId:canonical,
 setMealPlannerStatus(message,error,selector){const status=document.querySelector(selector);status.textContent=message;status.hidden=!message;status.classList.toggle('error',!!error);},
 refreshMealPlannerWorkspace:async(...args)=>{assert.equal(dialog.open,false,'Close successful confirmation before replacing planner markup');refreshes.push(args);return true;},
 refreshRecipePreviewMeals:window.refreshRecipePreviewMeals,
 fetch:async(url,options={})=>{const parsed=new URL(url,'https://example.test'),call={url,path:parsed.pathname,params:parsed.searchParams,options};calls.push(call);return respond(call);}
};
vm.createContext(ctx);const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInContext(source.slice(source.indexOf('function openMealPlannerDeleteDialog'),source.indexOf('const GLOBAL_APP_SEARCH_DEBOUNCE_MS')),ctx);
const flush=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
const ok=data=>({ok:true,status:200,json:async()=>({ok:true,...data})});
const fail=(error,status=500)=>({ok:false,status,json:async()=>({ok:false,error})});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const meal=(extra={})=>({id:'meal/1',batch_id:'batch/1',date:'2026-09-25',meal_type:'dinner',recipe_name:'Corn <bread> & soup',planned_servings:2,...extra});
const batch=()=>({id:'batch/1',recipe_name:'Corn <bread> & soup',batch_servings:12,prep_steps:[{id:'step-1',date:'2026-09-24',instruction:'Bake <bread>',completed:true},{id:'step-2',date:'2026-10-04',instruction:'Reheat',completed:false}]});
const meals=()=>[meal(),meal({id:'meal/2',date:'2026-10-05',meal_type:'lunch',planned_servings:3})];
const card=(extra={})=>node('button',{dataset:{mealId:'meal/1',batchId:'batch/1',mealName:'Stale card title',...extra}});
const submit=()=>ctx.confirmMealPlannerDelete({preventDefault(){},currentTarget:form});
respond=async call=>ok(call.path.includes('/batches/')?{batch:batch(),meals:meals()}:{meal:meal()});
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", str(APP_JS)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_removal_template_starts_with_disabled_submit_and_collapsed_scope_details():
    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = []

        def handle_starttag(self, tag, attrs):
            self.elements.append((tag, dict(attrs)))

    source = (ROOT / "PushShoppingList/templates/sections/app_workspaces.html").read_text(encoding="utf-8")
    start = source.index('<dialog id="mealPlannerDeleteDialog"')
    markup = source[start:source.index("</dialog>", start)]
    parser = Elements()
    parser.feed(markup)
    fields = {key: attrs for _, attrs in parser.elements for key in attrs if key.startswith("data-meal-delete-")}
    assert "disabled" in fields["data-meal-delete-submit"]
    assert "hidden" in fields["data-meal-delete-schedule"]
    assert "open" not in fields["data-meal-delete-schedule"]
    assert "hidden" in fields["data-meal-delete-retry"]
    assert "disabled" not in fields["data-meal-delete-cancel"]
    assert "disabled" not in fields["data-meal-delete-close"]
    assert fields["data-meal-delete-retry"]["onclick"] == "return loadMealPlannerDeleteDetails()"
    assert fields["data-meal-delete-status"]["aria-live"] == "polite"
    assert "saved recipe, shopping lists, and shopping trips will be kept" in markup
    assert "Ingredients already added to a shopping list will stay there" in markup


def test_entire_batch_confirmation_loads_all_dates_and_tasks_before_enabling_removal():
    run_delete(r"""
const pending=deferred();respond=()=>pending.promise;const opener=card();
assert.equal(ctx.openMealPlannerDeleteDialog(opener,'batch'),false);
assert.equal(dialog.open,true);assert.equal(dialog.mealDeleteState.scope,'batch');assert.equal(dialog.mealDeleteState.id,'batch/1');
assert.equal(fields.submit.disabled,true);assert.equal(fields.cancel.focused,true);assert.equal(fields.cancel.disabled,false);
assert.equal(fields.schedule.hidden,true);assert.equal(dialog.attrs['aria-busy'],'true');
await submit();assert.equal(calls.length,1,'Submission is blocked until the affected schedule is loaded');
assert.equal(calls[0].path,'/api/meal-plan/batches/batch%2F1');assert.equal(calls[0].params.get('viewer_user_id'),'account-1');
pending.resolve(ok({batch:batch(),meals:meals()}));await flush();
assert.equal(dialog.mealDeleteState.ready,true);assert.equal(dialog.mealDeleteState.loading,false);assert.equal(fields.submit.disabled,false);
assert.equal(title.textContent,'Remove entire prep batch');assert(fields.copy.textContent.includes('Corn <bread> & soup'));assert(!fields.copy.textContent.includes('Stale card title'));
assert.match(fields.summary.textContent,/2 scheduled meals/);assert.match(fields.summary.textContent,/2 prep tasks/);assert.match(fields.summary.textContent,/other weeks/);
assert(fields.summary.textContent.includes(ctx.mealPlannerDeleteDate('2026-09-25')));assert(fields.summary.textContent.includes(ctx.mealPlannerDeleteDate('2026-10-05')));
assert.equal(fields.schedule.hidden,false);assert.equal(fields.schedule.open,false);
assert.equal(fields.items.children.length,4);assert(fields.items.children.every(item=>item.tag==='li'));
assert(fields.items.children[0].textContent.includes('Bake <bread>'));assert(fields.items.children[3].textContent.includes('lunch'));
assert.equal(calls.filter(call=>call.options.method==='DELETE').length,0);
""")


@pytest.mark.parametrize("scope", ["meal", "batch"])
def test_confirmed_scope_deletes_only_its_endpoint_and_refreshes_same_week_once(scope):
    run_delete(r"""
const scope=__SCOPE__,opener=card();ctx.openMealPlannerDeleteDialog(opener,scope);await flush();
if(scope==='meal'){
 assert.equal(fields.items.children.length,1);assert.match(fields.summary.textContent,/only the dinner/);assert.match(fields.summary.textContent,/Other meals in this batch and its prep tasks will be kept/);
 assert(fields.summary.textContent.includes(ctx.mealPlannerDeleteDate('2026-09-25')));
}
// DOM inputs cannot redirect a confirmed deletion to a different record.
fields.id.value='tampered-id';const pending=deferred();respond=()=>pending.promise;
const first=submit();await submit();ctx.closeMealPlannerDeleteDialog();ctx.openMealPlannerDeleteDialog(card({mealId:'another',batchId:'other'}),'batch');
assert.equal(dialog.open,true);assert.equal(dialog.mealDeleteState.saving,true);assert(dialog.querySelectorAll('button').every(button=>button.disabled));
const deletes=calls.filter(call=>call.options.method==='DELETE');assert.equal(deletes.length,1);
assert.equal(deletes[0].path,scope==='batch'?'/api/meal-plan/batches/batch%2F1':'/api/meal-plan/meal%2F1');
assert.equal(deletes[0].params.get('viewer_user_id'),'account-1');assert.equal(deletes[0].options.body,undefined);
pending.resolve(ok({removed_id:scope==='batch'?'batch/1':'meal/1'}));await first;
assert.equal(dialog.open,false);assert.equal(dialog.mealDeleteState,null);assert.equal(opener.focused,true);
assert.deepEqual(refreshes,[[]],'Refresh the current week without navigating to another allocation date');
assert.equal(page.dataset.mealWeek,'2026-09-21');assert.equal(previewRefreshes,1);assert.equal(reloads,0);assert.equal(selectedTab.focused,true);
assert.match(plannerStatus.textContent,/removed/i);assert(!plannerStatus.classList.contains('error'));
await submit();assert.equal(calls.filter(call=>call.options.method==='DELETE').length,1);
respond=async()=>ok({meal:meal()});ctx.openMealPlannerDeleteDialog(card(),'meal');await flush();
assert.equal(fields.cancel.disabled,false);assert.equal(fields.close.disabled,false,'Reopening after a successful deletion resets the cancel controls');
ctx.closeMealPlannerDeleteDialog();assert.equal(dialog.open,false);
""".replace("__SCOPE__", repr(scope)))


def test_standalone_meal_confirmation_does_not_describe_batch_or_prep_removal():
    run_delete(r"""
respond=async()=>ok({meal:meal({batch_id:undefined,meal_type:'breakfast'})});
ctx.openMealPlannerDeleteDialog(card({batchId:''}));await flush();
assert.equal(title.textContent,'Remove this meal');assert.match(fields.summary.textContent,/only the breakfast/);
assert(!fields.summary.textContent.includes('prep tasks'));assert.equal(fields.items.children.length,1);
assert.equal(calls[0].path,'/api/meal-plan/meal%2F1');assert.equal(dialog.mealDeleteState.scope,'meal');
""")


@pytest.mark.parametrize("malformed", ["missing_meals", "missing_tasks", "wrong_batch", "mismatched_id", "missing_date"])
def test_incomplete_batch_details_cannot_enable_or_send_delete(malformed):
    run_delete(r"""
const data={batch:batch(),meals:meals()},problem=__PROBLEM__;
if(problem==='missing_meals')delete data.meals;
if(problem==='missing_tasks')delete data.batch.prep_steps;
if(problem==='wrong_batch')data.meals[1].batch_id='other-batch';
if(problem==='mismatched_id')data.batch.id='other-batch';
if(problem==='missing_date')delete data.meals[1].date;
respond=async()=>ok(data);ctx.openMealPlannerDeleteDialog(card(),'batch');await flush();
assert.equal(dialog.mealDeleteState.ready,false);assert.equal(fields.submit.disabled,true);assert.equal(fields.retry.hidden,false);
assert.match(fields.status.textContent,/incomplete/i);await submit();assert.equal(calls.filter(call=>call.options.method==='DELETE').length,0);
""".replace("__PROBLEM__", repr(malformed)))


def test_failed_get_can_retry_without_losing_target_or_deleting_early():
    run_delete(r"""
respond=async()=>fail('Batch details could not be loaded.');ctx.openMealPlannerDeleteDialog(card(),'batch');await flush();
assert.equal(fields.status.textContent,'Batch details could not be loaded.');assert(fields.status.classList.contains('error'));
assert.equal(fields.submit.disabled,true);assert.equal(fields.retry.hidden,false);await submit();assert.equal(calls.length,1);
respond=async()=>ok({batch:batch(),meals:meals()});await ctx.loadMealPlannerDeleteDetails();
assert.equal(calls.length,2);assert.equal(calls[1].path,'/api/meal-plan/batches/batch%2F1');
assert.equal(fields.retry.hidden,true);assert.equal(fields.submit.disabled,false);assert.equal(dialog.mealDeleteState.ready,true);
assert.equal(fields.status.textContent,'');assert.equal(calls.filter(call=>call.options.method==='DELETE').length,0);
""")


def test_loading_cancel_aborts_and_late_details_cannot_reopen_or_change_confirmation():
    run_delete(r"""
const pending=deferred();respond=()=>pending.promise;const opener=card();ctx.openMealPlannerDeleteDialog(opener,'batch');
const request=calls[0];let prevented=false;dialog.oncancel({preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(dialog.open,false);assert.equal(request.options.signal.aborted,true);assert.equal(opener.focused,true);
pending.resolve(ok({batch:batch(),meals:meals()}));await flush();
assert.equal(dialog.open,false);assert.equal(dialog.mealDeleteState,null);assert.equal(fields.items.children.length,0);assert.equal(calls.filter(call=>call.options.method==='DELETE').length,0);
""")


def test_loading_another_scope_ignores_stale_batch_details_and_error():
    run_delete(r"""
const old=deferred(),fresh=deferred();let index=0;respond=()=>[old.promise,fresh.promise][index++];
ctx.openMealPlannerDeleteDialog(card(),'batch');const first=calls[0];
ctx.openMealPlannerDeleteDialog(card({mealId:'latest'}),'meal');assert.equal(first.options.signal.aborted,true);
fresh.resolve(ok({meal:meal({id:'latest',recipe_name:'Latest meal'})}));await flush();
const copy=fields.copy.textContent,summary=fields.summary.textContent;assert(copy.includes('Latest meal'));
old.resolve(fail('Old details failed.'));await flush();
assert.equal(fields.copy.textContent,copy);assert.equal(fields.summary.textContent,summary);assert.equal(fields.status.textContent,'');
assert.equal(dialog.mealDeleteState.id,'latest');assert.equal(dialog.mealDeleteState.scope,'meal');assert.equal(fields.items.children.length,1);assert.equal(fields.submit.disabled,false);
""")


def test_failed_delete_preserves_confirmation_for_explicit_retry_and_does_not_refresh():
    run_delete(r"""
ctx.openMealPlannerDeleteDialog(card(),'batch');await flush();respond=async()=>fail('Batch removal failed.');await submit();
assert.equal(dialog.open,true);assert.equal(dialog.mealDeleteState.saving,false);assert.equal(dialog.mealDeleteState.ready,true);
assert.equal(fields.status.textContent,'Batch removal failed.');assert.equal(fields.submit.disabled,false);assert.equal(fields.cancel.disabled,false);
assert.equal(fields.submit.textContent,'Remove entire prep batch');assert.equal(refreshes.length,0);assert.equal(previewRefreshes,0);assert.equal(reloads,0);
assert.equal(calls.filter(call=>call.options.method==='DELETE').length,1);
respond=async()=>ok({removed_id:'batch/1'});await submit();assert.equal(dialog.open,false);assert.equal(calls.filter(call=>call.options.method==='DELETE').length,2);assert.equal(refreshes.length,1);
""")


def test_missing_scope_id_or_invalid_scope_cannot_start_a_removal():
    run_delete(r"""
ctx.openMealPlannerDeleteDialog(card({batchId:''}),'batch');ctx.openMealPlannerDeleteDialog(card({mealId:''}),'meal');ctx.openMealPlannerDeleteDialog(card(),'all');
await submit();assert.equal(dialog.open,false);assert.equal(calls.length,0);assert.equal(refreshes.length,0);
""")


def test_successful_removal_with_failed_calendar_refresh_cannot_repeat_the_delete():
    run_delete(r"""
ctx.openMealPlannerDeleteDialog(card(),'batch');await flush();
ctx.refreshMealPlannerWorkspace=async(...args)=>{assert.equal(dialog.open,false);refreshes.push(args);return false;};
respond=async()=>ok({removed_id:'batch/1'});await submit();
assert.equal(dialog.open,false);assert.equal(dialog.mealDeleteState,null);assert.match(plannerStatus.textContent,/removed.*Reopen the planner/i);
assert(plannerStatus.classList.contains('error'));assert.equal(reloads,0);assert.equal(previewRefreshes,1);
await submit();assert.equal(calls.filter(call=>call.options.method==='DELETE').length,1,'A refresh failure must not retry an already successful deletion');
""")
