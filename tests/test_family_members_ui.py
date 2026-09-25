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
const documentEvents={},windowEvents={};
const ctx={URLSearchParams,innerWidth:1280,innerHeight:900,
 document:{readyState:'complete',querySelector(){return null;},
  addEventListener(type,handler){(documentEvents[type] ||= []).push(handler);}},
 addEventListener(type,handler){(windowEvents[type] ||= []).push(handler);},
 withCanonicalViewerUserId:url=>url+(url.includes('?')?'&':'?')+'viewer_user_id=viewer123',
 fetch:async(url,options)=>{requests.push({url,options});return {ok:httpOK,json:async()=>reply};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
function node(){return {value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,attrs:{},handlers:{},dataset:{},children:[],isConnected:true,
 style:{setProperty(key,value){this[key]=value;}},classList:{toggle(){},add(){},remove(){}},
 setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},removeAttribute(k){delete this.attrs[k];},addEventListener(k,v){this.handlers[k]=v;},
 focus(){this.focused=true;},reportValidity(){return true;},querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},
 contains(other){return other===this||this.children.some(child=>child===other||child.contains?.(other));},
 getBoundingClientRect(){return {left:300,right:335,top:200,bottom:235,width:35,height:35};},
 showPopover(){this.popoverOpen=true;this.hidden=false;this.showCount=(this.showCount||0)+1;},
 hidePopover(){this.popoverOpen=false;this.hideCount=(this.hideCount||0)+1;},matches(selector){return selector===':popover-open'&&!!this.popoverOpen;}};}
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
function mountGroupEditorRows() {
 const editor=page.querySelector('[data-family-group-editor]'),choices=page.querySelector('[data-family-group-editor-choices]');
 const title=page.querySelector('[data-family-group-editor-title]'),close=page.querySelector('[data-family-close-groups]');
 const firstChoice=node();firstChoice.type='checkbox';
 const focus=node=>{node.focused=true;ctx.document.activeElement=node;};
 firstChoice.focus=()=>focus(firstChoice);editor.focus=()=>focus(editor);close.focus=()=>focus(close);
 close.matches=selector=>selector==='[data-family-close-groups]';
 editor.id='familyMemberGroupEditor';editor.children=[choices,title,close];choices.children=[firstChoice];
 firstChoice.closest=selector=>selector==='[data-family-group-editor]'?editor:null;
 editor.querySelector=selector=>selector.includes('choices')?choices:selector.includes('title')?title:selector.includes('close')?close:selector.includes('input')&&choices.innerHTML.includes('type="checkbox"')?firstChoice:null;
 editor.querySelectorAll=selector=>selector==='button:not(:disabled), input:not(:disabled)'?[firstChoice,close]:[];
 choices.querySelector=selector=>selector.includes('input')&&choices.innerHTML.includes('type="checkbox"')?firstChoice:null;
 const domRows=panel.members.map(member=>{
  const row=node();row.dataset.familyMemberId=member.id;
  const name=node(),edit=node(),save=node(),cancel=node(),badges=node();name.value=panel.drafts.get(member.id)??member.name;
  const profiles=Object.fromEntries(['first_name','last_name','default_portion'].map(field=>{
   const input=node();input.value=String(panel.memberProfile(member)[field]);input.type=field==='default_portion'?'number':'text';
   input.dataset={familyProfile:field,familyFocus:member.id+':'+field};
   input.matches=selector=>selector==='[data-family-profile]'||selector===`[data-family-profile="${field}"]`;
   input.focus=()=>focus(input);input.closest=selector=>selector==='[data-family-member-id]'?row:null;
   return [field,input];
  }));
  name.matches=selector=>selector==='[data-family-name]';name.focus=()=>focus(name);
  edit.matches=selector=>selector==='[data-family-edit-groups]';edit.focus=()=>focus(edit);
  save.focus=()=>focus(save);
  for(const control of [name,edit,save,cancel])control.closest=selector=>selector==='[data-family-member-id]'?row:null;
  row.querySelector=selector=>({'[data-family-name]':name,'[data-family-edit-groups]':edit,'[data-family-save]':save,'[data-family-cancel]':cancel,
   '[data-family-group-badges]':badges,'.family-members-group-badges':badges,
   ...Object.fromEntries(Object.entries(profiles).map(([field,input])=>[`[data-family-profile="${field}"]`,input]))}[selector]||null);
  row.querySelectorAll=selector=>selector.includes('data-family-profile')?Object.values(profiles):[];
  row.children=[name,edit,save,cancel,badges,...Object.values(profiles)];return row;
 });
 page.querySelectorAll=selector=>selector==='[data-family-member-id]'?domRows:selector==='[data-family-edit-groups]'?domRows.map(row=>row.querySelector(selector)):
  selector==='[data-family-focus]'?domRows.flatMap(row=>row.querySelectorAll('[data-family-profile]')):[];
 const row=id=>domRows.find(item=>item.dataset.familyMemberId===id);
 const edit=id=>row(id).querySelector('[data-family-edit-groups]');
 return {editor,choices,title,close,firstChoice,row,edit};
}
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


