"""Preview batch forms preserve user input and keep linked plans distinct."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for UI logic checks")
def test_preview_batch_collection_portions_persistence_and_failed_completion():
    script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx = {window:{addEventListener(){}}, escapeHtml:esc, escapeAttribute:esc};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const row = (kind, values) => ({querySelectorAll:() => Object.entries(values).map(([key,value]) => ({dataset:{[kind]:key},value:String(value)}))});
const allocations = [row('allocationField',{date:'2026-10-05',meal_type:'lunch',planned_servings:4,prep_notes:'Take to work'}),row('allocationField',{date:'2026-10-07',meal_type:'dinner',planned_servings:4,prep_notes:''}),row('allocationField',{date:'2026-10-09',meal_type:'dinner',planned_servings:4,prep_notes:''})];
const steps = [row('prepField',{date:'2026-10-03',instruction:'Chop <vegetables>'}),row('prepField',{date:'2026-10-04',instruction:'Cook and portion'})];
let validity='',reset=false,refreshed=false,focused=false;
const balance={textContent:''},status={textContent:''},fieldSet={disabled:false};
const form = {hidden:false,scrollIntoView(){},elements:{batch_servings:{value:'12',focus(){},setCustomValidity:s=>validity=s},prep_notes:{value:'One batch for the week'}},
 querySelectorAll(selector){if(selector==='[data-preview-allocation]')return allocations;if(selector==='[data-preview-prep-row]')return steps;return allocations.map(r=>r.querySelectorAll().find(x=>x.dataset.allocationField==='planned_servings'));},
 querySelector(selector){return selector==='fieldset'?fieldSet:selector==='[data-preview-batch-status]'?status:selector==='[data-preview-portion-balance]'?balance:{replaceChildren(){}};},
 reportValidity:()=>!validity,reset:()=>{reset=true;}};
const state={url:'recipe://bread',projectionReady:true,selections:{butter:'bundle2'},page:{querySelector:selector=>selector==='#recipePreviewBatchPanel'?form:selector==='[data-preview-action="meal-prep"]'?{focus:()=>{focused=true;}}:status}};
ctx.state=state;vm.runInContext('integratedRecipePreview=state',ctx);
ctx.updateRecipePreviewPortionBalance();assert.equal(validity,'');assert.match(balance.textContent,/12 of 12/);
form.elements.batch_servings.value='10';ctx.updateRecipePreviewPortionBalance();assert.match(validity,/exceed/);assert.match(balance.textContent,/increase the batch by 2/);
form.elements.batch_servings.value='12';
state.batchDraftInitialized=true;form.elements.batch_servings.value='';
ctx.recipeEditServingsParts=()=>{throw new Error('Reopening a draft must not replace its eating dates');};
ctx.openRecipePreviewBatchPanel();assert.equal(form.elements.batch_servings.value,'');
form.elements.batch_servings.value='12';
const payload=JSON.parse(JSON.stringify(ctx.recipePreviewBatchPayload(form,state)));
assert.equal(payload.allocations.length,3);assert.equal(payload.prep_steps.length,2);assert.equal(payload.batch_servings,12);
assert.deepEqual(payload.allocations.map(x=>x.planned_servings),[4,4,4]);assert.deepEqual(payload.ingredient_option_selections,{butter:'bundle2'});
assert.equal(payload.prep_notes,'One batch for the week');assert.equal(payload.allocations[0].prep_notes,'Take to work');assert(!('recipe_notes' in payload));
ctx.fetch=async()=>({ok:false,json:async()=>({error:'That slot is already planned.'})});
const event={preventDefault(){},currentTarget:form};
(async()=>{
 await ctx.submitRecipePreviewBatch(event);assert.equal(reset,false);assert.equal(form.hidden,false);assert.equal(fieldSet.disabled,false);assert.match(status.textContent,/already planned/);
 ctx.fetch=async(url,options)=>{assert.equal(url,'/api/meal-plan/batches');assert.equal(JSON.parse(options.body).allocations.length,3);return {ok:true,json:async()=>({ok:true})};};
 ctx.refreshRecipePreviewMeals=async()=>{refreshed=true;};
 await ctx.submitRecipePreviewBatch(event);assert(reset&&refreshed&&focused);assert.equal(form.hidden,true);assert.equal(fieldSet.disabled,false);
 const batch={id:'batch1',batch_servings:12,allocated_servings:12,remaining_servings:0,prep_notes:'One & <batch>',allocations:payload.allocations,prep_steps:payload.prep_steps.map((x,i)=>({...x,id:String(i),completed:i===0})).reverse()};
 const html=ctx.recipePreviewMealPlansHtml({batches:[batch],meals:payload.allocations.map(x=>({...x,batch_id:'batch1'}))});
 assert.equal((html.match(/Take to work/g)||[]).length,1,'Linked meals appear once in their batch');
 assert(html.includes('Chop &lt;vegetables&gt;'));assert(html.includes('One &amp; &lt;batch&gt;'));assert(html.includes('is-complete'));
 assert(html.indexOf('Chop &lt;vegetables&gt;') < html.indexOf('Cook and portion'),'The prep timeline is chronological even when tasks were entered out of order');
 assert(!html.includes('Other scheduled meals'));assert.equal((html.match(/View in Meal Planner/g)||[]).length,3);
 const input={checked:true,disabled:false,dataset:{batchId:'batch1',stepId:'step1'},closest:()=>({classList:{toggle(){}}})};
 ctx.fetch=async()=>({ok:false,json:async()=>({error:'Unable to save'})});
 await ctx.toggleRecipePreviewPrepStep(input);assert.equal(input.checked,false);assert.equal(input.disabled,false);assert.equal(status.textContent,'Unable to save');
 // Refresh can replace the original checkbox before its PATCH completes.
 let release,oldReadAborted=false,visibleComplete=false;
 const current={checked:false,dataset:input.dataset,closest:()=>({classList:{toggle:(_name,value)=>visibleComplete=value}})};
 state.page.querySelectorAll=()=>[current];state.mealsAbort={abort:()=>oldReadAborted=true};
 input.checked=true;ctx.fetch=()=>new Promise(resolve=>release=resolve);
 const pending=ctx.toggleRecipePreviewPrepStep(input);
 release({ok:true,json:async()=>({ok:true})});await pending;
 assert(oldReadAborted);assert.equal(current.checked,true);assert.equal(visibleComplete,true);assert.equal(input.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    source = Path(__file__).resolve().parents[1] / "PushShoppingList/static/js/recipe-preview.js"
    result = subprocess.run([shutil.which("node"), "-e", script, str(source)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
