"""Family management integration with the shared planning form (DOM boundary tests)."""

from test_meal_plan_panel_ui import run_panel
from test_meal_planner_dialog_ui import run_dialog


def test_management_link_uses_viewer_scope_and_opens_without_discarding_draft():
    run_panel(r"""
ctx.withCanonicalViewerUserId=url=>url+'?viewer_user_id=family-owner';
panel.draft.notes='Keep this draft';panel.render();
assert.match(form.innerHTML,/href="\/settings\/family-members\?viewer_user_id=family-owner" target="_blank" rel="noopener"/);
assert(form.innerHTML.includes('Manage Family Members'));
assert(form.innerHTML.includes('Refresh members here after making changes.'));
assert.equal(panel.draft.notes,'Keep this draft');
""")


def test_reopen_refreshes_active_members_preserving_dates_notes_and_custom_portions():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});
await panel.open();M.setPortionMode(panel.draft,'family');
M.setDates(panel.draft,['2026-10-05','2026-10-07']);
M.setDayFamily(panel.draft,'2026-10-07','child','dinner',{servings:0.5});
M.setDayNotes(panel.draft,'2026-10-07','Pack separately');
panel.draft.notes='Keep batch notes';panel.draft.prepSteps=[{date:'2026-10-04',instruction:'Bake'}];
const originalTotal=M.summary(panel.draft).totalServings;
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[
 {id:'you',name:'Renamed'},members[1],members[2],{id:'guest',name:'Guest'},
 {id:'archived',name:'Archived',archived:true},
]})});
await panel.open();
assert.equal(panel.draft.members[0].name,'Renamed');
assert.equal(panel.draft.members.length,4);assert(!panel.draft.members.some(m=>m.id==='archived'));
assert.equal(panel.draft.familyDefaults.guest.dinner.enabled,false,'New choices do not increase existing draft portions');
assert.equal(M.summary(panel.draft).totalServings,originalTotal);
assert.deepEqual(plain(panel.draft.selectedDates),['2026-10-05','2026-10-07']);
assert.equal(panel.draft.days['2026-10-07'].family.child.dinner.servings,0.5);
assert.equal(panel.draft.days['2026-10-07'].notes,'Pack separately');
assert.equal(panel.draft.notes,'Keep batch notes');assert.equal(panel.draft.prepSteps[0].instruction,'Bake');
""")


def test_archived_members_require_review_before_saving_remaining_family_allocations():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});await panel.open();
M.setPortionMode(panel.draft,'family');panel.draft.notes='Retain recipe plan';
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[members[0],members[1],{...members[2],archived:true}]})});
await click({scheduleAction:'retry-members'});
assert.deepEqual(plain(panel.ui.memberReview),['Child']);
assert.equal(panel.draft.days['2026-10-05'].family.child,undefined);
assert(form.innerHTML.includes('No longer active: Child.'));
assert.match(form.innerHTML,/data-schedule-submit disabled/);
let writes=0;ctx.fetch=async()=>{writes++;return {ok:true,json:async()=>({ok:true,batch:{id:'saved'}})};};
await submit();assert.equal(writes,0,'A refresh must not silently submit reduced family portions');
panel.updateTotals();assert.equal(form.nodes['[data-schedule-submit]'].disabled,true);
assert.equal(panel.draft.notes,'Retain recipe plan');
await click({scheduleAction:'review-members'});assert.equal(panel.ui.memberReview.length,0);
await submit();assert.equal(writes,1);
""")


def test_member_refresh_and_mutations_are_serialized_and_failure_retains_inputs():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});await panel.open();
M.setPortionMode(panel.draft,'family');M.setDayFamily(panel.draft,'2026-10-05','child','dinner',{servings:0.5});
panel.ui.names.you='Pending name';panel.ui.newName='New person';panel.draft.notes='Keep notes';
let release;requests=[];
ctx.fetch=(url,options)=>{requests.push({url,options});return new Promise(resolve=>release=resolve);};
const pending=panel.loadMembers();
assert.equal(panel.ui.loading,true);await panel.saveMember('you');await submit();await panel.loadMembers();
assert.equal(requests.length,1,'List loads, member changes, and schedule saves cannot race');
release({ok:false,json:async()=>({ok:false,error:'Connection failed'})});await pending;
assert.equal(panel.ui.loading,false);assert.equal(panel.ui.membersLoaded,true);
assert.equal(panel.ui.names.you,'Pending name');assert.equal(panel.ui.newName,'New person');
assert.equal(panel.draft.notes,'Keep notes');assert.equal(panel.draft.days['2026-10-05'].family.child.dinner.servings,0.5);
assert(form.innerHTML.includes('Refresh members'));assert.match(panel.ui.message,/Connection failed/);
const mutation=panel.saveMember('you');assert.equal(panel.ui.memberBusy,true);
await panel.loadMembers();assert.equal(requests.length,2,'A refresh cannot overwrite an in-flight rename');
release({ok:true,json:async()=>({ok:true,member:{id:'you',name:'Pending name'}})});await mutation;
assert.equal(panel.draft.members[0].name,'Pending name');
""")


def test_main_planner_reopen_refreshes_members_but_recipe_switch_does_not():
    run_dialog(r"""
await open();const panel=await choose('recipe://bread');
assert.equal(requests.filter(r=>r.url==='/api/meal-plan/members').length,1);
await choose('recipe://soup');assert.equal(requests.filter(r=>r.url==='/api/meal-plan/members').length,1);
ctx.closeMealPlannerDialog();
responseFactory=async()=>({ok:true,json:async()=>({ok:true,members:[{id:'adult',name:'Nate'}]})});
await open('2026-11-02','lunch');
assert.equal(activeDialog.mealPlanScheduleState.panel,panel);
assert.equal(requests.filter(r=>r.url==='/api/meal-plan/members').length,2);
assert.deepEqual(plain(panel.draft.members),[{id:'adult',name:'Nate'}]);
assert.equal(panel.draft.singleDate,'2026-11-02');assert.deepEqual(plain(panel.draft.mealTypes),['lunch']);
""")


def test_archive_returned_during_inline_rename_requires_same_portion_review():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});await panel.open();
M.setPortionMode(panel.draft,'family');panel.ui.names.child='New name';
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,member:{id:'child',name:'New name',archived:true}})});
await panel.saveMember('child');
assert(!panel.draft.members.some(m=>m.id==='child'));assert.deepEqual(plain(panel.ui.memberReview),['Child']);
let writes=0;ctx.fetch=async()=>{writes++;throw new Error('Must not save yet');};
await submit();assert.equal(writes,0);
""")


def test_malformed_members_response_cannot_clear_family_allocations():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});await panel.open();
M.setPortionMode(panel.draft,'family');M.setDayFamily(panel.draft,'2026-10-05','child','dinner',{servings:0.5});
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true})});await panel.loadMembers();
assert.equal(panel.draft.members.length,3);assert.equal(panel.draft.days['2026-10-05'].family.child.dinner.servings,0.5);
assert.equal(panel.ui.memberReview.length,0);assert.equal(panel.ui.error,true);assert.equal(panel.ui.loading,false);
""")