@pytest.mark.parametrize("field", ["name", "first_name", "last_name"])
def test_async_other_row_completion_keeps_keyboard_focus_and_caret(field):
    run_page(r"""
panel.members.push({id:'sam',name:'Sam',archived:false,meal_count:1});
ctx.document.body={};ctx.document.activeElement=ctx.document.body;
let domRows=[],html='';
page.querySelectorAll=selector=>selector==='[data-family-member-id]'?domRows:
 selector==='[data-family-focus]'?domRows.flatMap(row=>row.querySelectorAll('[data-family-profile]')):[];
Object.defineProperty(page.querySelector('[data-family-rows]'),'innerHTML',{
 get(){return html;},set(value){
  html=value;
  if(ctx.document.activeElement?.closest?.('[data-family-member-id]'))ctx.document.activeElement=ctx.document.body;
  domRows=[...value.matchAll(/<tr[^>]*data-family-member-id="([^"]+)"[^>]*aria-busy="([^"]+)"[^>]*>/g)].map(match=>{
   const controls={};const row={...node(),dataset:{familyMemberId:match[1]},querySelector:selector=>controls[selector],
    querySelectorAll:selector=>selector==='[data-family-profile]'?Object.values(controls).filter(control=>control.dataset.familyProfile):[]};
   for(const key of ['name','save','cancel','archive','first_name','last_name','default_portion']){
    const isProfile=['first_name','last_name','default_portion'].includes(key);
    const selector=isProfile?`[data-family-profile="${key}"]`:`[data-family-${key}]`,control=node();controls[selector]=control;
    if(isProfile)control.dataset={familyProfile:key,familyFocus:match[1]+':'+key};
    control.disabled=match[2]==='true';control.matches=value=>value===selector||(isProfile&&value==='[data-family-profile]');
    control.closest=selector=>selector==='[data-family-member-id]'?row:null;
    control.focus=()=>{ctx.document.activeElement=control;};
    control.setSelectionRange=(start,end)=>{control.selectionStart=start;control.selectionEnd=end;};
   }
   return row;
  });
 }
});
panel.render();let release;ctx.fetch=(url,options)=>new Promise(resolve=>release=resolve);
const pending=panel.update(panel.members[0],{archived:true});
const field=__FIELD__,selector=field==='name'?'[data-family-name]':`[data-family-profile="${field}"]`;
const sam=domRows.find(row=>row.dataset.familyMemberId==='sam').querySelector(selector);
sam.focus();sam.selectionStart=1;sam.selectionEnd=2;sam.value='Samuel';panel.input({target:sam});
release({ok:true,json:async()=>({ok:true,member:{id:'nate',name:'Nate',archived:true,meal_count:3}})});await pending;
const replacement=domRows.find(row=>row.dataset.familyMemberId==='sam').querySelector(selector);
assert.equal(ctx.document.activeElement,replacement);assert.equal(replacement.selectionStart,1);assert.equal(replacement.selectionEnd,2);
assert.equal(field==='name'?panel.drafts.get('sam'):panel.memberProfile(panel.members.at(-1))[field],'Samuel');assert(rows().includes('value="Samuel"'));
assert.notEqual(page.querySelector('[data-family-filter]').focused,true);
""".replace("__FIELD__", repr(field)))


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
panel.profiles.set('nate',{first_name:'Nathan',last_name:'Tyler',default_portion:'0.5',group_ids:['house','friends','house']});
const picker=mountGroupEditorRows();panel.render();assert(rows().includes('value="Nate"'));assert(rows().includes('value="Nathan"'));assert(rows().includes('value="0.5"'));
panel.openGroupEditor(members[0]);
assert.match(picker.choices.innerHTML,/data-family-member-group[^>]+value="house" checked/);assert.match(picker.choices.innerHTML,/data-family-member-group[^>]+value="friends" checked/);
const input=node();input.value='Nate';const row={querySelector:()=>input};
reply={ok:true,member:{...members[0],first_name:'Nathan',last_name:'Tyler',default_portion:0.5,group_ids:['house','friends']}};
await panel.saveRow(row,members[0]);
assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Nate',first_name:'Nathan',last_name:'Tyler',default_portion:0.5,group_ids:['house','friends']});
assert.equal(panel.members[0].name,'Nate');assert.equal(panel.profiles.size,0);assert.equal(panel.members[0].meal_count,3);
panel.search='Nathan Tyler';assert.equal(panel.visibleMembers().length,1);
""")


def test_inline_profile_edits_save_names_fractional_portions_and_group_drafts_together():
    run_page(r"""
