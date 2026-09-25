"""Member management interactions; these checks do not replace browser visual QA."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "PushShoppingList/static/js/family-members.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js required for controller checks")


def run_page(script):
    bootstrap = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const plain=value=>JSON.parse(JSON.stringify(value));
let requests=[],reply={ok:true,members:[]},httpOK=true;
const ctx={document:{readyState:'complete',querySelector(){return null;}},
 withCanonicalViewerUserId:url=>url+(url.includes('?')?'&':'?')+'viewer_user_id=viewer123',
 fetch:async(url,options)=>{requests.push({url,options});return {ok:httpOK,json:async()=>reply};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
function node(){return {value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,attrs:{},handlers:{},
 classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this.handlers[k]=v;},
 focus(){this.focused=true;},reportValidity(){return true;},querySelectorAll(){return [];},querySelector(){return null;},matches(){return false;}};}
const nodes=new Map();
const page={dataset:{apiUrl:'/api/meal-plan/members',groupsApiUrl:'/api/meal-plan/groups'},handlers:{},
 addEventListener(k,v){this.handlers[k]=v;},querySelectorAll(){return [];},
 querySelector(selector){if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);}};
const createForm=page.querySelector('[data-family-create]'),createInput=node(),createError=node(),createButton=node(),cancelButton=node();
const createFirst=node(),createLast=node(),createPortion=node();createPortion.value='1';
createForm.querySelector=selector=>({'input':createInput,'[name="first_name"]':createFirst,'[name="last_name"]':createLast,'[name="default_portion"]':createPortion,'[data-family-create-error]':createError}[selector]||null);
createForm.querySelectorAll=()=>[createInput,createFirst,createLast,createPortion,createButton,cancelButton];createForm.hidden=true;
const groupCreate=page.querySelector('[data-family-group-create]'),groupInput=node(),groupButton=node();
groupCreate.querySelector=selector=>selector==='input'?groupInput:null;groupCreate.querySelectorAll=()=>[groupInput,groupButton];
const members=[{id:'nate',name:'Nate',archived:false,meal_count:3},{id:'old',name:'Former member',archived:true,meal_count:2}];
const panel=new ctx.FamilyMembersPage(page,members);
const rows=()=>page.querySelector('[data-family-rows]').innerHTML;
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", str(SCRIPT)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_management_filters_counts_usage_and_escaped_member_content():
    run_page(r"""
assert(rows().includes('Nate'));assert(!rows().includes('Former member'));
assert(rows().includes('3 scheduled meals'));
assert.equal(page.querySelector('[data-family-active]').textContent,1);
assert.equal(page.querySelector('[data-family-archived]').textContent,1);
assert.equal(page.querySelector('[data-family-used]').textContent,2);
panel.filter='archived';panel.render();assert(rows().includes('Former member'));assert(rows().includes('Restore'));
panel.filter='all';panel.search='nAtE';panel.render();assert(rows().includes('Nate'));assert(!rows().includes('Former member'));
panel.search='nobody';panel.render();assert.equal(rows(),'');assert.equal(page.querySelector('[data-family-empty]').hidden,false);
panel.search='';panel.members.push({id:'evil"',name:'<img src=x onerror=bad()>',archived:false,meal_count:0});panel.render();
assert(rows().includes('&lt;img src=x onerror=bad()&gt;'));assert(!rows().includes('<img'));
assert(rows().includes('data-family-member-id="evil&quot;"'));assert(rows().includes('scope=')===false);
""")


def test_refresh_load_failure_keeps_members_and_pending_name_edits():
    run_page(r"""
panel.drafts.set('nate','Nathan');reply={ok:true,members:[...members,{id:'new',name:'New',archived:false,meal_count:0}]};
await panel.load();assert.equal(requests[0].url,'/api/meal-plan/members?include_archived=true&viewer_user_id=viewer123');
assert.equal(panel.members.length,3);assert(rows().includes('value="Nathan"'));
httpOK=false;reply={ok:false,error:'Please sign in again.'};await panel.load();
assert.equal(panel.members.length,3);assert.equal(panel.drafts.get('nate'),'Nathan');
assert.equal(page.querySelector('[data-family-status]').textContent,'Please sign in again.');
assert.equal(page.querySelector('[data-family-refresh]').disabled,false);
""")


def test_save_and_archive_restore_share_existing_member_ids_and_preserve_meal_count():
    run_page(r"""
