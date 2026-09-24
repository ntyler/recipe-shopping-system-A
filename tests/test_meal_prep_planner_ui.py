"""Weekly planner rendering and prep-task completion behavior."""

from pathlib import Path
import shutil
import subprocess

from jinja2 import Environment
import pytest


ROOT = Path(__file__).resolve().parents[1]


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
    assert 'checked' in monday
    assert 'Chop &lt;onions&gt;' in monday
    assert 'data-recipe-url="recipe://bread"' in monday
    assert 'No prep steps for Tue 9/29' in html
    assert html.index('>Prep</div>') < html.index('>Dinner</div>')
    assert '2.5 servings' in html
    assert 'From prep batch' in html

    # Legacy contexts without batches still render the ordinary meal grid.
    context.pop("prep_steps_by_day")
    meal.pop("batch_id")
    meal["planned_servings"] = 1
    legacy_html = template.render(meal_plan=context, meal_plan_recipe_options=[meal])
    assert '1 serving' in legacy_html
    assert 'From prep batch' not in legacy_html


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
