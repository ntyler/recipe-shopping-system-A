"""Exercise the shared planning model in Node without substituting browser access."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "PushShoppingList/static/js/meal-plan-schedule.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for scheduling logic checks")


def test_saved_single_meal_keeps_allocations_when_date_is_cleared_then_date_and_meal_change():
    run_model(r"""
const meal={id:'meal1',date:'2026-10-05',meal_type:'dinner',portion_mode:'family',planned_servings:1.25,prep_notes:'Pack cold',
 member_portions:[{member_id:'former',name_snapshot:'Former eater',servings:0.75},{member_id:'you',name:'You',servings:0.5}]};
const saved=JSON.stringify(meal),edited=M.fromSaved({meal},'meal',{members});
assert.equal(edited.dateMode,'single');assert.equal(edited.portionMode,'family');assert.equal(edited.notes,'Pack cold');
assert.equal(M.summary(edited).totalServings,1.25);assert.equal(edited.familyDefaults.partner.dinner.enabled,false);
M.setMembers(edited,[...members,{id:'new',name:'New person'}]);
assert.equal(edited.members.find(member=>member.id==='former').archived,true);
assert.equal(edited.familyDefaults.new.dinner.enabled,false);assert.equal(M.summary(edited).totalServings,1.25);
M.setSingleDate(edited,'');assert.equal(M.summary(edited).valid,false);
M.setSingleDate(edited,'2026-11-02');M.setMeals(edited,['breakfast']);
const allocation=plain(M.payload(edited).allocations[0]);
assert.deepEqual(allocation,{id:'meal1',date:'2026-11-02',meal_type:'breakfast',portion_mode:'family',prep_notes:'Pack cold',
 member_portions:[{member_id:'you',servings:0.5},{member_id:'former',servings:0.75}]});
assert.equal(M.summary(edited).mealCount,1);assert.equal(JSON.stringify(meal),saved);
""")


def test_saved_batch_roundtrip_preserves_mixed_modes_individual_notes_ids_and_completed_prep():
    run_model(r"""
const meals=[{id:'breakfast1',date:'2026-10-05',meal_type:'breakfast',portion_mode:'family',planned_servings:0.5,prep_notes:'Pack breakfast',member_portions:[{member_id:'child',name:'Child',servings:0.5}]},
 {id:'dinner1',date:'2026-10-05',meal_type:'dinner',portion_mode:'household',planned_servings:3,prep_notes:'Share at dinner',member_portions:[]},
 {id:'later',date:'2026-11-07',meal_type:'lunch',portion_mode:'family',planned_servings:1,prep_notes:'For former member',member_portions:[{member_id:'former',name_snapshot:'Former',servings:1}]}];
const batch={id:'batch1',portion_mode:'family',prep_notes:'Cook once',batch_servings:6,prep_steps:[{id:'prep1',date:'2026-10-04',instruction:'Bake',completed:true}],allocations:meals};
const edited=M.fromSaved({batch},'batch',{members});
M.setMembers(edited,members);M.setGroups(edited,[]);
M.setPortionMode(edited,'family');
let payload=plain(M.payload(edited));
assert.equal(payload.allocations.length,3);assert.equal(M.summary(edited).totalServings,4.5);
assert.deepEqual(payload.allocations.map(item=>[item.id,item.portion_mode,item.prep_notes]),[
 ['breakfast1','family','Pack breakfast'],['dinner1','household','Share at dinner'],['later','family','For former member']]);
assert.equal(payload.allocations[0].member_portions[0].servings,0.5);assert.equal(payload.allocations[1].planned_servings,3);
assert.equal(edited.prepSteps[0].completed,true);
assert.deepEqual(payload.prep_steps,[{id:'prep1',date:'2026-10-04',instruction:'Bake'}],'Keep completion server-owned so another screen can finish this task while editing');
M.setMealNotes(edited,'2026-10-05','dinner','');edited.notes='Updated batch note';
payload=plain(M.payload(edited));assert.equal(payload.allocations[0].prep_notes,'Pack breakfast');assert.equal(payload.allocations[1].prep_notes,'');
assert.equal(payload.prep_notes,'Updated batch note');
M.setDates(edited,['2026-10-05','2026-11-07','2026-11-08']);
M.setDayFamily(edited,'2026-11-08','former','dinner',{enabled:true,servings:1});
assert.equal(M.summary(edited).valid,false);assert.match(M.summary(edited).errors.join(' '),/archived/);
assert.throws(()=>M.payload(edited),/archived/);
""")


def test_invalid_or_duplicate_saved_slots_are_rejected_instead_of_silently_collapsed():
    run_model(r"""
