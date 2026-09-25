"""Shared schedule integration for the weekly planner's recipe picker.

These exercise real panel/model logic with a small DOM boundary; they do not
claim browser layout or native-dialog visual verification.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / "PushShoppingList/static/js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for dialog interaction checks")


def run_dialog(script):
    bootstrap = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const plain = value => JSON.parse(JSON.stringify(value));
const classes = () => ({add(){},remove(){},toggle(){}});
function node(extra={}) {
 return {hidden:false,disabled:false,dataset:{},innerHTML:'',textContent:'',value:'',handlers:{},classList:classes(),
  addEventListener(type,handler){(this.handlers[type] ||= []).push(handler);},
  focus(){this.focused=true;},setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},
  querySelector(){return null;},querySelectorAll(){return [];},...extra};
}
let requests=[],refreshes=[],statuses=[],ingredientRenders=[],previewRefreshes=0;
let responseFactory=async()=>({ok:true,json:async()=>({ok:true,members:[{id:'adult',name:'Adult'},{id:'child',name:'Child'}]})});
let activeDialog;
const page=node({dataset:{mealWeek:'2026-09-21'}});
function makeDialog() {
 const options=[
  {value:'',textContent:'Choose a recipe',label:'Choose a recipe',dataset:{defaultServings:'1',yieldLabel:''}},
  {value:'recipe://bread',textContent:'Corn Spoon Bread',label:'Corn Spoon Bread',dataset:{defaultServings:'12',yieldLabel:'12 servings'}},
  {value:'recipe://soup',textContent:'Soup',label:'Soup',dataset:{defaultServings:'4',yieldLabel:'4 servings'}},
 ];
 const recipe=node({options});
 Object.defineProperty(recipe,'selectedOptions',{get:()=>[options.find(o=>o.value===recipe.value) || options[0]]});
 const helper=node(), fieldset=node(), close=node(), empty=node(), status=node();
 const form=node({hidden:true,nodes:{},contains(){return false;},scrollIntoView(){},reportValidity(){return true;},
  querySelector(selector){return this.nodes[selector] ||= node();},
 });
 const dialog=node({open:false,options,recipe,form,fieldset,closeButton:close,helper,empty,status,radios:[],
  dataset:{mealDate:'2026-09-21'},
  showModal(){this.open=true;},close(){this.open=false;for(const handler of this.handlers.close || []) handler({});},
  querySelector(selector){
   if(selector.includes('mealPlannerScheduleForm'))return form;
   if(selector.includes('mealPlannerRecipeFields'))return fieldset;
   if(selector.includes('mealPlannerRecipe') || selector.includes('recipe_url'))return recipe;
   if(selector.includes('data-meal-schedule-close'))return close;
   if(selector.includes('data-meal-servings-help'))return helper;
   if(selector.includes('data-meal-schedule-empty'))return empty;
   if(selector.includes('data-meal-plan-status'))return status;
   return null;
  },
  querySelectorAll(selector){
   if(selector.includes('ingredient-requirement-id'))return this.radios;
   if(selector.includes('data-meal-schedule-close'))return [close];
   return [];
  },
 });
 return dialog;
}
activeDialog=makeDialog();
const ctx={console,Date,Set,document:{activeElement:null,
 getElementById(id){return ({mealPlannerDialog:activeDialog,mealPlannerRecipe:activeDialog.recipe,
  mealPlannerRecipeFields:activeDialog.fieldset,mealPlannerScheduleForm:activeDialog.form,
  mealPlannerServingsHelp:activeDialog.helper,mealPlannerPage:page})[id] || null;},
 querySelector(selector){return activeDialog.querySelector(selector);},
},fetch:async(url,options)=>{requests.push({url,options});return responseFactory(url,options);},
 setMealPlannerStatus(message,error){statuses.push({message,error});},
 refreshMealPlannerWorkspace:async({date}={})=>{assert.equal(activeDialog.open,false,'Close dialog before refreshing its containing page');refreshes.push(date);return true;},
 refreshRecipePreviewMeals:async()=>{previewRefreshes++;},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const source=fs.readFileSync(process.argv[3],'utf8');
vm.runInContext(source.slice(source.indexOf('function formatMealPlannerServingNumber'),source.indexOf('function openMealPlannerDeleteDialog')),ctx);
// Ingredient options have their own DOM rendering tests. Keep their placement
// outside the scheduling form visible to the real context collector here.
ctx.renderMealPlannerIngredientOptions=option=>{ingredientRenders.push(option?.value);activeDialog.radios=[];};
const M=ctx.MealPlanSchedule;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const choose=async(value)=>{activeDialog.recipe.value=value;ctx.syncMealPlannerServingsFromRecipe();await flush();return activeDialog.mealPlanScheduleState.panel;};
const open=async(date='2026-10-05',meal='dinner')=>{ctx.openMealPlannerDialog(date,meal);await flush();};
const submit=panel=>panel.submit({preventDefault(){}});
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});",
         str(JS_ROOT / "meal-plan-schedule.js"), str(JS_ROOT / "meal-plan-panel.js"), str(JS_ROOT / "app.js")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_clicked_slot_and_recipe_yield_initialize_shared_schedule():
    run_dialog(r"""