panel.members[0]={...members[0],first_name:'Nathan',last_name:'Tyler',default_portion:1,group_ids:['home']};
panel.groups=[{id:'home',name:'Home',archived:false},{id:'friends',name:'Friends',archived:false}];
const picker=mountGroupEditorRows();panel.render();
const row=picker.row('nate'),savedBefore=plain(panel.members[0]);
const markup=rows().match(/<tr[^>]*data-family-member-id="nate"[^>]*>([\s\S]*?)<\/tr>/)[1];
for(const field of ['first_name','last_name','default_portion'])assert(markup.includes(`data-family-profile="${field}"`));
assert(!rows().includes('data-family-details'));assert(!rows().includes('data-family-detail-id'));
for(const [field,value] of Object.entries({first_name:' Nathaniel ',last_name:' Tyler Jr ',default_portion:'0.5'})){
 const input=row.querySelector(`[data-family-profile="${field}"]`);input.value=value;panel.input({target:input});
}
assert.equal(row.querySelector('[data-family-save]').disabled,false);assert.equal(row.querySelector('[data-family-cancel]').hidden,false);
assert.deepEqual(plain(panel.members[0]),savedBefore);assert.equal(requests.length,0);
panel.openGroupEditor(panel.members[0]);
panel.change({target:{value:'friends',checked:true,dataset:{familyMember:'nate'},matches:selector=>selector==='[data-family-member-group]'}});
panel.closeGroupEditor();
reply={ok:true,member:{...savedBefore,first_name:'Nathaniel',last_name:'Tyler Jr',default_portion:0.5,group_ids:['home','friends']}};
await panel.saveRow(row,panel.members[0]);
assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Nate',first_name:'Nathaniel',last_name:'Tyler Jr',default_portion:0.5,group_ids:['home','friends']});
assert.equal(panel.members[0].name,'Nate');assert.equal(panel.profiles.has('nate'),false);assert.equal(panel.dirty(panel.members[0]),false);
assert(rows().includes('value="Nathaniel"'));assert(rows().includes('value="0.5"'));
""")


def test_inline_profile_cancel_restores_all_fields_groups_and_display_name():
    run_page(r"""
