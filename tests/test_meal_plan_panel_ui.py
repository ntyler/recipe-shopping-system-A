"""Planning panel rendering and controller checks without claiming browser visual QA."""

from pathlib import Path
import shutil
import subprocess

import pytest


JS_ROOT = Path(__file__).resolve().parents[1] / "PushShoppingList/static/js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for panel logic checks")


def run_panel(script):
    bootstrap = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
let requests=[];
const ctx = {document:{activeElement:null},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({ok:true,members:[]})};}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const M = ctx.MealPlanSchedule, Panel = ctx.MealPlanPanel;
const plain = value => JSON.parse(JSON.stringify(value));
const members=[{id:'you',name:'You'},{id:'partner',name:'Partner'},{id:'child',name:'Child'}];
const form={hidden:true,innerHTML:'',handlers:{},nodes:{},details:[],checkedMeals:[],portionCells:[],numberInputs:[],valid:true,
 classList:{add(){}},addEventListener(type,handler){this.handlers[type]=handler;},
 contains(){return false;},scrollIntoView(){this.scrolled=true;},reportValidity(){return this.valid;},
 querySelectorAll(selector){
  if(selector==='details[data-schedule-day]')return this.details.filter(d=>d.dataset.scheduleDay);
  if(selector==='details[data-schedule-section]')return this.details.filter(d=>d.dataset.scheduleSection);
  if(selector==='[data-schedule-field="meal"]:checked')return this.checkedMeals;
  if(selector==='[data-portion-total]')return this.portionCells;
  if(selector==='input[type="number"][data-schedule-field]')return this.numberInputs;
  return [];
 },
 querySelector(selector){
  const section=/^\[data-schedule-section="([^"]+)"\]$/.exec(selector);
  if(section){const details=this.details.find(item=>item.dataset.scheduleSection===section[1]);if(details)return details;}
  return this.nodes[selector]||(this.nodes[selector]={textContent:'',innerHTML:'',disabled:false,focus(){}});
 }
};
let saved=[],canceled=0,membersChanged=0;
const options={today:'2026-10-05',servings:2,title:'Bread <script>bad()</script>',
 getContext:()=>({recipe_url:'recipe://bread',ingredient_option_selections:{butter:'bundle2'}}),
 onSaved:async(...args)=>saved.push(args),onCancel:()=>canceled++,onMembersChanged:()=>membersChanged++};
const panel=new Panel(form,options);
const click=(dataset,extra={})=>panel.click({target:{closest:()=>({dataset,disabled:false,...extra})}});
const field=(scheduleField,value='',extra={})=>({value,checked:false,type:'number',dataset:{scheduleField,...(extra.dataset||{})},hasAttribute:()=>false,...extra});
const submit=()=>panel.submit({preventDefault(){}});
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", str(JS_ROOT / "meal-plan-schedule.js"), str(JS_ROOT / "meal-plan-panel.js")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_family_schedule_rendering_totals_calendar_and_escaped_user_text():
    run_panel(r"""
assert(form.innerHTML.includes('One day'));assert(form.innerHTML.includes('Date range'));assert(form.innerHTML.includes('Select days'));
assert(form.innerHTML.includes('Bread &lt;script&gt;bad()&lt;/script&gt;'));assert(!form.innerHTML.includes('<script>'));
M.setMembers(panel.draft,members);M.setDates(panel.draft,['2026-10-05','2026-10-07','2026-10-09']);
M.setMeals(panel.draft,['breakfast','dinner']);M.setPortionMode(panel.draft,'family');
M.setFamilyDefault(panel.draft,'partner','dinner',{enabled:false});
for(const meal of ['breakfast','dinner'])M.setFamilyDefault(panel.draft,'child',meal,{servings:0.5});
M.setDayNotes(panel.draft,'2026-10-07','Pack <lunch> & "water"');
panel.draft.notes='Shared </textarea><script>alert(1)</script>';
panel.draft.prepSteps=[{date:'2026-10-04',instruction:'Chop <onions>'}];
panel.ui.openDays.add('2026-10-07');panel.render();
assert(form.innerHTML.includes('3 days · 6 meals · 12 servings'));assert(form.innerHTML.includes('Add 6 meals'));
assert(form.innerHTML.includes('You: 6 servings · Partner: 3 servings · Child: 3 servings'));
assert(form.innerHTML.includes('Breakfast: 2½ · Dinner: 1½'));assert(form.innerHTML.includes('Pack &lt;lunch&gt; &amp; &quot;water&quot;'));
const defaultFooter=form.innerHTML.match(/<tfoot>([\s\S]*?)<\/tfoot>/)[1];
assert(defaultFooter.includes('Per day'));assert.match(defaultFooter,/<td[^>]*>2½ servings<\/td>/);assert.match(defaultFooter,/<td[^>]*>1½ servings<\/td>/);
assert(form.innerHTML.includes('&lt;/textarea&gt;&lt;script&gt;alert(1)&lt;/script&gt;'));assert(!form.innerHTML.includes('<script>'));
assert(form.innerHTML.includes('Chop &lt;onions&gt;'));assert.equal((form.innerHTML.match(/data-schedule-day=/g)||[]).length,3);
assert.equal((form.innerHTML.match(/data-schedule-action="date"/g)||[]).length,42);
assert.equal((form.innerHTML.match(/data-schedule-action="date"[^>]+aria-pressed="true"/g)||[]).length,3);
assert.match(form.innerHTML,/data-schedule-day="2026-10-07" open/);
assert.match(form.innerHTML,/data-schedule-field="family"[^>]+data-member="partner"[^>]+value="1" disabled/);
""")