await open('2026-10-07','breakfast');
assert.equal(activeDialog.open,true);assert.equal(activeDialog.form.hidden,true);
const panel=await choose('recipe://bread');
assert(panel instanceof ctx.MealPlanPanel);
assert.equal(panel.form,activeDialog.form);assert.equal(panel.form.hidden,false);
assert.equal(panel.draft.singleDate,'2026-10-07');
assert.deepEqual(plain(panel.draft.mealTypes),['breakfast']);
assert.equal(Number(panel.draft.householdDefaults.breakfast),12);
assert.equal(panel.options.title,'Corn Spoon Bread');
assert.match(activeDialog.helper.textContent,/12 servings/);
assert.equal(panel.draft.members.length,2);
assert.equal(activeDialog.form.handlers.submit.length,1);
assert.equal(requests.filter(r=>r.options?.method==='POST').length,0);
assert(activeDialog.form.innerHTML.includes('Date range'));
assert(activeDialog.form.innerHTML.includes('Select days'));
assert(activeDialog.form.innerHTML.includes('By family member'));
""")


def test_recipe_switch_keeps_scheduling_work_and_only_updates_untouched_yield_defaults():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);M.setMeals(panel.draft,['breakfast','dinner']);
M.setHouseholdDefault(panel.draft,'breakfast',0.5);
M.setDayHousehold(panel.draft,'2026-10-07','dinner',2.5);
M.setDayFamily(panel.draft,'2026-10-07','child','dinner',{servings:0.5});
M.setDayNotes(panel.draft,'2026-10-07','Pack separately');
panel.draft.notes='Keep in the fridge';panel.draft.prepSteps=[{date:'2026-10-04',instruction:'Cook ahead'}];
const samePanel=await choose('recipe://soup');
assert.equal(samePanel,panel,'Switching recipes must not accumulate another controller on the same form');
assert.equal(panel.options.title,'Soup');
assert.deepEqual(plain(panel.draft.selectedDates),['2026-10-05','2026-10-07']);
assert.deepEqual(plain(panel.draft.mealTypes),['breakfast','dinner']);
assert.equal(Number(panel.draft.householdDefaults.breakfast),0.5);
assert.equal(Number(panel.draft.householdDefaults.dinner),4);
assert.equal(Number(panel.draft.days['2026-10-07'].household.dinner),2.5);
assert.equal(Number(panel.draft.days['2026-10-07'].family.child.dinner.servings),0.5);
assert.equal(panel.draft.days['2026-10-07'].notes,'Pack separately');
assert.equal(panel.draft.notes,'Keep in the fridge');assert.equal(panel.draft.prepSteps[0].instruction,'Cook ahead');
assert.equal(activeDialog.form.handlers.submit.length,1);
assert.equal(ingredientRenders.at(-1),'recipe://soup');
""")


