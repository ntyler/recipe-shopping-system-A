"""Saved preview plans show family portions and preserve prep completion behavior."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for UI logic checks")
def test_preview_saved_plans_family_portions_and_failed_completion():
    script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx = {window:{addEventListener(){}}, escapeHtml:esc, escapeAttribute:esc};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const allocations = [
 {date:'2026-10-05',meal_type:'lunch',planned_servings:4,prep_notes:'Take to work'},
 {date:'2026-10-07',meal_type:'dinner',planned_servings:4,prep_notes:''},
 {date:'2026-10-09',meal_type:'dinner',planned_servings:4,prep_notes:''},
];
const steps = [
 {date:'2026-10-03',instruction:'Chop <vegetables>'},
 {date:'2026-10-04',instruction:'Cook and portion'},
];
const status = {textContent:''};
const state = {url:'recipe://bread', projectionReady:true, page:{querySelector:()=>status}};
ctx.state=state;vm.runInContext('integratedRecipePreview=state',ctx);
(async()=>{
 const batch = {id:'batch1',batch_servings:12,allocated_servings:12,remaining_servings:0,prep_notes:'One & <batch>',allocations,prep_steps:steps.map((step,i)=>({...step,id:String(i),completed:i===0})).reverse()};
 const html = ctx.recipePreviewMealPlansHtml({batches:[batch],meals:allocations.map(meal=>({...meal,batch_id:'batch1'}))});
 assert.equal((html.match(/Take to work/g)||[]).length,1,'Linked meals appear once in their batch');
 assert(html.includes('Chop &lt;vegetables&gt;'));assert(html.includes('One &amp; &lt;batch&gt;'));assert(html.includes('is-complete'));
 assert(html.indexOf('Chop &lt;vegetables&gt;') < html.indexOf('Cook and portion'),'The prep timeline is chronological even when tasks were entered out of order');
 assert(!html.includes('Other scheduled meals'));assert.equal((html.match(/View in Meal Planner/g)||[]).length,3);

 const familyMeal = {...allocations[0],planned_servings:1.5,member_portions:[
  {member_id:'adult',name:'Current <adult>',name_snapshot:'Old adult',servings:1},
  {member_id:'child',name_snapshot:'Child & friend',servings:0.5},
 ]};
 const original = JSON.stringify(familyMeal);
 const familyHtml = ctx.recipePreviewFamilyPortionsHtml(familyMeal);
 assert(familyHtml.includes('<details'));
 assert(familyHtml.includes('Current &lt;adult&gt;'));
 assert(familyHtml.includes('Child &amp; friend'));
 assert(!familyHtml.includes('Old adult'));
 assert(/(?:0\.5|½)/.test(familyHtml), 'Half servings must be visible');
 assert.equal(JSON.stringify(familyMeal), original, 'Rendering must not change stored family portions or meal totals');
 assert.equal(ctx.recipePreviewFamilyPortionsHtml(allocations[0]), '', 'Legacy household meals have no family disclosure');
 const familyPlan = ctx.recipePreviewMealPlansHtml({batches:[],meals:[familyMeal]});
 assert.equal((familyPlan.match(/View in Meal Planner/g)||[]).length,1,'Family portions do not add separate meals');
 assert(/(?:1\.5|1½) servings/.test(familyPlan), 'Meal total remains 1.5 servings');

 const familyBatch = {...batch,allocations:[familyMeal],batch_servings:1.5,allocated_servings:1.5,member_totals:familyMeal.member_portions};
 const familyBatchHtml = ctx.recipePreviewMealPlansHtml({batches:[familyBatch],meals:[{...familyMeal,batch_id:'batch1'}]});
 assert.equal((familyBatchHtml.match(/View in Meal Planner/g)||[]).length,1);
 assert(familyBatchHtml.includes('Current &lt;adult&gt;'));
 assert(familyBatchHtml.includes('Child &amp; friend'));
 assert(!familyBatchHtml.includes('Old adult'));
 assert(familyBatchHtml.includes('Current &lt;adult&gt;: 1 servings'));
 assert(familyBatchHtml.includes('Child &amp; friend: 0.5 servings'));

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
