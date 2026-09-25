"""Global search favorites interactions using production JS at a DOM boundary.

These checks exercise requests, rendering, keyboard navigation, and stale-request
handling. They do not claim browser layout or native focus verification.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SEARCH_JS = ROOT / "PushShoppingList/static/js/app.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for search interaction checks")


def run_search(script):
    bootstrap = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const plain=value=>JSON.parse(JSON.stringify(value));
const camel=value=>value.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
let document;
function element(tag='div',attributes={}) {
 const values=new Set(),el={tag,attrs:{},dataset:{},children:[],handlers:{},parentElement:null,hidden:false,disabled:false,value:'',ownText:'',
  classList:{add(...names){names.forEach(name=>values.add(name));},remove(...names){names.forEach(name=>values.delete(name));},contains(name){return values.has(name);},toggle(name,on){if(on??!values.has(name))values.add(name);else values.delete(name);},[Symbol.iterator](){return values.values();}},
  setAttribute(name,value){this.attrs[name]=String(value);if(name.startsWith('data-'))this.dataset[camel(name.slice(5))]=String(value);if(name==='id')this.id=String(value);if(name==='class')this.className=value;},
  getAttribute(name){return this.attrs[name]??null;},removeAttribute(name){delete this.attrs[name];},
  append(...children){for(const child of children){const node=typeof child==='string'?text(child):child;node.parentElement=this;this.children.push(node);}},
  replaceChildren(...children){this.children=[];this.ownText='';this.append(...children);},
  addEventListener(type,handler){(this.handlers[type] ||= []).push(handler);},
  dispatch(type,event={}){for(const handler of this.handlers[type]||[])handler({target:this,preventDefault(){},...event});},
  contains(target){return target===this||this.children.some(child=>child.contains(target));},
  matches(selector){return selector.split(',').some(part=>{part=part.trim();if(part===this.tag)return true;if(part.startsWith('.'))return this.classList.contains(part.slice(1));const attr=part.match(/^\[([^=\]]+)(?:=["']([^"']*)["'])?\]$/);if(!attr)return false;const value=attr[1].startsWith('data-')?this.dataset[camel(attr[1].slice(5))]:this.attrs[attr[1]];return value!==undefined&&(attr[2]===undefined||value===attr[2]);});},
  querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);},
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;},
  closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector)||null;},
  focus(){if(document.activeElement!==this){document.activeElement=this;this.dispatch('focus');}},scrollIntoView(){},
 };
 Object.defineProperty(el,'className',{get:()=>[...values].join(' '),set:value=>{values.clear();String(value).split(/\s+/).filter(Boolean).forEach(name=>values.add(name));}});
 Object.defineProperty(el,'textContent',{get(){return this.ownText+this.children.map(child=>child.textContent).join('');},set(value){this.ownText=String(value);this.children=[];}});
 Object.defineProperty(el,'innerHTML',{set(){throw new Error('Search must render text safely through DOM nodes');}});
 Object.entries(attributes).forEach(([name,value])=>el.setAttribute(name,value));return el;
}
function text(value){const result=element('#text');result.textContent=value;return result;}
const input=element('input',{'id':'headerSearch','data-app-global-search':'','name':'q'});
const dropdown=element('div',{'data-global-search-dropdown':''});dropdown.hidden=true;
const favorites=element('button',{'data-global-search-favorites':'','aria-pressed':'false'});
const favoritesValue=element('input',{'data-global-search-favorites-value':'','name':'favorites','type':'hidden'});favoritesValue.value='1';favoritesValue.disabled=true;
const content=element('div',{'data-global-search-content':''}),visibleStatus=element('div',{'data-global-search-visible-status':''});dropdown.append(favorites,visibleStatus,content);
const form=element('form',{'data-global-search-form':'','data-global-search-endpoint':'/api/global-search?viewer_user_id=account-1','data-global-search-results-url':'/search?viewer_user_id=account-1','data-global-search-recent-url':'/api/global-search/recent?viewer_user_id=account-1','data-global-search-viewer-user-id':'account-1','data-global-search-spa':'false'});
form.append(input,favoritesValue,dropdown);
const pageShortcut=element('a',{'href':'/#recipesPage','data-global-search-page-shortcut':'','data-global-search-title':'Recipes'});
const quickShortcut=element('a',{'href':'/#importPage','data-global-search-quick-action':'','data-global-search-title':'Import'});
document={activeElement:null,documentElement:element('html'),handlers:{},
 createElement:element,createTextNode:text,createDocumentFragment:()=>element('#fragment'),
 querySelectorAll(selector){if(selector==='[data-global-search-form]')return [form];if(selector.includes('data-global-search-page-shortcut'))return [pageShortcut];if(selector.includes('data-global-search-quick-action'))return [quickShortcut];return [];},
 addEventListener(type,handler){(this.handlers[type] ||= []).push(handler);},
};
const timers=new Map(),requests=[],navigations=[],announcements=[];let timerId=0,respond=async()=>ok({groups:[],total_count:0});
const window={location:{origin:'https://example.test',assign:url=>navigations.push(String(url))},
 setTimeout(callback,delay){const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id)};
const ctx={console,window,document,URL,AbortController,Set,
 appShellSetSearchStatus:message=>announcements.push(message),normalizeAppShellSearchText:value=>String(value).trim().toLowerCase(),
 appShellNavTargetId:link=>link.getAttribute('href').split('#')[1]||'',activateAppShellNavLink:()=>{},
 fetch:async(url,options={})=>{const call={url:new URL(String(url),window.location.origin),options};requests.push(call);return respond(call);},
};
vm.createContext(ctx);const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInContext(source.slice(source.indexOf('const GLOBAL_APP_SEARCH_DEBOUNCE_MS'),source.indexOf('function recipeBrowseCards')),ctx);
const ok=data=>({ok:true,json:async()=>({ok:true,...data})});
const fail=error=>({ok:false,json:async()=>({ok:false,error})});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const flush=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
const runTimers=async()=>{const pending=[...timers.values()];timers.clear();pending.forEach(timer=>timer.callback());await flush();};
const result=(title='Corn <bread>',extra={})=>({id:'recipe-1',title,type:'Recipe',secondary:'Saved recipe',url:'/recipe/edit?viewer_user_id=wrong&user_id=legacy&url=recipe%3A%2F%2Fbread',icon:'recipes',...extra});
const recipeResults=(title='Corn <bread>')=>({groups:[{key:'recipes',label:'Recipes',results:[result(title)]}],total_count:1});
const type=async value=>{input.value=value;input.dispatch('input');await runTimers();};
const toggleFavorites=async()=>{ctx.toggleGlobalAppSearchFavorites(form);await runTimers();};
(async()=>{
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", bootstrap + script + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", str(SEARCH_JS)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_search_runtime_baseline_debounce_safe_rendering_and_canonical_result_navigation():
    run_search(r"""
