"""Exercise the shared planning model in Node without substituting browser access."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "PushShoppingList/static/js/meal-plan-schedule.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for scheduling logic checks")


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
