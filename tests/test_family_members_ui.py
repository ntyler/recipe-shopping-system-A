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
 focus(){this.focused=true;},reportValidity(){return true;}};}
const nodes=new Map();
const page={dataset:{apiUrl:'/api/meal-plan/members'},handlers:{},
 addEventListener(k,v){this.handlers[k]=v;},querySelectorAll(){return [];},
 querySelector(selector){if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);}};
const createForm=page.querySelector('[data-family-create]'),createInput=node(),createError=node(),createButton=node(),cancelButton=node();
createForm.querySelector=selector=>selector==='input'?createInput:createError;
createForm.querySelectorAll=()=>[createInput,createButton,cancelButton];createForm.hidden=true;
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
assert(rows().includes('Sam'));assert.deepEqual(JSON.parse(requests[1].options.body),{name:'Sam'});
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
input.closest=()=>row;panel.input({target:input});assert.equal(save.disabled,false);assert.equal(cancel.hidden,false);
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