def test_controller_dates_multiple_meals_portions_and_override_reapplication():
    run_panel(r"""
await click({scheduleMode:'range'});
panel.change({target:field('start-date','2026-10-30')});panel.change({target:field('end-date','2026-11-02')});
assert.deepEqual(plain(panel.draft.selectedDates),['2026-10-30','2026-10-31','2026-11-01','2026-11-02']);
form.checkedMeals=[{dataset:{meal:'breakfast'}},{dataset:{meal:'dinner'}}];
panel.change({target:field('meal','',{type:'checkbox',checked:true})});
assert.deepEqual(plain(panel.draft.mealTypes),['breakfast','dinner']);
panel.input({target:field('household','0.5',{dataset:{scheduleField:'household',meal:'breakfast'}})});
assert.equal(M.summary(panel.draft).totalServings,10);
assert(form.nodes['[data-schedule-summary]'].innerHTML.includes('4 days · 8 meals · 10 servings'));
panel.change({target:field('day-meal','',{type:'checkbox',checked:false,dataset:{scheduleField:'day-meal',meal:'dinner',date:'2026-10-31'}})});
assert.equal(M.summary(panel.draft).mealCount,7);
panel.change({target:field('day-household','1.5',{dataset:{scheduleField:'day-household',meal:'breakfast',date:'2026-10-31'}})});
panel.change({target:field('household','1',{dataset:{scheduleField:'household',meal:'breakfast'}})});
assert.equal(panel.draft.days['2026-10-31'].household.breakfast,'1.5');
assert.equal(panel.draft.days['2026-10-31'].mealEnabled.dinner,false);
assert(form.innerHTML.includes('Adjusted for this day.'));
await click({scheduleMode:'days'});await click({scheduleAction:'date',date:'2026-10-31'});
assert.equal(panel.draft.days['2026-10-31'].household.breakfast,'1.5');
await click({scheduleAction:'apply'});
assert.equal(panel.draft.days['2026-10-31'].household.breakfast,'1');
assert.equal(panel.draft.days['2026-10-31'].mealEnabled.dinner,true);
await click({scheduleAction:'month',direction:'1'});assert.equal(panel.draft.calendarMonth,'2026-11');
await click({scheduleAction:'cancel'});assert.equal(form.hidden,true);assert.equal(canceled,1);
""")