panel.members[0]={...members[0],first_name:'Nathan',last_name:'Tyler',default_portion:1,group_ids:['home']};
panel.groups=[{id:'home',name:'Home',archived:false},{id:'friends',name:'Friends',archived:false}];
const picker=mountGroupEditorRows(),row=picker.row('nate');
const input=row.querySelector('[data-family-name]');input.value='Different name';panel.input({target:input});
for(const [field,value] of Object.entries({first_name:'New first',last_name:'New last',default_portion:'2.5'})){
 const input=row.querySelector(`[data-family-profile="${field}"]`);input.value=value;panel.input({target:input});
}
panel.change({target:{value:'friends',checked:true,dataset:{familyMember:'nate'},matches:selector=>selector==='[data-family-member-group]'}});
panel.cancelRow('nate');
assert.equal(panel.drafts.has('nate'),false);assert.equal(panel.profiles.has('nate'),false);assert.equal(panel.dirty(panel.members[0]),false);
assert.deepEqual(plain(panel.memberProfile(panel.members[0])),{first_name:'Nathan',last_name:'Tyler',default_portion:1,group_ids:['home']});
assert(rows().includes('value="Nate"'));assert(rows().includes('value="Nathan"'));assert(rows().includes('value="Tyler"'));
assert(!rows().includes('New first'));assert(!rows().includes('New last'));assert(!rows().includes('Different name'));
assert.equal(ctx.document.activeElement,input);assert.equal(requests.length,0);
""")


def test_inline_invalid_portions_block_save_and_focus_the_field_without_losing_other_drafts():
    run_page(r"""
const picker=mountGroupEditorRows(),row=picker.row('nate');
const first=row.querySelector('[data-family-profile="first_name"]');first.value='Nathan';panel.input({target:first});
const portion=row.querySelector('[data-family-profile="default_portion"]');
for(const value of ['0','-1','','not-a-number']){
 portion.value=value;panel.input({target:portion});ctx.document.activeElement=first;
 await panel.saveRow(row,panel.members[0]);
 assert.equal(requests.length,0);assert.equal(ctx.document.activeElement,portion);
 assert.equal(panel.memberProfile(panel.members[0]).default_portion,value);
 assert.equal(panel.memberProfile(panel.members[0]).first_name,'Nathan');
 assert.match(panel.errors.get('nate'),/greater than zero/i);
 assert.equal(panel.members[0].default_portion,undefined);
}
portion.value='0.25';panel.input({target:portion});
reply={ok:true,member:{...members[0],first_name:'Nathan',last_name:'',default_portion:0.25,group_ids:[]}};
await panel.saveRow(row,panel.members[0]);
assert.equal(requests.length,1);assert.equal(JSON.parse(requests[0].options.body).default_portion,0.25);
assert.equal(panel.errors.has('nate'),false);assert.equal(panel.profiles.has('nate'),false);
""")


def test_inline_profile_keyboard_enter_saves_and_escape_cancels_the_whole_row():
    run_page(r"""
const picker=mountGroupEditorRows(),row=picker.row('nate');
const first=row.querySelector('[data-family-profile="first_name"]'),last=row.querySelector('[data-family-profile="last_name"]');
first.value='Nathan';panel.input({target:first});
let prevented=0;reply={ok:true,member:{...members[0],first_name:'Nathan',last_name:'',default_portion:1,group_ids:[]}};
panel.keydown({target:first,key:'Enter',preventDefault(){prevented++;}});
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(requests.length,1);assert.equal(panel.members[0].first_name,'Nathan');assert.equal(prevented,1);
first.value='Unsaved first';last.value='Unsaved last';panel.input({target:first});panel.input({target:last});
const portion=row.querySelector('[data-family-profile="default_portion"]');portion.value='2';panel.input({target:portion});
panel.keydown({target:last,key:'Escape',preventDefault(){prevented++;}});
assert.equal(prevented,2);assert.equal(panel.profiles.has('nate'),false);assert.equal(requests.length,1);
assert.deepEqual(plain(panel.memberProfile(panel.members[0])),{first_name:'Nathan',last_name:'',default_portion:1,group_ids:[]});
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