ctx.initGlobalAppSearch();ctx.initGlobalAppSearch();assert.equal(input.handlers.input.length,1);
respond=async()=>ok(recipeResults());input.value='co';input.dispatch('input');input.value='corn';input.dispatch('input');
assert.equal(requests.length,0);assert.equal(timers.size,1);assert.equal([...timers.values()][0].delay,250);
await runTimers();assert.equal(requests.length,1);assert.equal(requests[0].url.searchParams.get('q'),'corn');
assert.equal(requests[0].url.searchParams.get('viewer_user_id'),'account-1');assert.equal(requests[0].options.cache,'no-store');
assert.equal(dropdown.hidden,false);assert.equal(input.getAttribute('aria-expanded'),'true');
assert(content.textContent.includes('Corn <bread>'));assert.equal(content.querySelectorAll('script').length,0);
input.dispatch('keydown',{key:'ArrowDown'});assert.equal(form._globalSearchActiveIndex,0);
input.dispatch('keydown',{key:'Enter'});assert.equal(navigations.length,1);
const target=new URL(navigations[0],window.location.origin);assert.equal(target.pathname,'/recipe/edit');
assert.equal(target.searchParams.get('viewer_user_id'),'account-1');assert.equal(target.searchParams.has('user_id'),false);
assert.equal(dropdown.hidden,true);assert.equal(requests.at(-1).options.method,'POST');
assert.deepEqual(JSON.parse(requests.at(-1).options.body),{group:'recipes',id:'recipe-1'});
""")


def test_favorites_toggle_browses_with_empty_query_and_preserves_filter_for_enter_and_view_all():
    run_search(r"""