panel.drafts.set('nate','Nathan');reply={ok:true,member:{id:'nate',name:'Nathan',archived:false,meal_count:3}};
await panel.update(members[0],{name:'Nathan'});
assert.equal(requests[0].url,'/api/meal-plan/members/nate?viewer_user_id=viewer123');
assert.equal(requests[0].options.method,'PATCH');assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Nathan'});
assert.equal(panel.drafts.has('nate'),false);assert.equal(panel.members[0].name,'Nathan');
reply={ok:true,member:{id:'nate',name:'Nathan',archived:true,meal_count:3}};
await panel.update(panel.members[0],{archived:true});assert(!rows().includes('Nathan'));
assert(page.querySelector('[data-family-status]').textContent.includes('Existing meal plans are preserved'));
panel.filter='archived';panel.render();assert(rows().includes('Nathan'));assert(rows().includes('3 scheduled meals'));
reply={ok:true,member:{id:'nate',name:'Nathan',archived:false,meal_count:3}};
await panel.update(panel.members[0],{archived:false});assert(!rows().includes('Nathan'));
assert.equal(panel.members[0].id,'nate');assert.equal(panel.members[0].meal_count,3);
assert(requests.every(request=>request.options.method!=='DELETE'));
""")


def test_failed_rename_retains_input_and_successful_retry_clears_error():
    run_page(r"""
panel.drafts.set('nate','Other name');httpOK=false;reply={ok:false,error:'A member already uses that name.'};
await panel.update(members[0],{name:'Other name'});
assert.equal(panel.members[0].name,'Nate');assert.equal(panel.drafts.get('nate'),'Other name');
assert(rows().includes('value="Other name"'));assert(rows().includes('aria-invalid="true"'));
assert(rows().includes('A member already uses that name.'));assert.equal(panel.pending.size,0);
httpOK=true;reply={ok:true,member:{id:'nate',name:'Other name',archived:false,meal_count:3}};
await panel.update(members[0],{name:'Other name'});assert.equal(panel.errors.size,0);assert.equal(panel.drafts.size,0);
""")


def test_add_member_failure_retains_name_and_retry_returns_to_active_list():
    run_page(r"""
panel.openCreate(true);assert.equal(createForm.hidden,false);assert.equal(createInput.focused,true);
createInput.value=' Sam ';httpOK=false;reply={ok:false,error:'Could not save.'};await panel.create();
assert.equal(createInput.value,' Sam ');assert.equal(createError.textContent,'Could not save.');
assert.equal(createForm.hidden,false);assert.equal(createButton.disabled,false);
panel.search='something';panel.filter='archived';httpOK=true;reply={ok:true,member:{id:'sam',name:'Sam',archived:false,meal_count:0}};
await panel.create();assert.equal(createInput.value,'');assert.equal(createForm.hidden,true);
assert.equal(panel.members.length,3);assert.equal(panel.filter,'active');assert.equal(panel.search,'');
assert(rows().includes('Sam'));assert.deepEqual(JSON.parse(requests[1].options.body),{name:'Sam',first_name:'',last_name:'',default_portion:1,group_ids:[]});
""")


def test_pending_mutation_blocks_duplicate_requests_and_refresh():
    run_page(r"""
let release;ctx.fetch=(url,options)=>{requests.push({url,options});return new Promise(resolve=>release=resolve);};
const first=panel.update(members[0],{archived:true});
assert.equal(panel.pending.size,1);assert.equal(page.querySelector('[data-family-refresh]').disabled,true);
await panel.update(members[0],{archived:true});await panel.load();assert.equal(requests.length,1);
release({ok:true,json:async()=>({ok:true,member:{id:'nate',name:'Nate',archived:true,meal_count:3}})});await first;
assert.equal(panel.pending.size,0);assert.equal(page.querySelector('[data-family-refresh]').disabled,false);
""")


def test_keyboard_save_and_cancel_preserve_validity_and_member_identity():
    run_page(r"""
