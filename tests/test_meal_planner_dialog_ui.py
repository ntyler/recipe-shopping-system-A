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
const classes = () => {const values=new Set();return {add(value){values.add(value);},remove(value){values.delete(value);},
 contains(value){return values.has(value);},toggle(value,present){if(present)values.add(value);else values.delete(value);}};};
const eventSurface=()=>({listeners:{},
 addEventListener(type,handler){(this.listeners[type] ||= new Set()).add(handler);},
 removeEventListener(type,handler){this.listeners[type]?.delete(handler);},
 dispatch(type,target,event={}){[...(this.listeners[type] || [])].forEach(handler=>handler({...event,target}));}
});
function node(extra={}) {
 return {hidden:false,disabled:false,dataset:{},innerHTML:'',textContent:'',value:'',handlers:{},classList:classes(),
  addEventListener(type,handler){(this.handlers[type] ||= []).push(handler);},
  focus(){this.focused=true;},setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},
  contains(target){return target===this;},querySelector(){return null;},querySelectorAll(){return [];},...extra};
}
let requests=[],refreshes=[],statuses=[],ingredientRenders=[],previewRefreshes=0;
let responseFactory=async()=>({ok:true,json:async()=>({ok:true,members:[{id:'adult',name:'Adult'},{id:'child',name:'Child'}]})});
let activeDialog;
const extraNodes=new Map();
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
 const dialog=node({open:false,options,recipe,form,fieldset,closeButton:close,helper,empty,status,radios:[],nodes:{},
  dataset:{mealDate:'2026-09-21'},
  showModal(){this.open=true;},close(){this.open=false;for(const handler of this.handlers.close || []) handler({});},
  querySelector(selector){
   if(selector.includes('mealPlannerScheduleForm'))return form;
   if(selector.includes('mealPlannerRecipeFields'))return fieldset;
   if(selector==='#mealPlannerRecipe' || selector.includes('recipe_url'))return recipe;
   if(selector.includes('data-meal-schedule-close'))return close;
   if(selector.includes('data-meal-servings-help'))return helper;
   if(selector.includes('data-meal-schedule-empty'))return empty;
   if(selector.includes('data-meal-plan-status'))return status;
   return this.nodes[selector] ||= node();
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
const ctx={console,Date,Set,AbortController,window:{...eventSurface(),innerWidth:800,innerHeight:600},document:{...eventSurface(),activeElement:null,
 getElementById(id){if(extraNodes.has(id))return extraNodes.get(id);return ({mealPlannerDialog:activeDialog,mealPlannerRecipe:activeDialog.recipe,
  mealPlannerRecipeFields:activeDialog.fieldset,mealPlannerScheduleForm:activeDialog.form,
  mealPlannerServingsHelp:activeDialog.helper,mealPlannerPage:page})[id] || activeDialog.querySelector('#'+id);},
 querySelector(selector){return activeDialog.querySelector(selector);},
 querySelectorAll(selector){return selector==='[data-meal-card-menu]'?[...extraNodes.values()].filter(node=>node.dataset.triggerId):[];},
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
const ok=data=>({ok:true,json:async()=>({ok:true,...data})});
const savedMeal=(overrides={})=>({id:'meal-1',date:'2026-10-07',meal_type:'dinner',recipe_url:'recipe://bread',
 recipe_name:'Corn Spoon Bread',planned_servings:3.5,portion_mode:'household',prep_notes:'Pack separately',
 ingredient_option_selections:{butter:'unsalted'},...overrides});
const savedBatch=()=>({id:'batch-1',recipe_url:'recipe://bread',recipe_name:'Corn Spoon Bread',portion_mode:'family',
 prep_notes:'Cook once for the family',batch_servings:12,ingredient_option_selections:{butter:'unsalted'},
 prep_steps:[{id:'prep-1',date:'2026-10-04',instruction:'Bake ahead',completed:true}]});
const savedAllocations=()=>[
 savedMeal({id:'meal-1',batch_id:'batch-1',date:'2026-10-05',meal_type:'lunch',portion_mode:'family',planned_servings:1.5,
  member_portions:[{member_id:'adult',name:'Adult',servings:1},{member_id:'child',name:'Child',servings:0.5}]}),
 savedMeal({id:'meal-2',batch_id:'batch-1',date:'2026-10-15',meal_type:'dinner',portion_mode:'family',planned_servings:2.25,
  member_portions:[{member_id:'adult',name:'Adult',servings:2},{member_id:'child',name:'Child',servings:0.25}]})
];
const card=(overrides={})=>node({dataset:{mealId:'meal-1',mealName:'Corn Spoon Bread',...overrides}});
function cardMenu(overrides={}) {
 const trigger=card({menuId:'meal-menu',...overrides});trigger.id='trigger-'+trigger.dataset.menuId;
 trigger.getBoundingClientRect=()=>({right:795,top:570,bottom:590});
 const firstAction=node();
 const menu=node({dataset:{triggerId:trigger.id},style:{},popoverOpen:false,
  matches(selector){return selector===':popover-open'&&this.popoverOpen;},
  showPopover(options){this.source=options?.source;this.popoverOpen=true;(this.handlers.toggle||[]).forEach(handler=>handler({newState:'open'}));},
  hidePopover(){this.popoverOpen=false;(this.handlers.toggle||[]).forEach(handler=>handler({newState:'closed'}));},
  contains(target){return target===this||target===firstAction;},
  getBoundingClientRect(){return {width:210,height:130};},
  querySelector(selector){return selector==='button'?firstAction:null;}
 });
 firstAction.closest=selector=>selector==='[data-meal-card-menu]'?menu:null;
 extraNodes.set(trigger.id,trigger);extraNodes.set(trigger.dataset.menuId,menu);
 return {trigger,menu,firstAction};
}
const openEdit=async(button=card(),scope='')=>{ctx.openMealPlannerEditDialog(button,scope);await flush();return activeDialog.mealPlanScheduleState.panel;};
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


def test_card_menu_toggle_positions_within_viewport_and_keyboard_dismissal_returns_focus():
    run_dialog(r"""
const {trigger,menu,firstAction}=cardMenu({batchId:'batch-1'});
assert.equal(ctx.toggleMealPlannerCardMenu(trigger),false);
assert.equal(menu.popoverOpen,true);assert.equal(menu.source,trigger);assert.equal(trigger['aria-expanded'],'true');
assert.equal(firstAction.focused,true);assert.equal(activeDialog.open,false);assert.equal(requests.length,0);
assert(Number.parseFloat(menu.style.left)>=8);assert(Number.parseFloat(menu.style.left)+210<=792);
assert(Number.parseFloat(menu.style.top)>=8);assert(Number.parseFloat(menu.style.top)+130<=592);
assert(Number.parseFloat(menu.style.top)<570,'A menu near the viewport bottom opens above its trigger');
ctx.toggleMealPlannerCardMenu(trigger);
assert.equal(menu.popoverOpen,false);assert.equal(trigger['aria-expanded'],'false');assert.equal(trigger.focused,true);
ctx.toggleMealPlannerCardMenu(trigger);let prevented=false;trigger.focused=false;
assert.equal(menu.handlers.toggle.length,1);assert.equal(menu.handlers.keydown.length,1,'Reopening must not duplicate keyboard handlers');
menu.handlers.keydown[0]({key:'Escape',preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(menu.popoverOpen,false);assert.equal(trigger.focused,true);assert.equal(trigger['aria-expanded'],'false');
ctx.toggleMealPlannerCardMenu(trigger);menu.hidePopover();
assert.equal(trigger['aria-expanded'],'false','Native light-dismiss notification synchronizes the trigger state');
assert.equal(requests.length,0);
""")


@pytest.mark.parametrize("scope", ["meal", "batch"])
def test_card_menu_edit_actions_close_before_loading_the_correct_saved_scope(scope):
    run_dialog(r"""
const scope=__SCOPE__,{trigger,menu,firstAction}=cardMenu({mealId:'meal-2',batchId:'batch-1'});
responseFactory=async(url)=>{
 assert.equal(menu.popoverOpen,false);assert.equal(trigger['aria-expanded'],'false');
 if(url==='/api/meal-plan/meal-2')return ok({meal:savedAllocations()[1],batch:savedBatch()});
 if(url==='/api/meal-plan/batches/batch-1')return ok({batch:savedBatch(),meals:savedAllocations()});
 if(url==='/api/meal-plan/members')return ok({members:[{id:'adult',name:'Adult'},{id:'child',name:'Child'}]});
 throw new Error('Unexpected request '+url);
};
ctx.toggleMealPlannerCardMenu(trigger);ctx.runMealPlannerCardAction(firstAction,scope);await flush();
const panel=activeDialog.mealPlanScheduleState.panel;
assert.equal(activeDialog.open,true);assert.equal(panel.edit.scope,scope);
assert.equal(panel.edit.id,scope==='meal'?'meal-2':'batch-1');
assert.equal(requests[0].url,scope==='meal'?'/api/meal-plan/meal-2':'/api/meal-plan/batches/batch-1');
assert.equal(activeDialog.querySelector('[data-meal-edit-scope]').hidden,true,'The menu already selected the edit scope');
assert.equal(activeDialog.mealPlanScheduleState.editOpener,trigger);
ctx.closeMealPlannerDialog();assert.equal(trigger.focused,true);assert.equal(requests.filter(request=>request.options?.method==='PATCH').length,0);
""".replace("__SCOPE__", repr(scope)))


def test_card_menu_remove_routes_original_meal_identity_without_deleting_until_confirmation():
    run_dialog(r"""
const {trigger,menu,firstAction}=cardMenu({mealId:'meal/2',batchId:'batch/1',mealName:'Bread <and soup>'});
const removals=[];ctx.openMealPlannerDeleteDialog=button=>{
 assert.equal(menu.popoverOpen,false);assert.equal(button['aria-expanded'],'false');
 removals.push(button);return false;
};
ctx.toggleMealPlannerCardMenu(trigger);
ctx.runMealPlannerCardAction(firstAction,'unknown');assert.equal(menu.popoverOpen,true);assert.equal(removals.length,0);
assert.equal(ctx.runMealPlannerCardAction(firstAction,'remove'),false);
assert.equal(removals.length,1);assert.equal(removals[0],trigger);
assert.equal(removals[0].dataset.mealId,'meal/2');assert.equal(removals[0].dataset.batchId,'batch/1');
assert.equal(removals[0].dataset.mealName,'Bread <and soup>');assert.equal(trigger.focused,true);
assert.equal(requests.length,0,'Opening the remove confirmation does not send a deletion request');
assert.equal(activeDialog.open,false);
""")


def test_card_menu_remove_entire_batch_routes_explicit_scope_only_for_batched_meals():
    run_dialog(r"""
const batched=cardMenu({menuId:'batch-menu',mealId:'meal/2',batchId:'batch/1'}),standalone=cardMenu({menuId:'single-menu',mealId:'single'}),removals=[];
ctx.openMealPlannerDeleteDialog=(button,scope='meal')=>{assert.equal(batched.menu.popoverOpen,false);removals.push({button,scope});return false;};
ctx.toggleMealPlannerCardMenu(batched.trigger);ctx.runMealPlannerCardAction(batched.firstAction,'remove-batch');
assert.equal(removals.length,1);assert.equal(removals[0].button,batched.trigger);assert.equal(removals[0].scope,'batch');
ctx.toggleMealPlannerCardMenu(standalone.trigger);ctx.runMealPlannerCardAction(standalone.firstAction,'remove-batch');
assert.equal(removals.length,1,'A standalone meal must never invoke batch removal');assert.equal(standalone.menu.popoverOpen,true);
ctx.runMealPlannerCardAction(standalone.firstAction,'remove');assert.equal(removals.length,2);assert.equal(removals[1].scope,'meal');
assert.equal(removals[1].button,standalone.trigger);assert.equal(requests.length,0);
""")


def test_card_shop_action_closes_menu_and_reviews_whole_batch_without_writing_items():
    run_dialog(r"""
const {trigger,menu,firstAction}=cardMenu({mealId:'meal/2',batchId:'batch/1'}),opened=[];
ctx.window.MealPlanShopping={open(selection,opener){
 assert.equal(menu.popoverOpen,false);assert.equal(trigger['aria-expanded'],'false');
 opened.push({selection:plain(selection),opener});
}};
ctx.toggleMealPlannerCardMenu(trigger);assert.equal(ctx.runMealPlannerCardAction(firstAction,'shop'),false);
assert.deepEqual(opened[0].selection,{batch_ids:['batch/1']});assert.equal(opened[0].opener,trigger);
assert.equal(activeDialog.open,false);assert.equal(requests.length,0,'Shopping is reviewed separately before items are committed');
ctx.document.activeElement=page;ctx.openMealPlanShopping();
assert.deepEqual(opened[1].selection,{week_start:'2026-09-21'});assert.equal(opened[1].opener,page);
""")


def test_card_menu_fallback_preserves_actions_and_dismisses_without_leaking_listeners():
    run_dialog(r"""
const {trigger,menu,firstAction}=cardMenu({batchId:'batch-1'});delete menu.showPopover;delete menu.hidePopover;
ctx.toggleMealPlannerCardMenu(trigger);
assert.equal(menu.classList.contains('is-fallback-open'),true);assert.equal(firstAction.focused,true);
assert.equal(activeDialog.open,false,'Opening the fallback must show the choices, not skip directly to editing');
assert.equal(ctx.document.listeners.pointerdown.size,1);assert.equal(ctx.document.listeners.scroll.size,1);assert.equal(ctx.window.listeners.resize.size,1);
ctx.document.dispatch('pointerdown',firstAction);assert.equal(menu.classList.contains('is-fallback-open'),true);
ctx.document.dispatch('scroll',menu);assert.equal(menu.classList.contains('is-fallback-open'),true,'Scrolling within the menu keeps it open');
trigger.focused=false;ctx.document.dispatch('pointerdown',node());
assert.equal(menu.classList.contains('is-fallback-open'),false);assert.equal(trigger['aria-expanded'],'false');
assert.equal(trigger.focused,false,'Outside dismissal must not steal focus from another control');
assert.equal(ctx.document.listeners.pointerdown.size,0);assert.equal(ctx.document.listeners.scroll.size,0);assert.equal(ctx.window.listeners.resize.size,0);
ctx.toggleMealPlannerCardMenu(trigger);ctx.window.dispatch('resize',ctx.window);assert.equal(menu.classList.contains('is-fallback-open'),false);
ctx.toggleMealPlannerCardMenu(trigger);ctx.document.dispatch('scroll',page);assert.equal(menu.classList.contains('is-fallback-open'),false);
const removed=[];ctx.openMealPlannerDeleteDialog=button=>{removed.push(button);return false;};
ctx.toggleMealPlannerCardMenu(trigger);ctx.runMealPlannerCardAction(firstAction,'remove');
assert.deepEqual(removed,[trigger]);assert.equal(menu.classList.contains('is-fallback-open'),false);assert.equal(requests.length,0);
assert.equal(ctx.document.listeners.pointerdown.size,0);assert.equal(ctx.window.listeners.resize.size,0);
""")


def test_opening_another_card_menu_closes_previous_menu_and_retains_one_dismissal_listener():
    run_dialog(r"""
const first=cardMenu({menuId:'first-menu',mealId:'first'}),second=cardMenu({menuId:'second-menu',mealId:'second'});
ctx.toggleMealPlannerCardMenu(first.trigger);assert.equal(first.menu.popoverOpen,true);
ctx.toggleMealPlannerCardMenu(second.trigger);
assert.equal(first.menu.popoverOpen,false);assert.equal(first.trigger['aria-expanded'],'false');
assert.equal(second.menu.popoverOpen,true);assert.equal(second.trigger['aria-expanded'],'true');
assert.equal(ctx.document.listeners.pointerdown.size,1);assert.equal(ctx.document.listeners.scroll.size,1);assert.equal(ctx.window.listeners.resize.size,1);
ctx.closeMealPlannerCardMenu(second.menu);
assert.equal(ctx.document.listeners.pointerdown.size,0);assert.equal(ctx.document.listeners.scroll.size,0);assert.equal(ctx.window.listeners.resize.size,0);
assert.equal(requests.length,0);
""")


def test_fallback_card_menu_escape_after_focus_leaves_menu_closes_and_restores_trigger_focus():
    run_dialog(r"""
const {trigger,menu}=cardMenu();delete menu.showPopover;delete menu.hidePopover;
const outside=node();let prevented=false;
ctx.toggleMealPlannerCardMenu(trigger);
ctx.document.activeElement=outside;outside.focus();trigger.focused=false;
assert.equal(ctx.document.listeners.keydown.size,1);
ctx.document.dispatch('keydown',outside,{key:'Tab',preventDefault(){throw new Error('Tab remains available outside the menu');}});
assert.equal(menu.classList.contains('is-fallback-open'),true);
ctx.document.dispatch('keydown',outside,{key:'Escape',preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(menu.classList.contains('is-fallback-open'),false);
assert.equal(trigger['aria-expanded'],'false');assert.equal(trigger.focused,true);
assert.equal(ctx.document.listeners.keydown.size,0);assert.equal(ctx.document.listeners.pointerdown.size,0);
assert.equal(ctx.document.listeners.scroll.size,0);assert.equal(ctx.window.listeners.resize.size,0);
ctx.toggleMealPlannerCardMenu(trigger);assert.equal(ctx.document.listeners.keydown.size,1,'Reopening installs one Escape listener');
ctx.document.dispatch('pointerdown',outside);assert.equal(ctx.document.listeners.keydown.size,0,'Outside dismissal also removes Escape handling');
trigger.focused=false;prevented=false;
ctx.document.dispatch('keydown',outside,{key:'Escape',preventDefault(){prevented=true;}});
assert.equal(trigger.focused,false);assert.equal(prevented,false,'A closed menu must not consume Escape elsewhere');
assert.equal(requests.length,0);
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


def test_edit_single_meal_loads_saved_values_locks_recipe_and_patches_then_refreshes_changed_date():
    run_dialog(r"""
responseFactory=async(url,options)=>{
 if(url==='/api/meal-plan/meal-1' && options?.method!=='PATCH')return ok({meal:savedMeal()});
 if(url==='/api/meal-plan/members')return ok({members:[{id:'adult',name:'Adult'},{id:'child',name:'Child'}]});
 throw new Error('Unexpected request '+url);
};
const panel=await openEdit();
assert.equal(activeDialog.open,true);assert.equal(panel.edit.scope,'meal');assert.equal(panel.edit.id,'meal-1');
assert.equal(panel.draft.singleDate,'2026-10-07');assert.deepEqual(plain(panel.draft.mealTypes),['dinner']);
assert.equal(M.summary(panel.draft).totalServings,3.5);assert.equal(panel.draft.notes,'Pack separately');
assert.equal(activeDialog.fieldset.hidden,true);assert.equal(activeDialog.fieldset.disabled,true);
assert.match(activeDialog.querySelector('[data-meal-schedule-description]').textContent,/Corn Spoon Bread/);
assert(activeDialog.form.innerHTML.includes('Save changes'));
activeDialog.recipe.value='recipe://soup';ctx.syncMealPlannerServingsFromRecipe();
assert.equal(panel.options.getContext().recipe_url,'recipe://bread','Editing a saved meal cannot change its recipe');
M.setSingleDate(panel.draft,'2026-11-03');panel.draft.notes='Updated meal-prep note';
requests=[];responseFactory=async(url,options)=>{
 assert.equal(url,'/api/meal-plan/meal-1');assert.equal(options.method,'PATCH');
 const body=JSON.parse(options.body);
 assert.equal(body.date,'2026-11-03');assert.equal(body.meal_type,'dinner');assert.equal(body.planned_servings,3.5);
 assert.equal(body.prep_notes,'Updated meal-prep note');assert(!('recipe_url' in body));assert(!('ingredient_option_selections' in body));
 return ok({meal:savedMeal({date:body.date,prep_notes:body.prep_notes})});
};
await submit(panel);assert.equal(requests.length,1);assert.equal(activeDialog.open,false);
assert.deepEqual(refreshes,['2026-11-03']);assert.equal(previewRefreshes,1);
""")


def test_edit_entire_prep_plan_fetches_all_dates_and_preserves_allocation_ids_and_completed_steps():
    run_dialog(r"""
responseFactory=async(url,options)=>{
 if(url==='/api/meal-plan/batches/batch-1' && options?.method!=='PATCH')return ok({batch:savedBatch(),meals:savedAllocations()});
 if(url==='/api/meal-plan/members')return ok({members:[{id:'adult',name:'Adult'},{id:'child',name:'Child'}]});
 throw new Error('Unexpected request '+url);
};
await openEdit(card({batchId:'batch-1'}));
assert.equal(activeDialog.open,true);assert.equal(requests.length,0,'A batch card must ask which scope to edit before fetching');
assert.equal(activeDialog.querySelector('[data-meal-edit-scope]').hidden,false);
await ctx.loadMealPlannerEdit('batch');await flush();const panel=activeDialog.mealPlanScheduleState.panel;
assert.equal(panel.edit.scope,'batch');assert.equal(panel.edit.id,'batch-1');
assert.deepEqual(plain(panel.draft.selectedDates),['2026-10-05','2026-10-15'],'Dates outside the displayed week must also load');
assert.equal(panel.draft.portionMode,'family');assert.equal(panel.draft.notes,'Cook once for the family');
assert.equal(panel.draft.days['2026-10-15'].family.child.dinner.servings,0.25);
assert.equal(panel.draft.prepSteps[0].id,'prep-1');assert.equal(panel.draft.prepSteps[0].completed,true);
M.setDayFamily(panel.draft,'2026-10-15','adult','dinner',{servings:1.75});
requests=[];responseFactory=async(url,options)=>{
 assert.equal(url,'/api/meal-plan/batches/batch-1');assert.equal(options.method,'PATCH');
 const body=JSON.parse(options.body);assert.equal(body.allocations.length,2);
 assert.deepEqual(body.allocations.map(meal=>meal.id),['meal-1','meal-2']);
 assert.deepEqual(body.allocations.map(meal=>meal.date),['2026-10-05','2026-10-15']);
 assert.equal(body.allocations[1].member_portions.find(member=>member.member_id==='adult').servings,1.75);
 assert.equal(body.allocations[1].member_portions.find(member=>member.member_id==='child').servings,0.25);
 assert.equal(body.prep_steps[0].id,'prep-1');assert(!('completed' in body.prep_steps[0]),'Preserve the latest server completion rather than overwriting it');
 assert(!('recipe_url' in body));assert(!('ingredient_option_selections' in body));
 return ok({batch:savedBatch(),meals:body.allocations});
};
await submit(panel);assert.equal(requests.length,1);assert.equal(activeDialog.open,false);
assert.deepEqual(refreshes,['2026-10-05']);
""")


def test_edit_one_meal_from_a_batch_cancel_does_not_save_or_edit_the_other_days():
    run_dialog(r"""
const meal=savedAllocations()[1];
responseFactory=async(url)=>{
 if(url==='/api/meal-plan/meal-2')return ok({meal,batch:savedBatch()});
 if(url==='/api/meal-plan/members')return ok({members:[{id:'adult',name:'Adult'},{id:'child',name:'Child'}]});
 throw new Error('Unexpected request '+url);
};
await openEdit(card({mealId:'meal-2',batchId:'batch-1'}));
await ctx.loadMealPlannerEdit('meal');await flush();const panel=activeDialog.mealPlanScheduleState.panel;
assert.equal(panel.edit.scope,'meal');assert.equal(panel.edit.id,'meal-2');
assert.deepEqual(plain(panel.draft.selectedDates),['2026-10-15']);
assert.deepEqual(plain(panel.draft.mealTypes),['dinner']);assert.equal(panel.draft.notes,'Pack separately');
assert.equal(panel.draft.prepSteps.length,0,'Editing one meal must not expose batch-wide prep steps');
panel.draft.notes='Uncommitted meal note';M.setDayFamily(panel.draft,'2026-10-15','child','dinner',{servings:2});
await panel.click({target:{closest:()=>({disabled:false,dataset:{scheduleAction:'cancel'}})}});
assert.equal(activeDialog.open,false);assert.equal(requests.filter(request=>request.options?.method==='PATCH').length,0);
assert.equal(requests.filter(request=>request.options?.method==='POST').length,0);assert.equal(refreshes.length,0);
assert.deepEqual(meal,savedAllocations()[1],'Hydration and cancel must not mutate the saved response');
""")


def test_edit_load_failure_and_incomplete_response_offer_retry_without_exposing_a_stale_form():
    run_dialog(r"""
responseFactory=async()=>({ok:false,json:async()=>({ok:false,error:'This meal could not be loaded.'})});
await openEdit();
assert.equal(activeDialog.open,true);assert.equal(activeDialog.form.hidden,true);
assert.equal(activeDialog.querySelector('[data-meal-edit-retry]').hidden,false);
assert.equal(activeDialog.mealPlanScheduleState.editLoading,false);
assert.deepEqual(statuses.at(-1),{message:'This meal could not be loaded.',error:true});
responseFactory=async()=>ok({meal:{id:'meal-1',date:'2026-10-07'}});
await ctx.loadMealPlannerEdit('meal');await flush();
assert.equal(activeDialog.form.hidden,true);assert.equal(activeDialog.querySelector('[data-meal-edit-retry]').hidden,false);
assert.match(statuses.at(-1).message,/incomplete/);assert.equal(statuses.at(-1).error,true);
responseFactory=async(url)=>url==='/api/meal-plan/members'?ok({members:[]}):ok({meal:savedMeal()});
await ctx.loadMealPlannerEdit('meal');await flush();
assert.equal(activeDialog.form.hidden,false);assert.equal(activeDialog.querySelector('[data-meal-edit-retry]').hidden,true);
assert.equal(activeDialog.querySelector('#mealPlannerDialogTitle').textContent,'Edit this meal');
assert.equal(activeDialog.mealPlanScheduleState.panel.draft.notes,'Pack separately');
assert.equal(requests.filter(request=>['PATCH','POST'].includes(request.options?.method)).length,0);
""")


def test_canceled_edit_request_cannot_replace_a_newer_edit_or_show_a_late_error():
    run_dialog(r"""
let releaseOld;
responseFactory=()=>new Promise(resolve=>releaseOld=resolve);
const firstCard=card();await openEdit(firstCard);
const oldSignal=requests[0].options.signal;
assert.equal(activeDialog.mealPlanScheduleState.editLoading,true);assert.equal(activeDialog.form.hidden,true);
ctx.closeMealPlannerDialog();assert.equal(activeDialog.open,false);assert.equal(oldSignal.aborted,true);assert.equal(firstCard.focused,true);
responseFactory=async(url)=>url==='/api/meal-plan/members'?ok({members:[]}):ok({meal:savedMeal({id:'meal-2',recipe_url:'recipe://soup',recipe_name:'Soup',prep_notes:'Soup note'})});
const panel=await openEdit(card({mealId:'meal-2',mealName:'Soup'}));
panel.draft.notes='Newly typed soup note';
releaseOld(ok({meal:savedMeal()}));await flush();
assert.equal(panel.edit.id,'meal-2');assert.equal(panel.options.getContext().recipe_url,'recipe://soup');
assert.equal(panel.draft.notes,'Newly typed soup note');assert.equal(activeDialog.form.hidden,false);
ctx.closeMealPlannerDialog();

let rejectOld;responseFactory=()=>new Promise((_resolve,reject)=>rejectOld=reject);
await openEdit(card({mealId:'meal-3'}));const abandoned=activeDialog;
activeDialog=makeDialog();responseFactory=async()=>ok({members:[]});
await open('2026-12-04','breakfast');const createPanel=await choose('recipe://bread');
createPanel.draft.notes='Current dialog draft';const statusCount=statuses.length;
rejectOld(new Error('Stale network error'));await flush();
assert.equal(createPanel.edit,null);assert.equal(createPanel.draft.singleDate,'2026-12-04');
assert.equal(createPanel.draft.notes,'Current dialog draft');assert.equal(activeDialog.form.hidden,false);
assert.equal(statuses.length,statusCount,'A replaced dialog must not show an old request failure');
assert.notEqual(activeDialog,abandoned);assert.equal(refreshes.length,0);
""")


def test_failed_edit_save_keeps_draft_and_locks_cancel_and_scope_until_request_completes():
    run_dialog(r"""
responseFactory=async(url)=>url==='/api/meal-plan/members'?ok({members:[]}):ok({meal:savedMeal()});
const panel=await openEdit();M.setSingleDate(panel.draft,'2026-11-03');panel.draft.notes='Keep this edit';
let release;requests=[];responseFactory=()=>new Promise(resolve=>release=resolve);
const pending=submit(panel);assert.equal(panel.ui.busy,true);assert.equal(activeDialog.closeButton.disabled,true);
ctx.closeMealPlannerDialog();assert.equal(activeDialog.open,true);
await ctx.loadMealPlannerEdit('meal');await submit(panel);assert.equal(requests.length,1);
assert.equal(requests[0].options.method,'PATCH');
release({ok:false,json:async()=>({ok:false,error:'Meal changed elsewhere. Try again.'})});await pending;
assert.equal(activeDialog.open,true);assert.equal(activeDialog.form.hidden,false);assert.equal(panel.ui.busy,false);
assert.equal(panel.edit.id,'meal-1');assert.equal(panel.draft.singleDate,'2026-11-03');assert.equal(panel.draft.notes,'Keep this edit');
assert.equal(activeDialog.fieldset.disabled,true,'Recipe must stay locked even after saving fails');
assert.equal(activeDialog.closeButton.disabled,false);assert.match(panel.ui.message,/Meal changed elsewhere/);
assert.equal(refreshes.length,0);assert.equal(previewRefreshes,0);
""")