ctx.initGlobalAppSearch();respond=async()=>ok(recipeResults());
ctx.toggleGlobalAppSearchFavorites(form);assert.equal(favoritesValue.disabled,false);assert.equal(favoritesValue.value,'1');
assert.equal(favorites.getAttribute('aria-pressed'),'true');assert.equal(requests.length,0);
assert.equal([...timers.values()][0].delay,250);await runTimers();
assert.equal(requests.length,1);const endpoint=requests[0].url;
assert.equal(endpoint.pathname,'/api/global-search');assert.equal(endpoint.searchParams.get('q'),'');
assert.equal(endpoint.searchParams.get('favorites'),'1');assert.equal(endpoint.searchParams.get('viewer_user_id'),'account-1');
assert.equal(content.textContent.includes('RECENT'),false);assert.equal(content.textContent.includes('QUICK ACTIONS'),false);assert.equal(content.textContent.includes('PAGES'),false);
assert(form._globalSearchResults.some(result=>result.title==='Corn <bread>'));
const viewAll=form._globalSearchResults.findIndex(result=>result.isViewAll);assert(viewAll>=0,'Empty-query favorites still offer full results');
ctx.submitGlobalAppSearch(form);assert.equal(navigations.length,1);
let target=new URL(navigations[0],window.location.origin);assert.equal(target.pathname,'/search');assert.equal(target.searchParams.get('q')||'','');assert.equal(target.searchParams.get('favorites'),'1');assert.equal(target.searchParams.get('viewer_user_id'),'account-1');
const option=form.querySelectorAll('[data-global-search-result]')[viewAll];form.dispatch('click',{target:option,button:0});
target=new URL(navigations[1],window.location.origin);assert.equal(target.pathname,'/search');assert.equal(target.searchParams.get('favorites'),'1');assert.equal(target.searchParams.get('viewer_user_id'),'account-1');
assert.equal(requests.filter(call=>call.options.method==='POST').length,0,'Browsing favorites must not change favorites or record View all as a visited recipe');
""")


def test_favorites_typed_query_narrows_results_keeps_minimum_length_and_can_return_to_normal_search():
    run_search(r"""
ctx.initGlobalAppSearch();respond=async()=>ok(recipeResults());await toggleFavorites();
let count=requests.length;await type('c');assert.equal(requests.length,count);assert.match(visibleStatus.textContent,/2 characters/);
await type('  corn  ');assert.equal(requests.at(-1).url.searchParams.get('q'),'corn');assert.equal(requests.at(-1).url.searchParams.get('favorites'),'1');
assert.equal(input.value,'  corn  ');assert(!form._globalSearchResults.some(result=>result.group==='pages'));
ctx.submitGlobalAppSearch(form);let target=new URL(navigations.at(-1),window.location.origin);assert.equal(target.searchParams.get('q'),'corn');assert.equal(target.searchParams.get('favorites'),'1');
await toggleFavorites();assert.equal(favoritesValue.disabled,true);assert.equal(favorites.getAttribute('aria-pressed'),'false');
assert.equal(requests.at(-1).url.searchParams.get('favorites'),null);assert.equal(requests.at(-1).url.searchParams.get('q'),'corn');
ctx.submitGlobalAppSearch(form);target=new URL(navigations.at(-1),window.location.origin);assert.equal(target.searchParams.has('favorites'),false);
respond=async()=>ok({groups:[{key:'recent',results:[result('Recently opened',{tracking_group:'recipes'})]}]});
await type('');await flush();assert(content.textContent.includes('RECENT'));assert(content.textContent.includes('QUICK ACTIONS'));assert(content.textContent.includes('PAGES'));
""")


@pytest.mark.parametrize("late_result", ["success", "error"])
def test_changing_favorites_rejects_late_unfiltered_response_even_when_query_is_unchanged(late_result):
    run_search(r"""
ctx.initGlobalAppSearch();const old=deferred(),fresh=deferred();let index=0;respond=()=>[old.promise,fresh.promise][index++];
await type('corn');assert.equal(requests.length,1);const oldSignal=requests[0].options.signal;
await toggleFavorites();assert.equal(requests.length,2);assert.equal(oldSignal.aborted,true);
fresh.resolve(ok(recipeResults('Favorite corn')));await flush();assert(content.textContent.includes('Favorite corn'));
old.resolve(__LATE__==='success'?ok(recipeResults('Unfiltered corn')):fail('Old search failed.'));await flush();
assert(content.textContent.includes('Favorite corn'));assert(!content.textContent.includes('Unfiltered corn'));assert.equal(visibleStatus.hidden,true);
assert.equal(input.getAttribute('aria-busy'),null);assert.equal(favorites.getAttribute('aria-pressed'),'true');
""".replace("__LATE__", repr(late_result)))


def test_late_recent_items_cannot_replace_empty_query_favorites():
    run_search(r"""