const input=node();input.value='Nathan';input.matches=selector=>selector==='[data-family-name]';
const save=node(),cancel=node();const row={dataset:{familyMemberId:'nate'},querySelector:selector=>selector==='[data-family-name]'?input:selector==='[data-family-save]'?save:cancel};
input.closest=selector=>selector==='[data-family-member-id]'?row:null;panel.input({target:input});assert.equal(save.disabled,false);assert.equal(cancel.hidden,false);
let prevented=0;reply={ok:true,member:{id:'nate',name:'Nathan',archived:false,meal_count:3}};
panel.keydown({target:input,key:'Enter',preventDefault(){prevented++;}});
await new Promise(resolve=>setTimeout(resolve,0));assert.equal(panel.members[0].name,'Nathan');assert.equal(prevented,1);
input.value='Unsaved';panel.input({target:input});panel.keydown({target:input,key:'Escape',preventDefault(){prevented++;}});
assert.equal(panel.drafts.has('nate'),false);assert.equal(prevented,2);assert.equal(requests.length,1);
""")


def test_async_other_row_completion_keeps_keyboard_focus_and_caret():
    run_page(r"""
panel.members.push({id:'sam',name:'Sam',archived:false,meal_count:1});
ctx.document.body={};ctx.document.activeElement=ctx.document.body;
let domRows=[],html='';
page.querySelectorAll=()=>domRows;
Object.defineProperty(page.querySelector('[data-family-rows]'),'innerHTML',{
 get(){return html;},set(value){
  html=value;
  if(ctx.document.activeElement?.closest?.('[data-family-member-id]'))ctx.document.activeElement=ctx.document.body;
  domRows=[...value.matchAll(/<tr data-family-member-id="([^"]+)" aria-busy="([^"]+)">/g)].map(match=>{
   const controls={};const row={dataset:{familyMemberId:match[1]},querySelector:selector=>controls[selector]};
   for(const key of ['name','save','cancel','archive']){
    const selector=`[data-family-${key}]`,control=node();controls[selector]=control;
    control.disabled=match[2]==='true';control.matches=value=>value===selector;control.closest=()=>row;
    control.focus=()=>{ctx.document.activeElement=control;};
    control.setSelectionRange=(start,end)=>{control.selectionStart=start;control.selectionEnd=end;};
   }
   return row;
  });
 }
});
panel.render();let release;ctx.fetch=(url,options)=>new Promise(resolve=>release=resolve);
const pending=panel.update(panel.members[0],{archived:true});
const sam=domRows.find(row=>row.dataset.familyMemberId==='sam').querySelector('[data-family-name]');
sam.focus();sam.selectionStart=1;sam.selectionEnd=2;panel.drafts.set('sam','Samuel');
release({ok:true,json:async()=>({ok:true,member:{id:'nate',name:'Nate',archived:true,meal_count:3}})});await pending;
const replacement=domRows.find(row=>row.dataset.familyMemberId==='sam').querySelector('[data-family-name]');
assert.equal(ctx.document.activeElement,replacement);assert.equal(replacement.selectionStart,1);assert.equal(replacement.selectionEnd,2);
assert.equal(panel.drafts.get('sam'),'Samuel');assert(rows().includes('value="Samuel"'));
assert.notEqual(page.querySelector('[data-family-filter]').focused,true);
""")


def test_archiving_the_focused_member_returns_focus_to_status_filter():
    run_page(r"""
reply={ok:true,member:{id:'nate',name:'Nate',archived:true,meal_count:3}};
await panel.update(members[0],{archived:true});
assert.equal(page.querySelector('[data-family-filter]').focused,true);
assert.equal(panel.visibleMembers().length,0);
""")


def test_legacy_display_names_stay_unchanged_and_profiles_save_explicit_fields():
    run_page(r"""
assert.deepEqual(plain(panel.memberProfile(members[0])),{first_name:'',last_name:'',default_portion:1,group_ids:[]});
panel.groups=[{id:'house',name:'Household',archived:false},{id:'friends',name:'Friends',archived:false}];
panel.expanded.add('nate');panel.profiles.set('nate',{first_name:'Nathan',last_name:'Tyler',default_portion:'0.5',group_ids:['house','friends','house']});
panel.render();assert(rows().includes('value="Nate"'));assert(rows().includes('value="Nathan"'));assert(rows().includes('value="0.5"'));
assert.match(rows(),/data-family-member-group[^>]+value="house" checked/);assert.match(rows(),/data-family-member-group[^>]+value="friends" checked/);
const input=node();input.value='Nate';const row={querySelector:()=>input};
reply={ok:true,member:{...members[0],first_name:'Nathan',last_name:'Tyler',default_portion:0.5,group_ids:['house','friends']}};
await panel.saveRow(row,members[0]);
assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Nate',first_name:'Nathan',last_name:'Tyler',default_portion:0.5,group_ids:['house','friends']});
assert.equal(panel.members[0].name,'Nate');assert.equal(panel.profiles.size,0);assert.equal(panel.members[0].meal_count,3);
panel.search='Nathan Tyler';assert.equal(panel.visibleMembers().length,1);
""")


def test_group_filters_use_ids_and_group_archive_preserves_member_associations():
    run_page(r"""
