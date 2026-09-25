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
assert(!form.innerHTML.includes('Select a family or group'),'Group controls appear only in family mode');
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
assert.match(panel.ui.message,/Individually adjusted days stay unchanged/);
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
assert.equal(panel.draft.members.length,1,'Successful save retains cached people for the next open');
assert.equal(panel.ui.refreshMemberDefaults,true);
defaultPortion=2;await panel.open();M.setPortionMode(panel.draft,'family');
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,2,'A fresh preview plan uses current saved defaults');
assert.equal(M.payload(panel.draft).allocations[0].member_portions[0].servings,2);
assert.equal(panel.draft.groups[0].id,'family');
assert.equal(panel.ui.refreshMemberDefaults,false,'Fresh defaults are reconciled once the member request succeeds');
M.setFamilyDefault(panel.draft,'adult','dinner',{servings:0.75});panel.draft.notes='Keep this unsaved plan';
await click({scheduleAction:'cancel'});defaultPortion=3;await panel.open();
assert.equal(panel.draft.members[0].default_portion,3);
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,0.75,'Cancel and reopen preserves custom unsaved portions');
assert.equal(panel.draft.notes,'Keep this unsaved plan');
defaultPortion=4;await panel.loadMembers();
assert.equal(panel.draft.familyDefaults.adult.dinner.servings,0.75,'Ordinary refresh preserves custom portions');
""")


def test_people_and_portions_precede_collapsed_group_and_management_disclosures():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[
 {id:'nate',name:'Nate',default_portion:1,group_ids:['family']},
 {id:'gary',name:'Gary Tyler',default_portion:0.5,group_ids:['family']}
],groups:[{id:'family',name:'Tyler family'}]})});
await panel.open();await click({schedulePortionMode:'family'});
const people=form.innerHTML.indexOf('People &amp; portions (2)'),name=form.innerHTML.indexOf('<th scope="row">Nate</th>');
const group=form.innerHTML.indexOf('data-schedule-section="groups"'),edit=form.innerHTML.indexOf('data-schedule-section="members"');
assert(people>=0 && name>people && group>name && edit>group,'People and their portions are the first family controls');
assert.match(form.innerHTML,/data-schedule-section="groups"\s*>/,'Group shortcut starts collapsed');
assert.match(form.innerHTML,/data-schedule-section="members"\s*>/,'Name management starts collapsed');
assert.match(form.innerHTML,/data-schedule-section="notes"\s*>/,'Optional blank prep notes start collapsed');
assert.match(form.innerHTML,/<th scope="row">Gary Tyler<\/th>/);
assert.match(form.innerHTML,/data-schedule-field="family"[^>]+data-member="gary"[^>]+value="0.5"/);
assert.match(form.innerHTML,/<div data-schedule-apply hidden>/,'Unmodified days inherit portions without an extra action');
assert(!form.innerHTML.includes('Select people by group'));
panel.ui.openSections.add('groups');panel.render();assert.match(form.innerHTML,/data-schedule-section="groups" open/);
""")


def test_group_choices_show_counts_and_disable_groups_with_no_active_people():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[
 {id:'nate',name:'Nate',group_ids:['family','adults']},
 {id:'old',name:'Archived',group_ids:['empty'],archived:true}
],groups:[{id:'family',name:'Family'},{id:'adults',name:'Adults'},{id:'empty',name:'Empty'}]})});
await panel.open();await click({schedulePortionMode:'family'});
assert(form.innerHTML.includes('Family (1)'));assert(form.innerHTML.includes('Adults (1)'));
assert(form.innerHTML.includes('Empty (0) — no active people assigned'));
assert.match(form.innerHTML,/data-schedule-field="group"[^>]+data-group="empty"[^>]*disabled/);
assert(!/data-schedule-field="group"[^>]+data-group="family"[^>]*disabled/.test(form.innerHTML));
panel.ui.groupIds=['empty'];panel.render();assert.match(form.innerHTML,/data-schedule-action="select-group-members"[^>]*disabled/);
panel.ui.groupIds=['family','adults'];panel.render();assert(!/data-schedule-action="select-group-members"[^>]*disabled/.test(form.innerHTML));
await click({scheduleAction:'select-group-members'});assert.equal(M.summary(panel.draft).totalServings,1,'Overlapping groups retain one allocation per person');
M.setGroups(panel.draft,[]);panel.render();assert(!form.innerHTML.includes('Select a family or group'),'No empty group chooser when no groups exist');
""")


def test_initial_people_loading_failure_empty_and_archived_states_are_distinct_and_scoped():
    run_panel(r"""