assert.throws(()=>M.fromSaved({meal:{id:'meal1',date:'bad',meal_type:'dinner'}},'meal'),/could not be loaded/);
const meal={id:'meal1',date:'2026-10-05',meal_type:'dinner',planned_servings:2};
assert.throws(()=>M.fromSaved({batch:{id:'batch1'},meals:[meal,{...meal,id:'meal2'}]},'batch'),/multiple meals in the same slot/);
""")


def test_edit_batch_new_dates_use_earliest_saved_active_portions_and_keep_existing_days_exact():
    run_model(r"""
const meals=[{id:'later',date:'2026-10-07',meal_type:'dinner',portion_mode:'family',planned_servings:3.5,member_portions:[{member_id:'you',name:'You',servings:3.5}]},
 {id:'first',date:'2026-10-05',meal_type:'dinner',portion_mode:'family',planned_servings:1.5,member_portions:[{member_id:'you',name:'You',servings:0.5},{member_id:'former',name:'Former',servings:1}]}];
const edited=M.fromSaved({batch:{id:'batch1',portion_mode:'family'},meals},'batch');
M.setMembers(edited,[{id:'you',name:'You',default_portion:1},{id:'new',name:'New person',default_portion:2}]);
assert.equal(edited.familyDefaults.you.dinner.enabled,true);assert.equal(edited.familyDefaults.you.dinner.servings,0.5);
assert.equal(edited.familyDefaults.former.dinner.enabled,false);assert.equal(edited.familyDefaults.new.dinner.enabled,false);
M.setDates(edited,['2026-10-05','2026-10-07','2026-10-09']);
let payload=plain(M.payload(edited));
assert.deepEqual(payload.allocations[0].member_portions,[{member_id:'you',servings:0.5},{member_id:'former',servings:1}]);
assert.deepEqual(payload.allocations[1].member_portions,[{member_id:'you',servings:3.5}]);
assert.deepEqual(payload.allocations[2].member_portions,[{member_id:'you',servings:0.5}]);
M.setFamilyDefault(edited,'you','dinner',{servings:0.75});M.setMembers(edited,[{id:'you',name:'Renamed',default_portion:2}]);
assert.equal(edited.familyDefaults.you.dinner.servings,0.75);assert.equal(edited.days['2026-10-05'].family.you.dinner.servings,0.5);
assert.equal(edited.days['2026-10-09'].family.you.dinner.servings,0.75);
""")


def run_model(script, timezone="America/Indiana/Indianapolis"):
    bootstrap = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const M = ctx.MealPlanSchedule;
const plain = value => JSON.parse(JSON.stringify(value));
const members = [{id:'you',name:'You'},{id:'partner',name:'Partner'},{id:'child',name:'Child'}];
const draft = M.create({today:'2026-10-05', servings:2, members});
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script, str(SOURCE)],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "TZ": timezone},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_three_days_two_meals_family_portions_and_payload():
    run_model(r"""
M.setDates(draft,['2026-10-05','2026-10-07','2026-10-09']);
M.setMeals(draft,['breakfast','dinner']);
M.setPortionMode(draft,'family');
M.setFamilyDefault(draft,'partner','dinner',{enabled:false});
for (const meal of ['breakfast','dinner']) M.setFamilyDefault(draft,'child',meal,{servings:0.5});
const totals = plain(M.summary(draft));
assert.equal(totals.valid,true); assert.equal(totals.dayCount,3); assert.equal(totals.mealCount,6);
assert.equal(totals.totalServings,12);
assert.deepEqual(totals.memberTotals,{you:6,partner:3,child:3});
for(const day of totals.days) {
 assert.equal(day.totalServings,4);
 assert.deepEqual(day.meals.map(meal=>meal.planned_servings),[2.5,1.5]);
}
draft.notes='Cook one batch'; draft.prepSteps=[{date:'2026-10-04',instruction:'Chop vegetables'}];
M.setDayNotes(draft,'2026-10-07','Pack for work');
const payload=plain(M.payload(draft));
assert.equal(payload.portion_mode,'family'); assert.equal(payload.allocations.length,6);
assert(!('batch_servings' in payload),'The backend derives the batch total');
assert(payload.allocations.every(meal=>!('planned_servings' in meal)),'The backend derives member totals');
assert.deepEqual(payload.allocations[1].member_portions,[{member_id:'you',servings:1},{member_id:'child',servings:0.5}]);
assert.equal(payload.allocations[2].prep_notes,'Pack for work');
assert.equal(payload.prep_notes,'Cook one batch');assert.equal(payload.prep_steps[0].instruction,'Chop vegetables');
assert(!('recipe_notes' in payload));
""")


@pytest.mark.parametrize("timezone", ["America/Indiana/Indianapolis", "America/Los_Angeles", "Pacific/Auckland"])
def test_local_calendar_dates_cross_month_year_and_daylight_savings(timezone):
    run_model(r"""