panel.groups=[{id:'home',name:'Family',archived:false},{id:'other',name:'Other group',archived:true}];
panel.members[0]={...members[0],group_ids:['home','other'],default_portion:0.5};
panel.members.push({id:'ungrouped',name:'New person',archived:false,meal_count:0,group_ids:[]});
panel.groupFilter='home';panel.render();assert.equal(panel.visibleMembers().length,1);assert.equal(panel.visibleMembers()[0].id,'nate');
assert(rows().includes('Other group (Archived)'));assert(rows().includes('3 scheduled meals'));
panel.groupFilter='ungrouped';panel.render();assert.equal(panel.visibleMembers()[0].id,'ungrouped');
assert(!panel.groupChoices([],'data-test').includes('Other group'));
assert(panel.groupChoices(['other'],'data-test').includes('Other group (Archived)'));
reply={ok:true,group:{id:'home',name:'Family',archived:true}};
await panel.updateGroup(panel.groups[0],{archived:true});
assert.deepEqual(panel.members[0].group_ids,['home','other']);assert.equal(panel.members[0].meal_count,3);
assert.equal(requests[0].url,'/api/meal-plan/groups/home?viewer_user_id=viewer123');
assert.equal(requests[0].options.method,'PATCH');assert.deepEqual(JSON.parse(requests[0].options.body),{archived:true});
reply={ok:true,group:{id:'home',name:'Family',archived:false}};await panel.updateGroup(panel.groups[0],{archived:false});
assert.equal(panel.groups[0].archived,false);
""")


def test_groups_create_rename_failure_and_retry_keep_saved_identity():
    run_page(r"""
groupInput.value=' Home team ';reply={ok:true,group:{id:'g1',name:'Home team',archived:false}};
await panel.createGroup();assert.equal(groupInput.value,'');assert.equal(panel.groups.length,1);
assert.equal(requests[0].url,'/api/meal-plan/groups?viewer_user_id=viewer123');assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Home team'});
panel.groupDrafts.set('g1','Family');httpOK=false;reply={ok:false,error:'Name already exists.'};
await panel.updateGroup(panel.groups[0],{name:'Family'});assert.equal(panel.groupDrafts.get('g1'),'Family');
assert.equal(panel.groups[0].name,'Home team');assert(page.querySelector('[data-family-groups]').innerHTML.includes('Name already exists.'));
httpOK=true;reply={ok:true,group:{id:'g1',name:'Family',archived:false}};
await panel.updateGroup(panel.groups[0],{name:'Family'});assert.equal(panel.groupDrafts.size,0);assert.equal(panel.groups[0].name,'Family');
assert.equal(panel.groupErrors.size,0);
""")


def test_create_profile_validates_positive_fraction_and_multiple_groups():
    run_page(r"""
panel.groups=[{id:'g1',name:'Group 1',archived:false},{id:'g2',name:'Group 2',archived:false}];
createInput.value='Sam';createFirst.value='Samuel';createLast.value='Example';createPortion.value='0';panel.createGroups=['g1','g2','g1'];
await panel.create();assert.equal(requests.length,0);assert(createError.textContent.includes('greater than zero'));assert.equal(createInput.value,'Sam');
createPortion.value='0.5';reply={ok:true,member:{id:'sam',name:'Sam',first_name:'Samuel',last_name:'Example',default_portion:0.5,group_ids:['g1','g2'],archived:false,meal_count:0}};
await panel.create();assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Sam',first_name:'Samuel',last_name:'Example',default_portion:0.5,group_ids:['g1','g2']});
assert.equal(createFirst.value,'');assert.equal(createLast.value,'');assert.equal(createPortion.value,1);assert.equal(panel.createGroups.length,0);
""")


def test_bulk_add_is_one_atomic_request_and_failed_rows_and_groups_are_preserved():
    run_page(r"""
