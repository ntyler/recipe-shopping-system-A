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
assert.deepEqual(plain(panel.draft.members.map(({id,name})=>({id,name}))),[{id:'adult',name:'Nate'}]);
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


def test_group_chooser_applies_union_once_with_saved_fractional_portions_and_explicit_ids():
    run_panel(r"""
const people=[
 {id:'nate',name:'Nate Tyler',first_name:'Nate',last_name:'Tyler',default_portion:1.5,group_ids:['family','adults']},
 {id:'kid',name:'Child',default_portion:0.5,group_ids:['family']},
 {id:'guest',name:'Guest',default_portion:2,group_ids:['guests']},
 {id:'old',name:'Archived person',default_portion:2,group_ids:['family'],archived:true},
];
const groups=[{id:'family',name:'Family <group>'},{id:'adults',name:'Adults'},{id:'guests',name:'Guests'},{id:'old-group',name:'Old group',archived:true}];
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:people,groups})});await panel.open();
assert.equal(panel.draft.familyDefaults.nate.dinner.servings,1.5);assert.equal(panel.draft.familyDefaults.kid.dinner.servings,0.5);
assert.equal(panel.draft.members[0].first_name,'Nate');assert.equal(panel.draft.members[0].last_name,'Tyler');
assert.deepEqual(plain(panel.draft.members[0].group_ids),['family','adults']);
assert(!form.innerHTML.includes('Select people by group'),'Group controls appear only in family mode');
await click({schedulePortionMode:'family'});
assert(form.innerHTML.includes('Family &lt;group&gt;'));assert(!form.innerHTML.includes('Old group'));assert(!form.innerHTML.includes('Archived person'));
const before=M.summary(panel.draft).totalServings;
for(const group of ['family','adults']) panel.change({target:field('group','',{type:'checkbox',checked:true,dataset:{scheduleField:'group',group}})});
assert.equal(M.summary(panel.draft).totalServings,before,'Checking groups alone does not change portions');
await click({scheduleAction:'select-group-members'});
assert.equal(M.summary(panel.draft).totalServings,2,'Overlapping groups count each person once');
assert.equal(panel.draft.familyDefaults.guest.dinner.enabled,false);
assert.equal(panel.draft.familyDefaults.nate.breakfast.enabled,true,'Newly enabled meals keep the selected people');
const payload=plain(M.payload(panel.draft));
assert.deepEqual(payload.allocations[0].member_portions,[{member_id:'nate',servings:1.5},{member_id:'kid',servings:0.5}]);
assert(!JSON.stringify(payload).includes('group'));assert(!JSON.stringify(payload).includes('default_portion'));
panel.change({target:field('family-enabled','',{type:'checkbox',checked:false,dataset:{scheduleField:'family-enabled',member:'kid',meal:'dinner'}})});
assert.equal(M.summary(panel.draft).totalServings,1.5,'Individual controls remain available after group selection');
""")


def test_group_defaults_preserve_custom_day_until_explicit_apply_and_do_not_reset_portions():
    run_panel(r"""
const people=[{id:'adult',name:'Adult',default_portion:1,group_ids:['family']},{id:'guest',name:'Guest',default_portion:0.5,group_ids:['visitors']}];
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:people,groups:[{id:'family',name:'Family'},{id:'visitors',name:'Visitors'}]})});await panel.open();
M.setPortionMode(panel.draft,'family');M.setDates(panel.draft,['2026-10-05','2026-10-07']);
M.setFamilyDefault(panel.draft,'adult','dinner',{servings:2.5});
M.setDayFamily(panel.draft,'2026-10-07','guest','dinner',{enabled:true,servings:0.75});
M.setDayNotes(panel.draft,'2026-10-07','Guest portions');panel.draft.notes='Preserve batch note';
panel.ui.groupIds=['family'];await click({scheduleAction:'select-group-members'});
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,2.5);
assert.equal(panel.draft.familyDefaults.guest.dinner.enabled,false);
assert.equal(panel.draft.days['2026-10-05'].family.guest.dinner.enabled,false);
assert.equal(panel.draft.days['2026-10-07'].family.guest.dinner.enabled,true);
assert.equal(panel.draft.days['2026-10-07'].family.guest.dinner.servings,0.75);
assert.match(panel.ui.message,/Adjusted days are unchanged/);
await click({scheduleAction:'apply'});
assert.equal(panel.draft.days['2026-10-07'].family.guest.dinner.enabled,false);
assert.equal(panel.draft.days['2026-10-07'].notes,'Guest portions');assert.equal(panel.draft.notes,'Preserve batch note');
""")