def test_family_toggle_rename_and_member_errors_retain_inputs():
    run_panel(r"""
await panel.open();assert.equal(panel.ui.membersLoaded,true);assert(form.scrolled);
M.setMembers(panel.draft,members);await click({schedulePortionMode:'family'});
panel.change({target:field('family-enabled','',{type:'checkbox',checked:false,dataset:{scheduleField:'family-enabled',member:'partner',meal:'dinner'}})});
assert.equal(M.summary(panel.draft).totalServings,2);
requests=[];panel.ui.newName='   ';await click({scheduleAction:'add-member'});
assert.equal(requests.length,0);assert.equal(panel.ui.error,true);assert.match(panel.ui.message,/name/);
panel.ui.newName='  Guest  ';
let release;ctx.fetch=(url,options)=>{requests.push({url,options});return new Promise(resolve=>release=resolve);};
const pending=click({scheduleAction:'add-member'});assert.equal(panel.ui.memberBusy,true);
assert.match(form.innerHTML,/<fieldset disabled>/);
await click({scheduleAction:'add-member'});assert.equal(requests.length,1,'Repeated member clicks are suppressed');
release({ok:false,json:async()=>({ok:false,error:'A member with this name already exists.'})});await pending;
assert.equal(panel.ui.newName,'  Guest  ');assert.equal(panel.ui.memberBusy,false);assert.equal(panel.draft.members.length,3);
assert.match(panel.ui.message,/already exists/);
ctx.fetch=async(url,options)=>({ok:true,json:async()=>({ok:true,member:{id:'guest',name:JSON.parse(options.body).name}})});
await click({scheduleAction:'add-member'});assert.equal(panel.ui.newName,'');assert.equal(panel.draft.members[3].name,'Guest');assert.equal(membersChanged,1);
panel.ui.names.you='You renamed';
ctx.fetch=async(url,options)=>{assert.equal(options.method,'PATCH');assert.equal(url,'/api/meal-plan/members/you');return {ok:true,json:async()=>({ok:true,member:{id:'you',name:'You renamed'}})};};
await click({scheduleAction:'save-member',member:'you'});
assert.equal(panel.draft.members[0].name,'You renamed');assert.equal(panel.draft.days['2026-10-05'].family.partner.dinner.enabled,false);
assert.equal(panel.ui.names.you,undefined);assert.equal(membersChanged,2);
""")


def test_member_load_failure_can_retry_without_erasing_schedule():
    run_panel(r"""
M.setDates(panel.draft,['2026-10-05','2026-10-07']);
panel.draft.notes='Keep batch notes';
ctx.fetch=async()=>{throw new Error('Network down');};
await panel.open();assert.equal(panel.ui.membersLoaded,false);assert.equal(panel.ui.loading,false);
assert.match(panel.ui.message,/retry or use household totals/);
assert(form.innerHTML.includes('Retry loading members'));
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});
await click({scheduleAction:'retry-members'});
assert.equal(panel.ui.membersLoaded,true);assert.equal(panel.ui.error,false);
assert.equal(panel.draft.notes,'Keep batch notes');assert.equal(panel.draft.selectedDates.length,2);
""")


def test_invalid_plan_and_save_failure_never_reset_draft_and_guard_repeated_submit():
    run_panel(r"""
panel.form.hidden=false;
M.setHouseholdDefault(panel.draft,'dinner','');await submit();assert.equal(requests.length,0);
assert.equal(panel.ui.error,true);assert.equal(panel.draft.householdDefaults.dinner,'');
M.setHouseholdDefault(panel.draft,'dinner','0.5');
panel.draft.notes='Keep notes';panel.draft.prepSteps=[{date:'2026-10-04',instruction:'Chop'}];
M.setDayNotes(panel.draft,'2026-10-05','Keep per-day note');
let release;ctx.fetch=(url,options)=>{requests.push({url,options});return new Promise(resolve=>release=resolve);};
const pending=submit();assert.equal(panel.ui.busy,true);assert.match(form.innerHTML,/<fieldset disabled>/);
await submit();assert.equal(requests.length,1);
release({ok:false,json:async()=>({ok:false,error:'That meal slot is already planned.'})});await pending;
assert.equal(panel.ui.busy,false);assert.equal(form.hidden,false);assert.equal(saved.length,0);
assert.equal(panel.draft.householdDefaults.dinner,'0.5');assert.equal(panel.draft.notes,'Keep notes');
assert.equal(panel.draft.prepSteps[0].instruction,'Chop');assert.equal(panel.draft.days['2026-10-05'].notes,'Keep per-day note');
assert.match(panel.ui.message,/already planned/);
ctx.fetch=async()=>{throw new Error('Connection interrupted');};await submit();
assert.equal(panel.ui.busy,false);assert.equal(panel.ui.error,true);assert.equal(panel.draft.notes,'Keep notes');
assert.equal(form.hidden,false);assert.match(panel.ui.message,/Connection interrupted/);
""")