assert.deepEqual(plain(M.dateRange('2026-12-30','2027-01-02')),['2026-12-30','2026-12-31','2027-01-01','2027-01-02']);
assert.deepEqual(plain(M.dateRange('2026-03-07','2026-03-10')),['2026-03-07','2026-03-08','2026-03-09','2026-03-10']);
assert.equal(M.formatDate(M.parseDate('2026-11-01')),'2026-11-01');
assert.equal(M.parseDate('2026-02-29'),null); assert.equal(M.parseDate('2024-02-29').getHours(),12);
assert.equal(M.parseDate('2026-10-05T00:00:00Z'),null);assert.equal(M.parseDate('0000-01-01'),null);
assert.deepEqual(plain(M.dateRange('2026-10-09','2026-10-05')),[]);
assert.equal(M.shiftMonth('2026-12',1),'2027-01');assert.equal(M.shiftMonth('2026-01',-1),'2025-12');
const calendar=M.calendarMonth('2026-10');assert.equal(calendar.days.length,42);
assert.equal(calendar.days[0].date,'2026-09-28');assert.equal(calendar.days[0].inMonth,false);
assert.equal(calendar.days[3].date,'2026-10-01');assert.equal(calendar.days[3].inMonth,true);
assert.equal(new Set(calendar.days.map(day=>day.date)).size,42);
M.setDateMode(draft,'range');M.setRange(draft,'2026-12-30','2027-01-02');assert.equal(M.summary(draft).dayCount,4);
M.setRange(draft,'2026-12-30','2026-12-29');assert.match(M.summary(draft).errors[0],/on or after/);
M.setRange(draft,'','2027-01-02');assert.match(M.summary(draft).errors[0],/valid start and end/);
""", timezone)


def test_defaults_preserve_date_overrides_and_reapply_only_selected_dates():
    run_model(r"""
M.setDates(draft,['2026-10-05','2026-10-07','2026-10-09']);
M.setMeals(draft,['breakfast','dinner']);
M.setDayHousehold(draft,'2026-10-07','breakfast',0.5);
M.setDayMeal(draft,'2026-10-07','dinner',false);
M.setDayNotes(draft,'2026-10-07','Keep this date note');
M.setHouseholdDefault(draft,'breakfast',3);M.setMeals(draft,['breakfast','lunch','dinner']);
assert.equal(draft.days['2026-10-05'].household.breakfast,3);
assert.equal(draft.days['2026-10-07'].household.breakfast,0.5);
assert.equal(draft.days['2026-10-07'].mealEnabled.dinner,false);
assert.equal(draft.days['2026-10-07'].mealEnabled.lunch,false);
assert.equal(M.summary(draft).days[1].customized,true);
M.setDateMode(draft,'range');M.setRange(draft,'2026-10-06','2026-10-08');
assert.equal(draft.days['2026-10-07'].household.breakfast,0.5);
M.setDateMode(draft,'single');M.setSingleDate(draft,'2026-10-05');M.applyDefaults(draft);
assert.equal(draft.days['2026-10-07'].household.breakfast,0.5,'Reapply affects only selected dates');
M.setDateMode(draft,'days');
assert.deepEqual(plain(draft.selectedDates),['2026-10-05','2026-10-07','2026-10-09']);
M.applyDefaults(draft);assert.equal(draft.days['2026-10-07'].household.breakfast,3);
assert.equal(draft.days['2026-10-07'].mealEnabled.dinner,true);
assert.equal(M.summary(draft).days[1].customized,false);
assert.equal(draft.days['2026-10-07'].notes,'Keep this date note');
M.toggleDate(draft,'2026-10-05',false);assert.equal(draft.selectedDates.length,2);
M.toggleDate(draft,'2026-10-05',true);assert.equal(draft.selectedDates.length,3);
""")


def test_family_modes_independent_and_new_or_renamed_members_preserve_allocations():
    run_model(r"""