def test_status_deep_link_initializes_filter_and_only_accepts_supported_values():
    run_page(r"""
ctx.location={search:'?viewer_user_id=viewer123&status=archived'};
const archived=new ctx.FamilyMembersPage(page,members);
assert.equal(archived.filter,'archived');assert.equal(page.querySelector('[data-family-filter]').value,'archived');
assert(rows().includes('Former member'));assert(!rows().includes('value="Nate"'));
reply={ok:true,members};await archived.load();assert.equal(archived.filter,'archived');
ctx.location.search='?status=all';const all=new ctx.FamilyMembersPage(page,members);assert.equal(all.visibleMembers().length,2);
for(const search of ['', '?status=unknown', '?status=%3Cscript%3E', '?status=ARCHIVED']){
 ctx.location.search=search;const safe=new ctx.FamilyMembersPage(page,members);
 assert.equal(safe.filter,'active');assert.equal(page.querySelector('[data-family-filter]').value,'active');assert.equal(safe.visibleMembers()[0].id,'nate');
}
ctx.location.search='?status=active';assert.equal(new ctx.FamilyMembersPage(page,members).filter,'active');
""")


def test_group_popover_leaves_profile_fields_inline_and_saves_memberships_only_with_row_save():
    run_page(r"""
panel.groups=[{id:'home',name:'Household',archived:false},{id:'friends',name:'Friends',archived:false},{id:'team',name:'Team',archived:false}];
panel.members[0]={...members[0],group_ids:['home'],first_name:'Nathan',last_name:'Tyler',default_portion:1};
panel.members.push({id:'sam',name:'Sam',group_ids:['friends'],archived:false,meal_count:1});
panel.drafts.set('nate','Nate T');panel.drafts.set('sam','Samuel');
panel.profiles.set('nate',{first_name:'Nathan',last_name:'Tyler',default_portion:'0.5',group_ids:['home','team']});
panel.profiles.set('sam',{first_name:'Sam',last_name:'',default_portion:2,group_ids:['friends']});
const profilesBefore=plain([...panel.profiles]),membersBefore=plain(panel.members),draftsBefore=plain([...panel.drafts]);
const picker=mountGroupEditorRows();
panel.render();
assert.match(rows(),/data-family-edit-groups[^>]+aria-label="Edit groups for Nate"/);
panel.click({target:{closest:()=>picker.edit('nate')}});
assert(!rows().includes('data-family-details'));assert(!rows().includes('data-family-detail-id'));
assert.equal(panel.groupEditorMemberId,'nate');assert.equal(picker.editor.popoverOpen,true);
assert.equal(picker.firstChoice.focused,true);
assert.deepEqual(plain([...panel.profiles]),profilesBefore);assert.deepEqual(plain([...panel.drafts]),draftsBefore);
assert.deepEqual(plain(panel.members),membersBefore);assert.equal(requests.length,0);
assert.match(picker.choices.innerHTML,/data-family-member-group[^>]+value="home" checked/);
assert.match(picker.choices.innerHTML,/data-family-member-group[^>]+value="team" checked/);
assert(!rows().includes('data-family-member-group'),'The shared picker is not rendered inside table rows');
panel.change({target:{value:'friends',checked:true,dataset:{familyMember:'nate'},matches:selector=>selector==='[data-family-member-group]'}});
assert.deepEqual(plain(panel.members[0].group_ids),['home'],'Checkbox changes are unsaved row drafts');
assert.equal(requests.length,0);assert.equal(panel.dirty(panel.members[0]),true);
const badges=rows().match(/data-mobile-label="Groups">([\s\S]*?)<\/td>/)[1];
assert(badges.includes('Team'));assert(badges.includes('Friends'),'Row chips reflect the draft selection');
reply={ok:true,member:{...panel.members[0],name:'Nate T',default_portion:0.5,group_ids:['home','team','friends']}};
await panel.saveRow(picker.row('nate'),panel.members[0]);
assert.deepEqual(JSON.parse(requests[0].options.body),{name:'Nate T',first_name:'Nathan',last_name:'Tyler',default_portion:0.5,group_ids:['home','team','friends']});
assert.deepEqual(plain(panel.members[0].group_ids),['home','team','friends']);
assert.deepEqual(plain(panel.members.at(-1).group_ids),['friends']);
assert.equal(panel.drafts.get('sam'),'Samuel');assert.deepEqual(plain(panel.profiles.get('sam')),profilesBefore[1][1]);
""")