ctx.initGlobalAppSearch();const recent=deferred(),favoriteResults=deferred();let index=0;respond=()=>[recent.promise,favoriteResults.promise][index++];
input.focus();assert.equal(requests.length,1);assert.equal(requests[0].url.searchParams.has('favorites'),false);
await toggleFavorites();assert.equal(requests.length,2);favoriteResults.resolve(ok(recipeResults('Favorite bread')));await flush();
recent.resolve(ok({groups:[{key:'recent',results:[result('Old recent',{tracking_group:'recipes'})]}]}));await flush();
assert(content.textContent.includes('Favorite bread'));assert(!content.textContent.includes('Old recent'));assert(!content.textContent.includes('QUICK ACTIONS'));assert.equal(dropdown.hidden,false);
""")


@pytest.mark.parametrize("dismissal", ["escape", "outside"])
def test_dismissed_favorites_search_does_not_reopen_after_delayed_response(dismissal):
    run_search(r"""
ctx.initGlobalAppSearch();const pending=deferred();respond=()=>pending.promise;await toggleFavorites();
assert.equal(requests.length,1);assert.equal(dropdown.hidden,false);
if(__DISMISSAL__==='escape')input.dispatch('keydown',{key:'Escape'});
else for(const handler of document.handlers.pointerdown||[])handler({target:element('div')});
assert.equal(dropdown.hidden,true);assert.equal(input.getAttribute('aria-expanded'),'false');assert.equal(requests[0].options.signal.aborted,true);
pending.resolve(ok(recipeResults()));await flush();assert.equal(dropdown.hidden,true);assert.equal(input.getAttribute('aria-expanded'),'false');
assert.equal(input.getAttribute('aria-busy'),null);
""".replace("__DISMISSAL__", repr(dismissal)))


def test_dismissal_before_debounce_cancels_queued_favorites_fetch():
    run_search(r"""
ctx.initGlobalAppSearch();respond=async()=>ok(recipeResults());ctx.toggleGlobalAppSearchFavorites(form);
assert.equal(timers.size,1);assert.equal(requests.length,0);input.dispatch('keydown',{key:'Escape'});
await runTimers();assert.equal(requests.length,0);assert.equal(dropdown.hidden,true);assert.equal(favoritesValue.disabled,false);
""")


def test_favorites_empty_and_error_states_remain_in_filter_and_can_retry():
    run_search(r"""
ctx.initGlobalAppSearch();respond=async()=>ok({groups:[],total_count:0});await toggleFavorites();
assert.match(visibleStatus.textContent,/favorite/i);assert.equal(content.textContent.includes('QUICK ACTIONS'),false);
respond=async()=>fail('Unavailable');await type('bread');assert.match(visibleStatus.textContent,/Search could not be completed/);
assert.equal(favoritesValue.disabled,false);assert.equal(favorites.getAttribute('aria-pressed'),'true');
respond=async()=>ok(recipeResults('Bread'));input.dispatch('input');await runTimers();
assert(content.textContent.includes('Bread'));assert.equal(visibleStatus.hidden,true);assert.equal(requests.at(-1).url.searchParams.get('favorites'),'1');
""")


def test_initial_favorites_form_state_is_respected_on_focus_and_keyboard_recipe_open():
    run_search(r"""
favoritesValue.disabled=false;favorites.setAttribute('aria-pressed','true');ctx.initGlobalAppSearch();respond=async()=>ok(recipeResults());
input.focus();await runTimers();assert.equal(requests[0].url.searchParams.get('favorites'),'1');
input.dispatch('keydown',{key:'ArrowDown'});assert.equal(form._globalSearchActiveIndex,0);input.dispatch('keydown',{key:'Enter'});
const target=new URL(navigations.at(-1),window.location.origin);assert.equal(target.pathname,'/recipe/edit');assert.equal(target.searchParams.get('viewer_user_id'),'account-1');
assert.equal(target.searchParams.has('favorites'),false,'The search filter is not a recipe mutation or recipe URL parameter');
assert.equal(requests.at(-1).options.method,'POST');assert.deepEqual(JSON.parse(requests.at(-1).options.body),{group:'recipes',id:'recipe-1'});
""")