def test_successful_save_sends_family_allocations_and_resets_before_refresh_callback():
    run_panel(r"""
M.setMembers(panel.draft,members);M.setPortionMode(panel.draft,'family');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);M.setMeals(panel.draft,['breakfast','dinner']);
M.setFamilyDefault(panel.draft,'child','dinner',{servings:0.5});
panel.ui.openDays.add('2026-10-07');panel.draft.notes='Shared prep notes';
ctx.fetch=async(url,options)=>{
 requests.push({url,options});assert.equal(url,'/api/meal-plan/batches');assert.equal(options.method,'POST');
 const body=JSON.parse(options.body);assert.equal(body.recipe_url,'recipe://bread');
 assert.deepEqual(body.ingredient_option_selections,{butter:'bundle2'});assert.equal(body.portion_mode,'family');
 assert.equal(body.allocations.length,4);assert.equal(body.allocations[1].member_portions[2].servings,0.5);
 assert(body.allocations.every(a=>!('planned_servings' in a)));assert(!('batch_servings' in body));
 assert.equal(body.prep_notes,'Shared prep notes');assert(!('recipe_notes' in body));
 return {ok:true,json:async()=>({ok:true,batch:{id:'saved'}})};
};
options.onSaved=async(result,date)=>{
 assert.equal(result.batch.id,'saved');assert.equal(date,'2026-10-05');
 assert.equal(form.hidden,true);assert.equal(panel.ui.busy,false);assert.equal(panel.ui.error,false);
 assert.equal(panel.draft.notes,'');assert.equal(panel.draft.members.length,3);assert.equal(panel.ui.membersLoaded,false);assert.equal(panel.ui.openDays.size,0);
 assert.equal(panel.ui.refreshMemberDefaults,true,'Fresh plan refreshes saved defaults while keeping cached people visible');
 assert.equal(panel.draft.familyDefaults.child.dinner.servings,1,'Saved plan portion overrides do not leak into a new plan');
 saved.push(result);
};
await submit();assert.equal(requests.length,1);assert.equal(saved.length,1);assert.equal(panel.ui.message,'Meal plan saved.');
""")


def test_refresh_callback_failure_does_not_misrepresent_saved_plan_as_failed_request():
    run_panel(r"""
panel.draft.notes='Already persisted';
ctx.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({ok:true,batch:{id:'saved'}})};};
options.onSaved=async()=>{throw new Error('Planner refresh unavailable');};
await submit();
assert.equal(requests.length,1);assert.equal(form.hidden,false);assert.equal(panel.ui.busy,false);
assert.equal(panel.ui.message,'Meal plan saved. Reload to see the updated schedule.');
assert(form.innerHTML.includes('Meal plan saved. Reload to see the updated schedule.'));
assert.equal(panel.draft.notes,'','A failed refresh must not retain the saved plan for accidental resubmission');
""")


def test_new_prep_task_expands_closed_section_and_minus_never_increases_portions():
    run_panel(r"""
const details={dataset:{scheduleSection:'prep'},open:false};form.details=[details];
await click({scheduleAction:'add-prep'});
assert.equal(panel.draft.prepSteps.length,1);
assert.match(form.innerHTML,/data-schedule-section="prep" open/,'The newly added preparation task is visible');
const input=field('household','0.25',{dataset:{scheduleField:'household',meal:'dinner'}});
M.setHouseholdDefault(panel.draft,'dinner',0.25);
await click({scheduleAction:'step',direction:'-1'},{parentElement:{querySelector:()=>input}});
assert(Number(input.value)>0);assert(Number(input.value)<=0.25,'Minus must not increase a fractional portion');
assert.equal(Number(panel.draft.householdDefaults.dinner),Number(input.value));
""")