def test_empty_group_popover_is_focusable_and_close_preserves_drafts():
    run_page(r"""
const picker=mountGroupEditorRows();panel.drafts.set('nate','Nathan');
panel.openGroupEditor(members[0]);
assert.equal(panel.groupEditorMemberId,'nate');assert.equal(picker.editor.popoverOpen,true);
assert.equal(picker.editor.focused,true);assert(!rows().includes('data-family-details'));
assert(picker.choices.innerHTML.includes('No groups yet'));
panel.click({target:{closest:()=>picker.close}});
assert.equal(picker.editor.popoverOpen,false);assert.equal(picker.edit('nate').focused,true);
assert.equal(panel.drafts.get('nate'),'Nathan');assert.equal(requests.length,0);
picker.edit('nate').disabled=true;picker.editor.focused=false;
panel.click({target:{closest:()=>picker.edit('nate')}});
assert(!rows().includes('data-family-detail-id'));assert.equal(picker.editor.focused,false);assert.equal(picker.editor.popoverOpen,false);
""")


def test_switching_group_popover_keeps_each_members_draft_and_cancel_reverts_only_current_row():
    run_page(r"""
panel.groups=[{id:'home',name:'Home',archived:false},{id:'friends',name:'Friends',archived:false}];
panel.members[0]={...members[0],group_ids:['home']};
panel.members.push({id:'sam',name:'Sam',archived:false,meal_count:0,group_ids:['friends']});
const picker=mountGroupEditorRows();
const toggle=(member,group,checked)=>panel.change({target:{value:group,checked,dataset:{familyMember:member},matches:selector=>selector==='[data-family-member-group]'}});
panel.openGroupEditor(panel.members[0]);toggle('nate','friends',true);panel.closeGroupEditor();
assert.deepEqual(plain(panel.memberProfile(panel.members[0]).group_ids),['home','friends']);
panel.openGroupEditor(panel.members.at(-1));toggle('sam','home',true);
assert.equal(panel.groupEditorMemberId,'sam');assert(picker.title.textContent.includes('Sam'));
assert.match(picker.choices.innerHTML,/data-family-member="sam"/);
panel.openGroupEditor(panel.members[0]);
assert.equal(panel.groupEditorMemberId,'nate');assert.match(picker.choices.innerHTML,/value="friends" checked/);
assert.deepEqual(plain(panel.members[0].group_ids),['home']);assert.deepEqual(plain(panel.members.at(-1).group_ids),['friends']);
panel.cancelRow('nate');
assert.deepEqual(plain(panel.memberProfile(panel.members[0]).group_ids),['home']);
assert.deepEqual(plain(panel.memberProfile(panel.members.at(-1)).group_ids),['friends','home']);
assert.equal(requests.length,0);
""")