M.setDayHousehold(draft,'2026-10-05','dinner',4);
M.setPortionMode(draft,'family');
M.setDayFamily(draft,'2026-10-05','child','dinner',{servings:0.5});
M.setFamilyDefault(draft,'child','dinner',{servings:1.5});
assert.equal(draft.days['2026-10-05'].family.child.dinner.servings,0.5);
M.setMembers(draft,[{id:'you',name:'New name'},members[1],members[2],{id:'guest',name:'Guest'}]);
assert.equal(draft.members[0].name,'New name');
assert.equal(draft.days['2026-10-05'].family.child.dinner.servings,0.5);
assert.equal(draft.days['2026-10-05'].family.guest.dinner.servings,1);
M.applyDefaults(draft);assert.equal(draft.days['2026-10-05'].family.child.dinner.servings,1.5);
M.setPortionMode(draft,'household');assert.equal(M.summary(draft).totalServings,4);
const household=plain(M.payload(draft));assert.equal(household.allocations[0].planned_servings,4);
assert(!('member_portions' in household.allocations[0]));
M.applyDefaults(draft);M.setPortionMode(draft,'family');
assert.equal(draft.days['2026-10-05'].family.child.dinner.servings,1.5);
""")


def test_skipped_member_meals_and_fractional_totals_without_float_artifacts():
    run_model(r"""
M.setDates(draft,['2026-10-05','2026-10-07','2026-10-09']);
M.setMeals(draft,['breakfast','dinner']);M.setPortionMode(draft,'family');
M.setFamilyDefault(draft,'you','breakfast',{servings:0.1});
M.setFamilyDefault(draft,'partner','breakfast',{servings:0.2});
M.setFamilyDefault(draft,'child','breakfast',{enabled:false,servings:''});
for(const member of members) M.setFamilyDefault(draft,member.id,'dinner',{enabled:false});
let totals=M.summary(draft);assert.equal(totals.valid,true);assert.equal(totals.mealCount,3);
assert.equal(totals.totalServings,0.9);assert.equal(totals.memberTotals.you,0.3);
assert.equal(totals.memberTotals.partner,0.6);assert.equal(totals.memberTotals.child,0);
M.setDayFamily(draft,'2026-10-07','you','breakfast',{enabled:false});
M.setDayFamily(draft,'2026-10-07','partner','breakfast',{enabled:false});
totals=M.summary(draft);assert.equal(totals.mealCount,2);assert.equal(totals.totalServings,0.6);
assert.equal(totals.days[1].totalServings,0);assert.equal(M.payload(draft).allocations.length,2);
M.setMeals(draft,[]);assert.equal(M.summary(draft).valid,false);
""")


@pytest.mark.parametrize("invalid", ['""', '"NaN"', '"Infinity"', '"1e309"', '-1', '0', 'null', 'false', '"0x10"'])
def test_invalid_servings_remain_in_draft_and_prevent_save(invalid):
    run_model("""
const invalid = %s;
M.setHouseholdDefault(draft,'dinner',invalid);
assert.equal(draft.householdDefaults.dinner,invalid);
assert.equal(M.summary(draft).valid,false);assert.throws(()=>M.payload(draft),/finite/);
M.setPortionMode(draft,'family');M.setFamilyDefault(draft,'you','dinner',{servings:invalid});
assert.equal(M.summary(draft).valid,false);assert.throws(()=>M.payload(draft),/finite/);
""" % invalid)


def test_invalid_selection_empty_family_and_incomplete_prep_steps():
    run_model(r"""