panel.bulkRows=[{key:'1',name:' Alex ',first_name:'Alexander',last_name:'',default_portion:1},{key:'2',name:'Jamie',first_name:'',last_name:'Smith',default_portion:'0.5'}];
panel.bulkGroups=['g1','g2','g1'];panel.openBulk(true);
httpOK=false;reply={ok:false,error:'Jamie already exists. No people added.'};
await panel.createBulk();assert.equal(panel.members.length,2);assert.equal(panel.bulkRows.length,2);assert.equal(panel.bulkRows[1].last_name,'Smith');
assert.deepEqual(plain(panel.bulkGroups),['g1','g2','g1']);assert.equal(page.querySelector('[data-family-bulk]').hidden,false);
assert.equal(page.querySelector('[data-family-bulk-error]').hidden,false);
assert.equal(requests[0].url,'/api/meal-plan/members/bulk?viewer_user_id=viewer123');
assert.deepEqual(JSON.parse(requests[0].options.body),{members:[{name:'Alex',first_name:'Alexander',last_name:'',default_portion:1},{name:'Jamie',first_name:'',last_name:'Smith',default_portion:0.5}],group_ids:['g1','g2']});
panel.bulkRows[1].name='Jamie S';httpOK=true;reply={ok:true,members:[{id:'alex',name:'Alex',archived:false,meal_count:0,group_ids:['g1','g2']},{id:'jamie',name:'Jamie S',archived:false,meal_count:0,group_ids:['g1','g2']}]};
await panel.createBulk();assert.equal(panel.members.length,4);assert.equal(requests.length,2);assert.equal(page.querySelector('[data-family-bulk]').hidden,true);
assert.equal(panel.bulkRows.length,2);assert.equal(panel.bulkRows[0].name,'');assert.equal(panel.bulkGroups.length,0);
""")


def test_bulk_rows_are_editable_add_remove_keep_other_rows_and_invalid_portions_block():
    run_page(r"""
const input=node();input.value='Alex';input.dataset={familyBulkField:'name'};
input.matches=selector=>selector==='[data-family-bulk-field]';input.closest=()=>({dataset:{familyBulkRow:panel.bulkRows[0].key}});
panel.input({target:input});assert.equal(panel.bulkRows[0].name,'Alex');
const button=(selector,dataset={})=>({disabled:false,dataset,matches:value=>value===selector,closest(){return null;}});
panel.click({target:{closest:()=>button('[data-family-bulk-add-row]')}});assert.equal(panel.bulkRows.length,3);assert.equal(panel.bulkRows[0].name,'Alex');
const key=panel.bulkRows[1].key;
panel.click({target:{closest:()=>button('[data-family-bulk-remove]',{familyBulkRemove:key})}});assert.equal(panel.bulkRows.length,2);assert.equal(panel.bulkRows[0].name,'Alex');
panel.bulkRows[1].name='Taylor';panel.bulkRows[1].default_portion=0;
await panel.createBulk();assert.equal(requests.length,0);assert(page.querySelector('[data-family-bulk-error]').textContent.includes('Person 2'));
panel.bulkRows[1].default_portion=0.5;let release;
ctx.fetch=(url,options)=>{requests.push({url,options});return new Promise(resolve=>release=resolve);};
const pending=panel.createBulk();await panel.createBulk();await panel.load();assert.equal(requests.length,1);assert.equal(panel.bulkBusy,true);
release({ok:false,json:async()=>({ok:false,error:'Try again.'})});await pending;assert.equal(panel.bulkBusy,false);assert.equal(panel.bulkRows[0].name,'Alex');
""")


def test_existing_ungrouped_members_can_join_multiple_groups_and_profile_cancel_is_complete():
    run_page(r"""
const member=members[0];
const checkbox=(id,checked)=>({value:id,checked,dataset:{familyMember:'nate'},matches:selector=>selector==='[data-family-member-group]'});
panel.change({target:checkbox('group1',true)});panel.change({target:checkbox('group2',true)});panel.change({target:checkbox('group1',true)});
assert.deepEqual(plain(panel.memberProfile(member).group_ids),['group1','group2']);assert.equal(panel.dirty(member),true);
panel.change({target:checkbox('group1',false)});assert.deepEqual(plain(panel.memberProfile(member).group_ids),['group2']);
panel.drafts.set('nate','New name');panel.errors.set('nate','failed');panel.cancelRow('nate');
assert.equal(panel.profiles.size,0);assert.equal(panel.drafts.size,0);assert.equal(panel.errors.size,0);assert.equal(panel.memberProfile(member).first_name,'');
""")