def test_group_popover_escape_and_tab_exit_preserve_draft_and_return_to_row_controls():
    run_page(r"""
panel.groups=[{id:'home',name:'Home',archived:false}];
const picker=mountGroupEditorRows();
panel.openGroupEditor(members[0]);
panel.change({target:{value:'home',checked:true,dataset:{familyMember:'nate'},matches:selector=>selector==='[data-family-member-group]'}});
let prevented=0,stopped=0;
const event=(target,key,shiftKey=false)=>({target,key,shiftKey,preventDefault(){prevented++;},stopPropagation(){stopped++;}});
panel.keydown(event(picker.firstChoice,'Escape'));
assert.equal(prevented,1);assert.equal(stopped,1);assert.equal(picker.editor.hidden,true);
assert.equal(ctx.document.activeElement,picker.edit('nate'));
assert.deepEqual(plain(panel.memberProfile(members[0]).group_ids),['home']);assert.equal(requests.length,0);
panel.openGroupEditor(members[0]);panel.keydown(event(picker.firstChoice,'Tab',true));
assert.equal(picker.editor.hidden,true);assert.equal(ctx.document.activeElement,picker.edit('nate'));
panel.openGroupEditor(members[0]);panel.keydown(event(picker.close,'Tab'));
assert.equal(picker.editor.hidden,true);assert.equal(ctx.document.activeElement,picker.row('nate').querySelector('[data-family-save]'));
panel.openGroupEditor(members[0]);picker.row('nate').querySelector('[data-family-save]').disabled=true;
panel.keydown(event(picker.close,'Tab'));
assert.equal(ctx.document.activeElement,picker.row('nate').querySelector('[data-family-profile="default_portion"]'));
assert.equal(prevented,4);assert.deepEqual(plain(panel.memberProfile(members[0]).group_ids),['home']);
assert.equal(requests.length,0);
""")


def test_group_popover_outside_dismissal_keeps_other_controls_focus_and_unsaved_changes():
    run_page(r"""
panel.groups=[{id:'home',name:'Home',archived:false}];
const picker=mountGroupEditorRows();panel.openGroupEditor(members[0]);
panel.change({target:{value:'home',checked:true,dataset:{familyMember:'nate'},matches:selector=>selector==='[data-family-member-group]'}});
const emit=(type,target)=>documentEvents[type].forEach(handler=>handler({target}));
emit('pointerdown',picker.firstChoice);emit('focusin',picker.firstChoice);
assert.equal(panel.groupEditorMemberId,'nate','Interacting inside the picker keeps it open');
const otherControl=node();otherControl.closest=selector=>selector==='button, input, select, textarea, a[href], [tabindex]'?otherControl:null;
ctx.document.activeElement=otherControl;emit('pointerdown',otherControl);
assert.equal(picker.editor.hidden,true);assert.equal(ctx.document.activeElement,otherControl);
panel.openGroupEditor(members[0]);ctx.document.activeElement=otherControl;emit('focusin',otherControl);
assert.equal(picker.editor.hidden,true);assert.equal(ctx.document.activeElement,otherControl);
assert.deepEqual(plain(panel.memberProfile(members[0]).group_ids),['home']);assert.equal(requests.length,0);
""")


def test_group_popover_reanchors_on_scroll_resize_and_closes_when_member_is_filtered_out():
    run_page(r"""
panel.groups=[{id:'home',name:'Home',archived:false}];
panel.members.push({id:'sam',name:'Sam',archived:false,meal_count:0});
const picker=mountGroupEditorRows(),positions=[];
ctx.MasterDataAliasEditor={positionPopover(editor,anchor){positions.push({editor,anchor});}};
panel.openGroupEditor(members[0]);
assert.equal(positions.at(-1).editor,picker.editor);assert.equal(positions.at(-1).anchor,picker.edit('nate'));
assert.equal(picker.editor.showCount,1);
documentEvents.scroll.forEach(handler=>handler());windowEvents.resize.forEach(handler=>handler());
assert.equal(positions.length,3);assert(positions.every(item=>item.anchor===picker.edit('nate')));
panel.openGroupEditor(panel.members.at(-1));
assert.equal(positions.at(-1).anchor,picker.edit('sam'));assert.equal(picker.editor.showCount,1,'The shared popover stays open when switching members');
panel.drafts.set('sam','Samuel');panel.search='Nate';panel.render();
assert.equal(panel.groupEditorMemberId,'');assert.equal(picker.editor.hidden,true);assert.equal(picker.editor.popoverOpen,false);
const count=positions.length;documentEvents.scroll.forEach(handler=>handler());assert.equal(positions.length,count);
assert.equal(panel.drafts.get('sam'),'Samuel');assert.equal(requests.length,0);
""")