def test_refresh_and_bulk_added_people_do_not_live_bind_group_selection_or_override_draft():
    run_panel(r"""
let people=[{id:'nate',name:'Nate',default_portion:0.5,group_ids:['family']},{id:'guest',name:'Guest',default_portion:1,group_ids:[]}];
let groups=[{id:'family',name:'Family'}];
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:people,groups})});await panel.open();
M.setPortionMode(panel.draft,'family');panel.ui.groupIds=['family'];await click({scheduleAction:'select-group-members'});
M.setFamilyDefault(panel.draft,'nate','dinner',{servings:1.25});
const originalPayload=JSON.stringify(M.payload(panel.draft));
people=[{id:'nate',name:'Nate',default_portion:3,group_ids:[]},{id:'guest',name:'Guest',default_portion:2,group_ids:['family']},
 {id:'new-a',name:'New A',default_portion:0.5,group_ids:['family']},{id:'new-b',name:'New B',default_portion:1.5,group_ids:['family']}];
await panel.loadMembers();
assert.equal(panel.draft.familyDefaults.nate.dinner.servings,1.25,'Settings defaults never replace existing custom portions');
assert.equal(panel.draft.members[0].default_portion,3,'Saved metadata is available for a future fresh draft');
assert.equal(panel.draft.familyDefaults.guest.dinner.servings,1,'Existing portions stay stable even when an unchanged settings default changes');
assert.equal(panel.draft.familyDefaults['new-a'].dinner.servings,0.5);
assert.equal(panel.draft.familyDefaults['new-b'].dinner.servings,1.5);
assert.equal(panel.draft.familyDefaults['new-a'].dinner.enabled,false);
assert.equal(JSON.stringify(M.payload(panel.draft)),originalPayload,'Group edits and bulk-added people do not change draft allocations');
await click({scheduleAction:'select-group-members'});
assert.deepEqual(plain(M.payload(panel.draft).allocations[0].member_portions),[
 {member_id:'guest',servings:1},{member_id:'new-a',servings:0.5},{member_id:'new-b',servings:1.5}
]);
groups=[{id:'family',name:'Family',archived:true}];const payloadBeforeArchive=JSON.stringify(M.payload(panel.draft));
await panel.loadMembers();
assert.equal(panel.draft.groups.length,0);assert.equal(panel.ui.groupIds.length,0);
assert.equal(JSON.stringify(M.payload(panel.draft)),payloadBeforeArchive,'Archiving a group does not remove the selected individual people');
assert.throws(()=>M.selectGroupMembers(panel.draft,['family']),/active group/);
""")


def test_malformed_groups_response_preserves_members_and_legacy_response_has_no_groups():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members,groups:[{id:'family',name:'Family'}]})});await panel.open();
panel.draft.notes='Preserve';
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[],groups:{bad:true}})});await panel.loadMembers();
assert.equal(panel.draft.members.length,3);assert.equal(panel.draft.groups.length,1);assert.equal(panel.ui.error,true);
assert.equal(panel.draft.notes,'Preserve');
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members})});await panel.loadMembers();
assert.equal(panel.draft.groups.length,0);assert.equal(panel.draft.members.length,3);assert.equal(panel.ui.error,false);
""")


def test_main_dialog_reopen_uses_member_default_portions_and_preserves_group_catalog():
    run_dialog(r"""
responseFactory=async()=>({ok:true,json:async()=>({ok:true,
 members:[{id:'adult',name:'Adult',default_portion:1.5,group_ids:['family']},{id:'child',name:'Child',default_portion:0.5,group_ids:['family']}],
 groups:[{id:'family',name:'Family'}]
})});
await open();const panel=await choose('recipe://bread');
M.setPortionMode(panel.draft,'family');panel.ui.groupIds=['family'];M.selectGroupMembers(panel.draft,panel.ui.groupIds);
assert.equal(M.summary(panel.draft).totalServings,2);M.setFamilyDefault(panel.draft,'child','dinner',{servings:3});
ctx.closeMealPlannerDialog();await open('2026-11-02','lunch');
assert.equal(panel.draft.groups[0].name,'Family');assert.equal(panel.ui.groupIds.length,0);
assert.equal(panel.draft.familyDefaults.adult.lunch.servings,1.5);assert.equal(panel.draft.familyDefaults.child.lunch.servings,0.5);
await choose('recipe://soup');assert.equal(panel.draft.groups[0].id,'family');
ctx.closeMealPlannerDialog();
responseFactory=async()=>({ok:true,json:async()=>({ok:true,
 members:[{id:'adult',name:'Adult',default_portion:2,group_ids:['family']},{id:'child',name:'Child',default_portion:0.75,group_ids:['family']}],
 groups:[{id:'family',name:'Family'}]
})});
await open('2026-11-03','dinner');
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,2,'A new plan uses defaults changed in Settings since the previous open');
assert.equal(panel.draft.familyDefaults.child.dinner.servings,0.75);
""")


def test_preview_new_plan_after_save_uses_latest_defaults_but_cancel_and_refresh_preserve_draft():
    run_panel(r"""
let defaultPortion=1;
ctx.fetch=async(url,options)=>({ok:true,json:async()=>options?.method==='POST'
 ? {ok:true,batch:{id:'saved'}}
 : {ok:true,members:[{id:'adult',name:'Adult',default_portion:defaultPortion,group_ids:['family']}],groups:[{id:'family',name:'Family'}]}
});
await panel.open();M.setPortionMode(panel.draft,'family');
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,1);
await submit();assert.equal(form.hidden,true);assert.equal(panel.ui.membersLoaded,false);
defaultPortion=2;await panel.open();M.setPortionMode(panel.draft,'family');
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,2,'A fresh preview plan uses current saved defaults');
assert.equal(M.payload(panel.draft).allocations[0].member_portions[0].servings,2);
assert.equal(panel.draft.groups[0].id,'family');
M.setFamilyDefault(panel.draft,'adult','dinner',{servings:0.75});panel.draft.notes='Keep this unsaved plan';
await click({scheduleAction:'cancel'});defaultPortion=3;await panel.open();
assert.equal(panel.draft.members[0].default_portion,3);
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,0.75,'Cancel and reopen preserves custom unsaved portions');
assert.equal(panel.draft.notes,'Keep this unsaved plan');
defaultPortion=4;await panel.loadMembers();
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,0.75,'Ordinary refresh preserves custom portions');
""")