def test_family_batch_save_uses_external_recipe_choices_and_refreshes_after_closing():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);M.setMeals(panel.draft,['breakfast','dinner']);
M.setPortionMode(panel.draft,'family');M.setFamilyDefault(panel.draft,'child','dinner',{servings:0.5});
panel.draft.notes='Meal prep only';panel.draft.prepSteps=[{date:'2026-10-04',instruction:'Bake once'}];
activeDialog.radios=[{dataset:{ingredientRequirementId:'butter'},value:'unsalted'}];
requests=[];responseFactory=async(url,options)=>{
 assert.equal(url,'/api/meal-plan/batches');assert.equal(options.method,'POST');
 const body=JSON.parse(options.body);
 assert.equal(body.recipe_url,'recipe://bread');assert.deepEqual(body.ingredient_option_selections,{butter:'unsalted'});
 assert.equal(body.allocations.length,4);assert.equal(body.portion_mode,'family');
 assert.equal(body.allocations[1].member_portions[1].servings,0.5);
 assert.equal(body.prep_notes,'Meal prep only');assert.equal(body.prep_steps[0].instruction,'Bake once');
 assert(!('recipe_notes' in body));assert(!('batch_servings' in body));
 return {ok:true,json:async()=>({ok:true,batch:{id:'batch-1'}})};
};
await submit(panel);
assert.equal(requests.length,1);assert.equal(activeDialog.open,false);
assert.deepEqual(refreshes,['2026-10-05']);assert.equal(previewRefreshes,1);
assert.equal(panel.draft.notes,'','Successful save must not leave a resubmittable old draft');
""")


def test_pending_save_locks_recipe_and_close_then_failure_preserves_the_entire_draft():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);panel.draft.notes='Keep all my work';
activeDialog.radios=[{dataset:{ingredientRequirementId:'butter'},value:'unsalted'}];
let release;requests=[];responseFactory=()=>new Promise(resolve=>release=resolve);
const pending=submit(panel);
assert.equal(panel.ui.busy,true);assert.equal(activeDialog.fieldset.disabled,true);
ctx.closeMealPlannerDialog();assert.equal(activeDialog.open,true);
activeDialog.recipe.value='recipe://soup';ctx.syncMealPlannerServingsFromRecipe();
assert.equal(activeDialog.recipe.value,'recipe://bread');
let prevented=false;
for(const handler of activeDialog.handlers.cancel || [])handler({preventDefault(){prevented=true;}});
assert.equal(prevented,true,'Escape cannot dismiss a pending save');
await submit(panel);assert.equal(requests.length,1);
release({ok:false,json:async()=>({ok:false,error:'Please retry later.'})});await pending;
assert.equal(panel.ui.busy,false);assert.equal(activeDialog.fieldset.disabled,false);
assert.equal(activeDialog.open,true);assert.equal(panel.form.hidden,false);
assert.equal(panel.draft.notes,'Keep all my work');assert.equal(panel.draft.selectedDates.length,2);
assert.equal(panel.options.getContext().ingredient_option_selections.butter,'unsalted');
assert.match(panel.ui.message,/Please retry later/);assert.equal(refreshes.length,0);
""")


def test_reopening_prefills_new_slot_without_duplicate_listeners_and_refresh_replacement_gets_new_controller():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);panel.draft.notes='Canceled draft';
ctx.closeMealPlannerDialog();await open('2026-11-02','lunch');
const reopened=activeDialog.mealPlanScheduleState.panel;
assert.equal(reopened,panel);assert.equal(activeDialog.form.handlers.submit.length,1);
assert.equal(reopened.draft.singleDate,'2026-11-02');assert.deepEqual(plain(reopened.draft.mealTypes),['lunch']);
assert.equal(reopened.draft.notes,'');
ctx.closeMealPlannerDialog();const oldDialog=activeDialog;activeDialog=makeDialog();
await open('2026-12-03','snack');const replacement=await choose('recipe://soup');
assert.notEqual(replacement,panel);assert.equal(replacement.form,activeDialog.form);
assert.equal(replacement.draft.singleDate,'2026-12-03');assert.deepEqual(plain(replacement.draft.mealTypes),['snack']);
assert.equal(replacement.options.getContext().recipe_url,'recipe://soup');
assert.equal(oldDialog.form.handlers.submit.length,1);assert.equal(activeDialog.form.handlers.submit.length,1);
""")


def test_placeholder_and_replaced_dialog_cannot_submit_a_stale_recipe_context():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
panel.draft.notes='Retain while selecting a recipe';
await choose('');assert.equal(activeDialog.form.hidden,true);
assert.equal(panel.draft.notes,'Retain while selecting a recipe');
requests=[];await submit(panel);assert.equal(requests.length,0);
await choose('recipe://bread');assert.equal(panel.form.hidden,false);
assert.equal(panel.draft.notes,'Retain while selecting a recipe');
const oldDialog=activeDialog;activeDialog=makeDialog();
assert.equal(oldDialog.open,true,'The old controller alone cannot prove it still belongs to the page');
requests=[];await submit(panel);assert.equal(requests.length,0);
assert.equal(panel.draft.notes,'Retain while selecting a recipe');
""")