M.setDates(draft,[]);assert.equal(M.summary(draft).valid,false);
M.setDates(draft,['2026-10-05','2026-10-05']);assert.equal(M.summary(draft).dayCount,1);
M.setMembers(draft,[]);M.setPortionMode(draft,'family');assert.match(M.summary(draft).errors[0],/family member/);
M.setPortionMode(draft,'household');
draft.prepSteps=[{date:'2026-02-30',instruction:'Chop'}];assert.throws(()=>M.payload(draft),/valid date/);
draft.prepSteps=[{date:'2026-10-04',instruction:'   '}];assert.throws(()=>M.payload(draft),/instruction/);
assert.throws(()=>M.setDateMode(draft,'all'),/valid date mode/);
assert.throws(()=>M.setPortionMode(draft,'whatever'),/valid portions mode/);
M.setHouseholdDefault(draft,'dinner',1e308);M.setDates(draft,['2026-10-05','2026-10-06']);
assert.equal(M.summary(draft).valid,false);assert.throws(()=>M.payload(draft),/too large/);
""")


def test_fresh_member_refresh_updates_only_untouched_enabled_defaults_and_preserves_day_overrides():
    run_model(r"""
M.setMembers(draft,[{id:'you',name:'You',default_portion:1},{id:'partner',name:'Partner',default_portion:1},{id:'child',name:'Child',default_portion:0.5}],{refreshDefaults:true});
M.setDates(draft,['2026-10-05','2026-10-07']);M.setMeals(draft,['breakfast','dinner']);M.setPortionMode(draft,'family');
M.setFamilyDefault(draft,'you','dinner',{servings:'2.5'});
M.setFamilyDefault(draft,'partner','dinner',{enabled:false});
M.setFamilyDefault(draft,'child','dinner',{servings:''});
M.setDayFamily(draft,'2026-10-07','you','breakfast',{servings:0.25});
M.setDayNotes(draft,'2026-10-07','Pack separately');draft.notes='Keep batch notes';
draft.prepSteps=[{date:'2026-10-04',instruction:'Prepare ahead'}];
const changedDay=JSON.stringify(draft.days['2026-10-07'].family);
M.setMembers(draft,[
 {id:'you',name:'New name',default_portion:2},{id:'partner',name:'Partner',default_portion:3},
 {id:'child',name:'Child',default_portion:0.75},{id:'new',name:'New member',default_portion:0.5}
],{refreshDefaults:true,newMembersEnabled:false});
assert.equal(draft.familyDefaults.you.breakfast.servings,2,'Untouched enabled defaults use fresh Settings portions');
assert.equal(draft.familyDefaults.you.dinner.servings,'2.5','Typed portions survive refresh');
assert.equal(draft.familyDefaults.partner.dinner.enabled,false);
assert.equal(draft.familyDefaults.partner.dinner.servings,1,'Unchecked portions are deliberate selections, not untouched defaults');
assert.equal(draft.familyDefaults.child.breakfast.servings,0.75);
assert.equal(draft.familyDefaults.child.dinner.servings,'','Incomplete numeric edits remain available to fix');
assert.equal(draft.familyDefaults.new.breakfast.enabled,false);assert.equal(draft.familyDefaults.new.breakfast.servings,0.5);
assert.equal(draft.days['2026-10-05'].family.you.breakfast.servings,2,'Dates using defaults receive current values');
const changedDayAfter=plain(draft.days['2026-10-07'].family);delete changedDayAfter.new;
assert.equal(JSON.stringify(changedDayAfter),changedDay,'Explicit date allocations stay unchanged');
assert.equal(draft.days['2026-10-07'].family.new.breakfast.enabled,false);
assert.equal(draft.days['2026-10-07'].notes,'Pack separately');assert.equal(draft.notes,'Keep batch notes');
assert.equal(draft.prepSteps[0].instruction,'Prepare ahead');assert.deepEqual(plain(draft.selectedDates),['2026-10-05','2026-10-07']);
""")


def test_ordinary_member_refresh_never_reinterprets_existing_allocations_as_fresh_defaults():
    run_model(r"""
M.setPortionMode(draft,'family');M.setDates(draft,['2026-10-05','2026-10-07']);
M.setDayFamily(draft,'2026-10-07','child','dinner',{servings:0.5});
const before=JSON.stringify(M.payload(draft));
M.setMembers(draft,[
 {id:'you',name:'You',default_portion:3},{id:'partner',name:'Partner',default_portion:2},
 {id:'child',name:'Child',default_portion:0.25},{id:'new',name:'New member',default_portion:0.5}
],{newMembersEnabled:false});
assert.equal(draft.members[0].default_portion,3,'New metadata is retained for a future plan');
assert.equal(draft.familyDefaults.you.dinner.servings,1,'An ordinary refresh preserves portions even when equal to the old Settings default');
assert.equal(JSON.stringify(M.payload(draft)),before,'Refreshing settings does not change scheduled allocations');
""")