def test_apply_controls_appear_only_for_customized_days_and_update_without_replacing_inputs():
    run_panel(r"""
M.setMembers(panel.draft,members);M.setPortionMode(panel.draft,'family');panel.render();
assert.match(form.innerHTML,/<div data-schedule-apply hidden>/);
let renders=0;const realRender=panel.render.bind(panel);panel.render=()=>{renders++;realRender();};
panel.input({target:field('day-family','0.5',{dataset:{scheduleField:'day-family',member:'child',meal:'dinner',date:'2026-10-05'}})});
assert.equal(renders,0,'Typing a per-day override should not replace the focused input');
assert.equal(form.nodes['[data-schedule-apply]'].hidden,false);
assert.equal(M.summary(panel.draft).days[0].customized,true);
await click({scheduleAction:'apply'});assert.equal(M.summary(panel.draft).days[0].customized,false);
assert.match(form.innerHTML,/<div data-schedule-apply hidden>/);
panel.updateTotals();assert.equal(form.nodes['[data-schedule-apply]'].hidden,true);
""")


def test_typing_and_blur_preserve_controls_while_updating_inherited_portions_and_totals():
    run_panel(r"""
M.setMembers(panel.draft,members);M.setPortionMode(panel.draft,'family');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);
M.setDayFamily(panel.draft,'2026-10-07','child','dinner',{servings:0.25});
panel.render();
const active=field('family','0.50',{dataset:{scheduleField:'family',member:'child',meal:'dinner'}});
const inherited=field('day-family','1',{dataset:{scheduleField:'day-family',member:'child',meal:'dinner',date:'2026-10-05'}});
const overridden=field('day-family','0.25',{dataset:{scheduleField:'day-family',member:'child',meal:'dinner',date:'2026-10-07'}});
form.numberInputs=[active,inherited,overridden];
form.portionCells=[{dataset:{portionTotal:'dinner',date:''}},{dataset:{portionTotal:'dinner',date:'2026-10-05'}},{dataset:{portionTotal:'dinner',date:'2026-10-07'}}];
let renders=0;panel.render=()=>{renders++;};
panel.input({target:active});
assert.equal(renders,0,'Typing must preserve the active input and adjacent action buttons');
assert.equal(active.value,'0.50','Active input text is retained while typing');
assert.equal(inherited.value,'0.50');assert.equal(Number(overridden.value),0.25,'Date overrides are not overwritten');
assert.deepEqual(form.portionCells.map(cell=>cell.textContent),['2½ servings','2½ servings','2¼ servings']);
assert(form.nodes['[data-schedule-summary]'].innerHTML.includes('2 days · 2 meals · 4¾ servings'));
assert.equal(form.nodes['[data-day-total="2026-10-05"]'].textContent,'2½ servings');
assert.equal(form.nodes['[data-day-total="2026-10-07"]'].textContent,'2¼ servings');
panel.change({target:active});assert.equal(renders,0,'Blur must not replace the button receiving the following click');
const note=field('notes','Keep <my> note',{type:'text'});
panel.input({target:note});panel.change({target:note});assert.equal(renders,0);assert.equal(panel.draft.notes,'Keep <my> note');
const ownPortion=field('day-family','0.75',{dataset:{scheduleField:'day-family',member:'child',meal:'dinner',date:'2026-10-05'}});
panel.input({target:ownPortion});panel.change({target:ownPortion});assert.equal(renders,0);
assert.equal(panel.draft.days['2026-10-05'].overrides.family,true);
assert.equal(form.portionCells[1].textContent,'2¾ servings');
assert.equal(form.nodes['[data-day-default-status="2026-10-05"]'].textContent,'Adjusted for this day.');
""")
