"""Weekly planner rendering and prep-task completion behavior."""

from pathlib import Path
from html.parser import HTMLParser
import shutil
import subprocess

from jinja2 import Environment
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_meal_cards_use_compact_actions_with_correct_ids_and_batch_scope_choices():
    class Buttons(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons = []
            self.menus = []
            self.cards = []
            self.stack = []
            self.current = None

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if "data-meal-card-menu" in attributes:
                self.menus.append(attributes)
            if "data-meal-plan-id" in attributes:
                self.cards.append(attributes)
            if tag == "button":
                parent = next((attrs for _, attrs in reversed(self.stack) if "data-meal-card-menu" in attrs), None)
                self.current = {"attrs": attributes, "text": "", "menu": parent}
                self.buttons.append(self.current)
            if tag not in {"img", "input", "br", "hr", "meta", "link"}:
                self.stack.append((tag, attributes))

        def handle_data(self, data):
            if self.current is not None:
                self.current["text"] += data

        def handle_endtag(self, tag):
            if tag == "button":
                self.current = None
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    source = (ROOT / "PushShoppingList/templates/sections/app_workspaces.html").read_text(encoding="utf-8")
    start = source.index('<section class="app-meal-planner-grid"')
    template = Environment(autoescape=True).from_string(source[start:source.index("</section>", start)])
    standalone = {"id": 'meal"<one>', "recipe_url": "recipe://bread", "recipe_name": 'Bread " & <meal>', "planned_servings": 1}
    batched = {**standalone, "id": "meal-2", "batch_id": 'batch"<one>'}
    html = template.render(meal_plan={
        "days": [{"date": "2026-10-05", "weekday": "Mon", "day_label": "10/5"}],
        "meal_types": ["dinner"], "meals_by_day": {"2026-10-05": {"dinner": [standalone, batched]}},
        "prep_steps_by_day": {},
    }, meal_plan_recipe_options=[standalone])
    parser = Buttons()
    parser.feed(html)
    triggers = [button for button in parser.buttons if "data-meal-card-actions-toggle" in button["attrs"]]
    assert len(triggers) == 2
    assert all("app-meal-actions-toggle" in button["attrs"]["class"].split() for button in triggers)
    assert [button["attrs"]["data-meal-id"] for button in triggers] == [standalone["id"], "meal-2"]
    assert [button["attrs"]["data-batch-id"] for button in triggers] == ["", batched["batch_id"]]
    assert all(button["attrs"]["onclick"] == "return toggleMealPlannerCardMenu(this)" for button in triggers)
    assert triggers[0]["attrs"]["data-meal-name"] == standalone["recipe_name"]
    assert standalone["recipe_name"] in triggers[0]["attrs"]["aria-label"]
    assert not any(button["attrs"].get("class") in {"app-meal-edit", "app-meal-remove"} for button in parser.buttons)
    assert len(parser.menus) == 2
    assert [card["data-meal-plan-id"] for card in parser.cards] == [standalone["id"], batched["id"]]
    assert [card["data-meal-plan-batch-id"] for card in parser.cards] == ["", batched["batch_id"]]
    for trigger, expected_options in zip(triggers, [
        ["Edit meal", "Remove this meal"],
        ["Edit this meal", "Edit entire prep plan", "Shop this prep batch", "Remove this meal", "Remove entire prep batch"],
    ]):
        menu = next(menu for menu in parser.menus if menu["id"] == trigger["attrs"]["data-menu-id"])
        assert menu["data-trigger-id"] == trigger["attrs"]["id"]
        assert menu["popover"] == "auto"
        actions = [button for button in parser.buttons if button["menu"] is menu]
        assert [button["text"].strip() for button in actions] == expected_options
        assert all("runMealPlannerCardAction" in button["attrs"]["onclick"] for button in actions)
        previews = [button["attrs"]["data-meal-delete-preview"] for button in actions if "data-meal-delete-preview" in button["attrs"]]
        assert previews == (["meal", "batch"] if trigger["attrs"]["data-batch-id"] else ["meal"])
    assert '<meal>' not in html and '<one>' not in html
    assert 'data-meal-prep-date=' not in html
    assert '>Prep</div>' not in html

    scope_start = source.index('<section class="app-meal-edit-scope"')
    scope = Buttons()
    scope.feed(source[scope_start:source.index("</section>", scope_start)])
    assert len(scope.buttons) == 2
    assert scope.buttons[0]["text"].startswith("Edit this meal")
    assert scope.buttons[0]["attrs"]["onclick"] == "return loadMealPlannerEdit('meal')"
    assert scope.buttons[1]["text"].startswith("Edit entire prep plan")
    assert scope.buttons[1]["attrs"]["onclick"] == "return loadMealPlannerEdit('batch')"


def test_weekly_grid_places_prep_steps_on_their_dates_and_labels_batch_meals():
    source = (ROOT / "PushShoppingList/templates/sections/app_workspaces.html").read_text(encoding="utf-8")
    grid_start = source.index('<section class="app-meal-planner-grid"')
    template = Environment(autoescape=True).from_string(source[grid_start:source.index("</section>", grid_start)])
    days = [
        {"date": "2026-09-28", "weekday": "Mon", "day_label": "9/28"},
        {"date": "2026-09-29", "weekday": "Tue", "day_label": "9/29"},
    ]
    meal = {"id": "meal-1", "recipe_url": "recipe://bread", "recipe_name": "Bread", "planned_servings": 2.5, "batch_id": "batch-1"}
    step = {"id": "step-1", "batch_id": "batch-1", "recipe_url": "recipe://bread", "recipe_name": "Bread", "instruction": "Chop <onions>", "completed": True}
    context = {
        "days": days, "meal_types": ["dinner"],
        "meals_by_day": {"2026-09-28": {"dinner": []}, "2026-09-29": {"dinner": [meal]}},
        "prep_steps_by_day": {"2026-09-28": [step], "2026-09-29": []},
    }
    html = template.render(meal_plan=context, meal_plan_recipe_options=[meal])
    monday = html.split('data-meal-prep-date="2026-09-28"', 1)[1].split('data-meal-prep-date="2026-09-29"', 1)[0]
    assert 'data-batch-id="batch-1"' in monday
    assert 'data-step-id="step-1"' in monday
    assert 'data-meal-prep-batch-id="batch-1"' in monday
    assert 'checked' in monday
    assert 'Chop &lt;onions&gt;' in monday
    assert 'data-recipe-url="recipe://bread"' in monday
    assert 'No prep steps for Tue 9/29' in html
    assert html.index('>Prep</div>') < html.index('>Dinner</div>')
    assert '2.5 servings' in html
    assert 'Prep batch' in html

    # Legacy contexts without batches still render the ordinary meal grid.
    context.pop("prep_steps_by_day")
    meal.pop("batch_id")
    meal["planned_servings"] = 1
    legacy_html = template.render(meal_plan=context, meal_plan_recipe_options=[meal])
    assert '1 serving' in legacy_html
    assert 'Prep batch' not in legacy_html
    assert 'data-meal-prep-date=' not in legacy_html
    assert '>Prep</div>' not in legacy_html

    meal["member_portions"] = [
        {"member_id": "adult", "name": "Updated <name>", "name_snapshot": "Previous name", "servings": 1},
        {"member_id": "child", "name_snapshot": "Child", "servings": 0.5},
    ]
    meal["planned_servings"] = 1.5
    family_html = template.render(meal_plan=context, meal_plan_recipe_options=[meal])
    assert family_html.count('data-meal-plan-id="meal-1"') == 1
    assert 'data-meal-family-details="meal-1"' in family_html
    assert 'Family portions (2)' in family_html
    assert 'Updated &lt;name&gt;' in family_html
    assert 'Previous name' not in family_html
    assert '<span>Child</span><span>0.5 servings</span>' in family_html
    assert '<span>1 serving</span>' in family_html


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for the interaction check")
def test_weekly_prep_completion_commits_success_and_reverts_failures():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const handler = source.slice(source.indexOf('async function toggleMealPlannerPrepStep'), source.indexOf('function formatMealPlannerServingNumber'));
function classes() {
    const values = new Set();
    return {add: x => values.add(x), remove: x => values.delete(x), has: x => values.has(x), toggle: (x, present) => present ? values.add(x) : values.delete(x)};
}
const status = {hidden: true, textContent: '', classList: classes()};
const card = {classList: classes(), querySelector: () => status};
const input = {checked: true, disabled: false, dataset: {batchId: 'batch/1', stepId: 'step/1'}, closest: () => card};
let calls = [];
let respond;
const ctx = {fetch: async (url, options) => {calls.push({url, options}); return respond();}};
vm.createContext(ctx);
vm.runInContext(handler, ctx);
(async () => {
    let release;
    respond = () => new Promise(resolve => {release = resolve});
    const pending = ctx.toggleMealPlannerPrepStep(input);
    assert.equal(input.disabled, true);
    await ctx.toggleMealPlannerPrepStep(input);
    assert.equal(calls.length, 1, 'A pending save cannot be submitted twice');
    release({ok: true, json: async () => ({ok: true, step: {completed: true}})});
    await pending;
    assert.equal(calls[0].url, '/api/meal-plan/batches/batch%2F1/prep-steps/step%2F1');
    assert.equal(calls[0].options.method, 'PATCH');
    assert.deepEqual(JSON.parse(calls[0].options.body), {completed: true});
    assert.equal(input.checked, true);
    assert.equal(input.disabled, false);
    assert.equal(card.classList.has('is-complete'), true);
    assert.equal(status.textContent, 'Completed.');

    input.checked = false;
    respond = async () => ({ok: false, json: async () => ({error: 'Please try again.'})});
    await ctx.toggleMealPlannerPrepStep(input);
    assert.equal(input.checked, true, 'A rejected uncheck returns to completed');
    assert.equal(card.classList.has('is-complete'), true);
    assert.equal(status.textContent, 'Please try again.');
    assert.equal(status.classList.has('error'), true);
    assert.equal(input.disabled, false);

    input.checked = false;
    respond = async () => ({ok: true, json: async () => ({ok: true, step: {completed: false}})});
    await ctx.toggleMealPlannerPrepStep(input);
    assert.equal(input.checked, false);
    assert.equal(card.classList.has('is-complete'), false);
    assert.equal(status.classList.has('error'), false);

    input.checked = true;
    respond = async () => {throw new Error('Network unavailable.');};
    await ctx.toggleMealPlannerPrepStep(input);
    assert.equal(input.checked, false, 'An offline save returns to incomplete');
    assert.equal(input.disabled, false);
    assert.equal(status.textContent, 'Network unavailable.');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", script, str(ROOT / "PushShoppingList/static/js/app.js")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for the interaction check")
def test_visible_planner_url_tracks_loaded_week_without_disturbing_preview_or_failed_refreshes():
    script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const handler = source.slice(source.indexOf('let mealPlannerRefreshController'), source.indexOf('function openMealPlannerPageAndDialog'));
let dialogOpen = false, calls = [], replacements = [], responseFactory;
const status = {hidden:true,textContent:'',classList:{add(){}}};
const page = {
 dataset:{mealWeek:'2026-09-21'},hidden:false,inert:false,innerHTML:'old-week',
 setAttribute(){},removeAttribute(){},querySelectorAll(){return [];},
 querySelector(selector){return selector === 'dialog[open]' ? dialogOpen : status;},
};
const historyState = {workspace:'mealPlannerPage',unrelatedState:{keep:true}};
const window = {
 location:new URL('https://pantry.test/?meal_week=2026-09-21&viewer_user_id=test-user&scope=household#mealPlannerPage'),
 history:{state:historyState,replaceState(state,title,url){
  replacements.push({state,title,url:String(url)});
  this.state=state;window.location=new URL(String(url),window.location.href);
 }},
};
const ctx = {
 AbortController,Set,URL,window,document:{getElementById:()=>page},
 withCanonicalViewerUserId:url=>`${url}&viewer_user_id=test-user`,initDeferredImages(){},
 DOMParser:class {parseFromString(week){return {getElementById:()=>({innerHTML:`week:${week}`,dataset:{mealWeek:week}})};}},
 fetch:async(url,options)=>{calls.push({url,options});return responseFactory();},
};
vm.createContext(ctx);vm.runInContext(handler,ctx);
const ok = week => ({ok:true,redirected:false,text:async()=>week});
(async()=>{
 responseFactory=()=>ok('2026-10-05');
 assert.equal(await ctx.refreshMealPlannerWorkspace({date:'2026-10-07'}),true);
 assert.equal(window.location.searchParams.get('meal_week'),'2026-10-05','Reload must reopen the week actually displayed');
 assert.equal(window.location.pathname,'/');assert.equal(window.location.hash,'#mealPlannerPage');
 assert.equal(window.location.searchParams.get('viewer_user_id'),'test-user');
 assert.equal(window.location.searchParams.get('scope'),'household');
 assert.equal(replacements.length,1);assert.equal(replacements[0].state,historyState,'Keep existing browser history state');
 const visibleUrl=window.location.href;

 page.hidden=true;responseFactory=()=>ok('2026-11-02');
 assert.equal(await ctx.refreshMealPlannerWorkspace({date:'2026-11-03'}),true);
 assert.equal(window.location.href,visibleUrl,'Updating a hidden planner must not change the active workspace URL');
 page.hidden=false;page.inert=true;responseFactory=()=>ok('2026-12-07');
 assert.equal(await ctx.refreshMealPlannerWorkspace({date:'2026-12-09'}),true);
 assert.equal(window.location.href,visibleUrl,'The planner underneath recipe preview must not take over its URL');
 page.inert=false;window.location.hash='#recipe-preview';
 const previewUrl=window.location.href;responseFactory=()=>ok('2027-01-04');
 assert.equal(await ctx.refreshMealPlannerWorkspace(),true);
 assert.equal(window.location.href,previewUrl);assert.equal(replacements.length,1);

 window.location.hash='#mealPlannerPage';const beforeFailure=window.location.href;
 responseFactory=()=>({ok:false});
 assert.equal(await ctx.refreshMealPlannerWorkspace({date:'2027-02-02'}),false);
 assert.equal(window.location.href,beforeFailure);assert.equal(replacements.length,1);
 dialogOpen=true;const beforeDeferred=calls.length;
 assert.equal(await ctx.refreshMealPlannerWorkspace({date:'2027-03-02'}),false);
 assert.equal(calls.length,beforeDeferred);assert.equal(window.location.href,beforeFailure);
 assert.equal(replacements.length,1,'Neither failed nor deferred requests change the URL');
 dialogOpen=false;responseFactory=()=>ok('2027-03-01');
 assert.equal(await ctx.refreshMealPlannerWorkspace(),true);
 assert.match(calls.at(-1).url,/meal_week=2027-03-02/,'Retry retains the requested future week');
 assert.equal(window.location.searchParams.get('meal_week'),'2027-03-01');assert.equal(replacements.length,2);

 let releaseOld;responseFactory=()=>new Promise(resolve=>releaseOld=resolve);
 const old=ctx.refreshMealPlannerWorkspace({date:'2027-04-01'});
 responseFactory=()=>ok('2027-05-03');
 assert.equal(await ctx.refreshMealPlannerWorkspace({date:'2027-05-05'}),true);
 releaseOld(ok('2027-03-29'));assert.equal(await old,false);
 assert.equal(window.location.searchParams.get('meal_week'),'2027-05-03','An older response must not revert calendar or URL');
 assert.equal(replacements.length,3);assert.equal(window.history.state,historyState);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", script, str(ROOT / "PushShoppingList/static/js/app.js")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for the interaction check")
def test_planner_refresh_preserves_preview_state_and_rejects_stale_responses():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const handler = source.slice(source.indexOf('let mealPlannerRefreshController'), source.indexOf('function openMealPlannerPageAndDialog'));
const status = {hidden: true, textContent: '', classList: {add() {}}};
const details = {dataset: {mealFamilyDetails: 'meal-1'}, open: true};
let dialogOpen = false;
const attrs = new Set();
const page = {
    dataset: {mealWeek: '2026-09-28'}, hidden: true, inert: true, innerHTML: 'original',
    setAttribute: name => attrs.add(name), removeAttribute: name => attrs.delete(name),
    querySelector: selector => selector === 'dialog[open]' ? dialogOpen : status,
    querySelectorAll: () => [details],
};
let responseFactory, calls = [], viewInits = [];
const ctx = {
    AbortController, Set, encodeURIComponent,
    window: {PlannerViews: {init(root) {viewInits.push({root, html:root.innerHTML, hidden:root.hidden, inert:root.inert});}}},
    document: {getElementById: () => page},
    withCanonicalViewerUserId: url => `${url}&viewer_user_id=test-user`,
    initDeferredImages() {},
    DOMParser: class {parseFromString(html) {return {getElementById: () => ({innerHTML: html, dataset: {mealWeek: '2026-10-05'}})}}},
    fetch: async (url, options) => {calls.push({url, options}); return responseFactory()},
};
vm.createContext(ctx);
vm.runInContext(handler, ctx);
const ok = html => ({ok: true, redirected: false, text: async () => html});
(async () => {
    responseFactory = () => ok('fresh');
    assert.equal(await ctx.refreshMealPlannerWorkspace({date: '2026-10-06'}), true);
    assert.equal(calls[0].url, '/?meal_week=2026-10-06&viewer_user_id=test-user');
    assert.equal(page.innerHTML, 'fresh');
    assert.equal(page.hidden, true, 'Refreshing must not reveal the planner underneath the recipe preview');
    assert.equal(page.inert, true);
    assert.equal(details.open, true);
    assert.equal(page.dataset.mealWeek, '2026-10-05');
    assert.equal(page.dataset.mealPlannerStale, undefined);
    assert.equal(attrs.has('aria-busy'), false);
    assert.equal(viewInits.length, 1);
    assert.equal(viewInits[0].root, page, 'Reinitialize views on the retained planner root');
    assert.deepEqual(viewInits[0], {root:page, html:'fresh', hidden:true, inert:true});

    responseFactory = () => ({ok: false});
    assert.equal(await ctx.refreshMealPlannerWorkspace(), false);
    assert.equal(page.innerHTML, 'fresh');
    assert.equal(page.dataset.mealPlannerStale, '1');
    assert.equal(status.hidden, false);
    assert.match(status.textContent, /Unable to refresh/);
    assert.equal(viewInits.length, 1, 'A failed refresh must not reinitialize views from an error response');

    const requestCount = calls.length;
    dialogOpen = true;
    assert.equal(await ctx.refreshMealPlannerWorkspace(), false);
    assert.equal(calls.length, requestCount, 'An open Add Meal form must not lose its inputs');
    dialogOpen = false;

    let releaseOld;
    responseFactory = () => new Promise(resolve => {releaseOld = resolve});
    const oldRequest = ctx.refreshMealPlannerWorkspace();
    const oldSignal = calls.at(-1).options.signal;
    responseFactory = () => ok('newest');
    assert.equal(await ctx.refreshMealPlannerWorkspace(), true);
    assert.equal(oldSignal.aborted, true);
    releaseOld(ok('outdated'));
    assert.equal(await oldRequest, false);
    assert.equal(page.innerHTML, 'newest', 'An older response must not overwrite a newer plan');
    assert.equal(viewInits.length, 2, 'The stale response must not reinitialize or overwrite the selected planner view');
    assert.equal(viewInits[1].root, page);
    assert.deepEqual(viewInits[1], {root:page, html:'newest', hidden:true, inert:true});
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", script, str(ROOT / "PushShoppingList/static/js/app.js")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