def test_member_updates_lock_external_controls_and_refresh_cards_only_after_closing():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
M.setPortionMode(panel.draft,'family');panel.draft.notes='Keep portions';
panel.ui.names.child='Younger child';
let release;responseFactory=()=>new Promise(resolve=>release=resolve);
const pending=panel.saveMember('child');
assert.equal(panel.ui.memberBusy,true);assert.equal(activeDialog.fieldset.disabled,true);
assert.equal(activeDialog.closeButton.disabled,true);
ctx.closeMealPlannerDialog();assert.equal(activeDialog.open,true);
release({ok:true,json:async()=>({ok:true,member:{id:'child',name:'Younger child'}})});await pending;await flush();
assert.equal(panel.ui.memberBusy,false);assert.equal(activeDialog.fieldset.disabled,false);
assert.equal(panel.draft.members[1].name,'Younger child');assert.equal(panel.draft.notes,'Keep portions');
assert.equal(page.dataset.mealPlannerStale,'1');assert.equal(previewRefreshes,1);
assert.equal(refreshes.length,0,'Member edits must not replace an open planning form');
ctx.closeMealPlannerDialog();await flush();assert.equal(activeDialog.open,false);assert.equal(refreshes.length,1);
""")


def test_reopen_keeps_known_people_while_refresh_is_pending_or_fails():
    run_dialog(r"""
responseFactory=async()=>({ok:true,json:async()=>({ok:true,
 members:[{id:'nate',name:'Nate',default_portion:1,group_ids:['tyler']},{id:'gary',name:'Gary',default_portion:0.5,group_ids:['tyler']}],
 groups:[{id:'tyler',name:'Tyler'}]
})});
await open();const panel=await choose('recipe://bread');
ctx.closeMealPlannerDialog();
let release;responseFactory=()=>new Promise(resolve=>release=resolve);
await open('2026-10-09','lunch');
assert.equal(panel.ui.loading,true);
assert.deepEqual(plain(panel.draft.members.map(member=>member.name)),['Nate','Gary'],'Known people must not disappear before the refresh completes');
assert.equal(panel.draft.groups[0].name,'Tyler');
release({ok:false,json:async()=>({ok:false,error:'Member refresh unavailable'})});await flush();
assert.equal(panel.ui.loading,false);assert.equal(panel.ui.error,true);
assert.deepEqual(plain(panel.draft.members.map(member=>member.name)),['Nate','Gary'],'A failed refresh must retain the last loaded people');
assert.equal(panel.draft.singleDate,'2026-10-09');assert.deepEqual(plain(panel.draft.mealTypes),['lunch']);
""")


def test_fresh_dialog_refresh_updates_saved_defaults_without_overwriting_edits_made_while_loading():
    run_dialog(r"""
responseFactory=async()=>({ok:true,json:async()=>({ok:true,
 members:[{id:'nate',name:'Nate',default_portion:1,group_ids:['tyler']},{id:'gary',name:'Gary',default_portion:0.5,group_ids:['tyler']}],
 groups:[{id:'tyler',name:'Tyler'}]
})});
await open();const panel=await choose('recipe://bread');ctx.closeMealPlannerDialog();
let release;responseFactory=()=>new Promise(resolve=>release=resolve);
await open('2026-10-09','lunch');M.setPortionMode(panel.draft,'family');
M.setFamilyDefault(panel.draft,'nate','lunch',{servings:2.5});
M.setDayFamily(panel.draft,'2026-10-09','gary','lunch',{servings:0.25});
panel.draft.notes='Keep changes during refresh';
release({ok:true,json:async()=>({ok:true,
 members:[{id:'nate',name:'Nate',default_portion:3,group_ids:['tyler']},{id:'gary',name:'Gary',default_portion:0.75,group_ids:['tyler']}],
 groups:[{id:'tyler',name:'Tyler'}]
})});await flush();
assert.equal(panel.draft.familyDefaults.nate.lunch.servings,2.5,'A typed default must survive refresh');
assert.equal(panel.draft.familyDefaults.gary.lunch.servings,0.75,'An untouched new-plan default uses its latest saved value');
assert.equal(panel.draft.days['2026-10-09'].family.gary.lunch.servings,0.25,'An edited date retains its own override');
assert.equal(panel.draft.notes,'Keep changes during refresh');assert.equal(panel.ui.loading,false);
""")