ctx.withCanonicalViewerUserId=url=>url+(url.includes('?')?'&':'?')+'viewer_user_id=owner';
await click({schedulePortionMode:'family'});
let release;ctx.fetch=()=>new Promise(resolve=>release=resolve);const pending=panel.open();
assert(form.innerHTML.includes('Loading saved people…'));assert(!form.innerHTML.includes('No active people are saved'));
assert(!form.innerHTML.includes('Add at least one family member.'),'Unresolved member lists must not suggest duplicate creation');
assert.match(form.innerHTML,/data-schedule-action="retry-members"[^>]*disabled/);
release({ok:false,json:async()=>({ok:false,error:'Offline'})});await pending;
assert(form.innerHTML.includes('Your people could not be loaded. Retry before adding them again.'));
assert(!form.innerHTML.includes('Add at least one family member.'));
assert(!form.innerHTML.includes('No active people are saved'));
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[],groups:[],archived_members:[]})});await panel.loadMembers();
assert(form.innerHTML.includes('No active people are saved in this workspace.'));assert(form.innerHTML.includes('to add people.'));
assert(!form.innerHTML.includes('View archived people'));
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[],groups:[],archived_members:[{id:'nate',name:'Nate'},{id:'gary',name:'Gary Tyler'}]})});await panel.loadMembers();
assert(form.innerHTML.includes('Archived: Nate, Gary Tyler.'));assert(form.innerHTML.includes('to restore them.'));
assert.match(form.innerHTML,/href="\/settings\/family-members\?status=archived&amp;viewer_user_id=owner" target="_blank" rel="noopener"/);
assert(!form.innerHTML.includes('Your people could not be loaded'));
""")


def test_active_archived_and_group_names_are_escaped_in_people_section():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[{id:'person',name:'Nate <img src=x onerror=bad()> & "Jr"',group_ids:['group']}],groups:[{id:'group',name:'Family <script>bad()</script>'}]})});
await panel.open();await click({schedulePortionMode:'family'});
const people=Panel.peopleSection(panel.draft,panel.ui,'/settings/family-members');
assert(people.includes('Nate &lt;img src=x onerror=bad()&gt; &amp; &quot;Jr&quot;'));
assert(people.includes('Family &lt;script&gt;bad()&lt;/script&gt;'));assert(!people.includes('<script>'));assert(!people.includes('<img'));
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[],groups:[],archived_members:[{id:'old',name:'</p><script>bad()</script>'}]})});await panel.loadMembers();
const archived=Panel.peopleSection(panel.draft,panel.ui,'/settings/family-members');
assert(archived.includes('&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;'));assert(!archived.includes('<script>'));
""")


def test_cached_people_and_allocations_survive_refresh_failure_and_malformed_archived_metadata():
    run_panel(r"""
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members,groups:[{id:'group',name:'Family'}],archived_members:[{id:'old',name:'Old person'}]})});
await panel.open();await click({schedulePortionMode:'family'});M.setFamilyDefault(panel.draft,'child','dinner',{servings:0.5});
panel.draft.notes='Keep these notes';const payload=JSON.stringify(M.payload(panel.draft));
let release;ctx.fetch=()=>new Promise(resolve=>release=resolve);const refresh=panel.loadMembers();
assert(form.innerHTML.includes('Refreshing saved people…'));assert.match(form.innerHTML,/<th scope="row">Child<\/th>/);
release({ok:false,json:async()=>({ok:false,error:'Offline'})});await refresh;
assert(form.innerHTML.includes('Could not refresh people. The previously loaded people are still shown.'));
assert.equal(panel.draft.members.length,3);assert.equal(JSON.stringify(M.payload(panel.draft)),payload);
ctx.fetch=async()=>({ok:true,json:async()=>({ok:true,members:[],groups:[],archived_members:{invalid:true}})});await panel.loadMembers();
assert.equal(panel.draft.members.length,3);assert.equal(panel.draft.groups.length,1);assert.equal(panel.ui.archivedMembers[0].name,'Old person');
assert.equal(JSON.stringify(M.payload(panel.draft)),payload);assert.equal(panel.ui.memberLoadError,true);
""")


def test_fresh_plan_keeps_cached_people_on_reopen_failure_and_reconciles_only_untouched_defaults():
    run_panel(r"""
let people=[{id:'nate',name:'Nate',default_portion:1},{id:'gary',name:'Gary Tyler',default_portion:0.5}];
ctx.fetch=async(url,options)=>({ok:true,json:async()=>options?.method==='POST'?{ok:true,batch:{id:'saved'}}:{ok:true,members:people}});
await panel.open();await click({schedulePortionMode:'family'});await submit();
assert.equal(panel.draft.members.length,2);assert.equal(panel.ui.refreshMemberDefaults,true);assert.equal(panel.ui.membersLoaded,false);
ctx.fetch=async()=>{throw new Error('Offline');};await panel.open();await click({schedulePortionMode:'family'});
assert.match(form.innerHTML,/<th scope="row">Nate<\/th>/);assert.match(form.innerHTML,/<th scope="row">Gary Tyler<\/th>/);
assert(form.innerHTML.includes('previously loaded people are still shown'));assert.equal(panel.ui.refreshMemberDefaults,true);
let release;ctx.fetch=()=>new Promise(resolve=>release=resolve);const refresh=panel.loadMembers();
M.setFamilyDefault(panel.draft,'nate','dinner',{servings:1.25});
M.setFamilyDefault(panel.draft,'gary','breakfast',{enabled:false});
M.setDayFamily(panel.draft,'2026-10-05','nate','dinner',{servings:2.25});
people=[{id:'nate',name:'Nate',default_portion:3},{id:'gary',name:'Gary Tyler',default_portion:0.75}];
release({ok:true,json:async()=>({ok:true,members:people})});await refresh;
assert.equal(panel.ui.refreshMemberDefaults,false);assert.equal(panel.draft.familyDefaults.nate.dinner.servings,1.25,'Edits while loading survive');
assert.equal(panel.draft.familyDefaults.nate.lunch.servings,3,'Untouched defaults use newly saved personal portions');
assert.equal(panel.draft.familyDefaults.gary.dinner.servings,0.75);assert.equal(panel.draft.familyDefaults.gary.breakfast.enabled,false);
assert.equal(panel.draft.days['2026-10-05'].family.nate.dinner.servings,2.25,'Per-day edits while loading survive');
""")
