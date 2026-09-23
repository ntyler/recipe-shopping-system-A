"""The compact header reads canonical fields and keeps existing editing actions."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_JS = ROOT / "PushShoppingList/static/js/recipe-edit-summary.js"
APP_JS = ROOT / "PushShoppingList/static/js/app.js"


def app_function(name):
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index(f"function {name}(")
    end = source.find("\nfunction ", start + 1)
    return source[start:end] if end >= 0 else source[start:]


def run_summary_javascript(script, app_functions=()):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the compact recipe summary contract")
    harness = SUMMARY_JS.read_text(encoding="utf-8")
    harness += "\n" + "\n".join(app_function(name) for name in app_functions)
    harness += r"""
const nodes = {};
const categories = {};
const cuisine = [];
const dietary = [];
const custom = [];
let multiplier = 1;
function element() {
    return {
        textContent: '', title: '', dataset: {}, children: [], replaceCount: 0, attributes: {},
        classList: {values: {}, toggle(key, enabled) { this.values[key] = enabled; }},
        replaceChildren(...children) { this.children = children; this.replaceCount++; },
        appendChild(child) { this.children.push(child); },
        setAttribute(name, value) { this.attributes[name] = value; },
        closest(selector) { return selector === '.recipe-edit-summary-metric' ? this.metric || null : null; },
    };
}
const targets = Object.fromEntries(['title', 'description', 'servings', 'scale', 'time', 'difficulty'].map(key => [key, element()]));
for (const key of ['servings', 'scale', 'time', 'difficulty']) targets[key].metric = element();
const tags = element();
const summary = {
    querySelector(selector) {
        if (selector === '[data-summary-tags]') return tags;
        return targets[selector.match(/data-summary-value="([^"]+)"/)?.[1]] || null;
    },
};
nodes.recipeEditCompactSummary = summary;
const document = {getElementById: id => nodes[id] || null, createElement: () => element()};
function collectRecipeEditorCategoryValues() { return {...categories}; }
function recipeEditCuisineTagValues() { return [...cuisine]; }
function recipeEditDietaryPreferenceValues() { return [...dietary]; }
function recipeEditCustomCategoryValues() { return [...custom]; }
function currentRecipeEditScaleMultiplier() { return multiplier; }
function formatRecipeScaleMultiplierLabel(value) { return `${value}x`; }
function setFields(values) { for (const [id, value] of Object.entries(values)) nodes[id] = {value}; }
function projection() {
    return {
        values: Object.fromEntries(Object.entries(targets).map(([key, target]) => [key, {
            text: target.textContent, title: target.title, unspecified: target.classList.values['is-unspecified'],
        }])),
        tags: tags.children.map(chip => ({text: chip.textContent, title: chip.title})),
        accessibleMetrics: Object.fromEntries(Object.entries(targets).filter(([, target]) => target.metric).map(([key, target]) => [key, target.metric.attributes['aria-label']])),
        accessibleTags: tags.attributes['aria-label'],
    };
}
"""
    result = subprocess.run(
        [node], input=harness + "\n" + script, cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_summary_reads_current_canonical_values_and_deduplicates_real_tags():
    result = run_summary_javascript(r"""
setFields({
    recipeEditDisplayName: '  Family Corn Bread  ', recipeEditDescription: ' A saved family recipe. ',
    recipeEditServings: '8 servings', recipeEditTotalTime: '50 min', recipeEditLevel: 'medium',
});
Object.assign(categories, {meal_type: 'Side Dish', main_ingredient: 'Corn', cooking_method: 'Baked', occasion: 'Dinner'});
cuisine.push('American', 'american');
dietary.push('Vegetarian', 'SIDE DISH');
custom.push('Family favorite', 'Corn');
multiplier = 2;
const before = JSON.stringify({nodes: Object.fromEntries(Object.entries(nodes).filter(([, value]) => 'value' in value)), categories, cuisine, dietary, custom});
const values = recipeEditCompactSummaryValues();
const after = JSON.stringify({nodes: Object.fromEntries(Object.entries(nodes).filter(([, value]) => 'value' in value)), categories, cuisine, dietary, custom});
process.stdout.write(JSON.stringify({values, unchanged: before === after}));
""")

    assert result["values"] == {
        "title": "Family Corn Bread", "description": "A saved family recipe.",
        "servings": "8", "scale": "2x", "time": "50 min", "difficulty": "medium",
        "tags": ["Side Dish", "American", "Vegetarian", "Corn", "Baked", "Dinner", "Family favorite"],
    }
    assert result["unchanged"] is True


def test_missing_metadata_remains_unspecified_without_writing_recipe_fields():
    result = run_summary_javascript(r"""
setFields({recipeEditDisplayName: '', recipeEditDescription: '', recipeEditServings: '', recipeEditTotalTime: '', recipeEditLevel: ''});
const before = Object.fromEntries(Object.entries(nodes).filter(([, value]) => 'value' in value).map(([id, input]) => [id, input.value]));
const values = recipeEditCompactSummaryValues();
syncRecipeEditCompactSummary();
const after = Object.fromEntries(Object.entries(nodes).filter(([, value]) => 'value' in value).map(([id, input]) => [id, input.value]));
process.stdout.write(JSON.stringify({values, rendered: projection(), unchanged: JSON.stringify(before) === JSON.stringify(after)}));
""")

    assert result["values"] == {
        "title": "", "description": "", "servings": "", "scale": "1x",
        "time": "", "difficulty": "", "tags": [],
    }
    projected = result["rendered"]["values"]
    assert projected["title"]["text"] == "Untitled recipe"
    assert projected["description"]["text"] == "Add a description"
    assert projected["time"] == {"text": "Not set", "title": "Not set", "unspecified": True}
    assert projected["servings"]["unspecified"] is True
    assert projected["difficulty"]["unspecified"] is True
    assert result["rendered"]["tags"] == []
    assert result["rendered"]["accessibleMetrics"]["time"] == "Total time: Not set. Edit total time."
    assert result["rendered"]["accessibleTags"] == "Edit recipe tags"
    assert result["unchanged"] is True


def test_summary_refreshes_after_edits_without_replacing_unchanged_tag_chips():
    result = run_summary_javascript(r"""
setFields({recipeEditDisplayName: 'Before', recipeEditDescription: '<b>Recipe note</b>', recipeEditServings: '8 to 10 servings', recipeEditTotalTime: '50 min', recipeEditLevel: 'easy'});
cuisine.push('American', 'Southern');
dietary.push('Vegetarian');
custom.push('Family', 'Weeknight');
syncRecipeEditCompactSummary();
const first = projection();
const firstChips = [...tags.children];
nodes.recipeEditDisplayName.value = 'After';
nodes.recipeEditTotalTime.value = '1 hr';
nodes.recipeEditLevel.value = '';
syncRecipeEditCompactSummary();
const second = projection();
const sameChips = firstChips.every((chip, index) => chip === tags.children[index]);
custom.splice(0);
syncRecipeEditCompactSummary();
process.stdout.write(JSON.stringify({first, second, sameChips, final: projection(), replaceCount: tags.replaceCount}));
""")

    assert result["first"]["values"]["servings"]["text"] == "8 to 10"
    assert result["first"]["values"]["description"]["text"] == "<b>Recipe note</b>"
    assert [chip["text"] for chip in result["first"]["tags"]] == [
        "American", "Southern", "Vegetarian", "Family", "+1",
    ]
    assert result["first"]["tags"][-1]["title"] == "Weeknight"
    assert result["first"]["accessibleTags"] == "Edit recipe tags: American, Southern, Vegetarian, Family, Weeknight"
    assert result["first"]["accessibleMetrics"]["servings"] == "Servings: 8 to 10. Edit servings."
    assert result["second"]["values"]["title"]["text"] == "After"
    assert result["second"]["values"]["time"]["text"] == "1 hr"
    assert result["second"]["values"]["difficulty"]["unspecified"] is True
    assert result["second"]["accessibleMetrics"]["time"] == "Total time: 1 hr. Edit total time."
    assert result["second"]["accessibleMetrics"]["difficulty"] == "Difficulty: Not set. Edit difficulty."
    assert result["sameChips"] is True
    assert result["replaceCount"] == 2
    assert [chip["text"] for chip in result["final"]["tags"]] == ["American", "Southern", "Vegetarian"]
    assert result["final"]["accessibleTags"] == "Edit recipe tags: American, Southern, Vegetarian"


def test_summary_note_and_field_actions_use_existing_editor_controls():
    result = run_summary_javascript(r"""
const actions = [];
function setRecipeEditActiveTab(tab) { actions.push(['tab', tab]); }
function openRecipeEditCoverDialog() { actions.push(['cover-dialog']); }
function addRecipeReflectionNoteRow() {
    actions.push(['add-reflection-note']);
    return {querySelector(selector) {
        if (selector !== '[data-field="text"]') throw new Error('Wrong canonical note control');
        return {focus() { actions.push(['focus-note']); }};
    }};
}
nodes.recipeEditTotalTime = {
    focus(options) { actions.push(['focus-time', options]); },
    scrollIntoView(options) { actions.push(['scroll-time', options]); },
};
addRecipeEditSummaryNote();
openRecipeEditSummaryField('recipeinformation', 'recipeEditTotalTime');
openRecipeEditSummaryField('recipeimage', undefined);
process.stdout.write(JSON.stringify(actions));
""")

    assert result == [
        ["tab", "notes"], ["add-reflection-note"], ["focus-note"],
        ["tab", "recipeinformation"], ["focus-time", {"preventScroll": True}],
        ["scroll-time", {"block": "nearest", "behavior": "smooth"}],
        ["cover-dialog"],
    ]


def test_existing_context_and_dirty_state_hooks_refresh_the_summary():
    result = run_summary_javascript(r"""
setFields({recipeEditDisplayName: 'Loaded', recipeEditDescription: '', recipeEditServings: '4', recipeEditTotalTime: '20 min', recipeEditLevel: 'easy'});
function syncRecipeEditDocumentRows() {}
function updateRecipeEditRestaurantCard() {}
function updateRecipeEditIngredientGallery() {}
function updateRecipeEditorHealth() {}
function updateRecipeEditMetadataUnits() {}
function recipeEditFieldContainer() { return null; }
const form = {dataset: {}, querySelectorAll: () => []};
nodes.recipeEditForm = form;
const recipeEditSavedFormSnapshots = new WeakMap([[form, 'saved']]);
function recipeEditorCurrentSaveSnapshot() { return 'changed'; }
updateRecipeEditContextPanels();
const initial = projection();
nodes.recipeEditDisplayName.value = 'Programmatically changed';
nodes.recipeEditTotalTime.value = '35 min';
const dirty = updateRecipeEditorDirtyState(form);
process.stdout.write(JSON.stringify({initial, current: projection(), dirty, dirtyState: form.dataset.recipeEditDirty}));
""", app_functions=("updateRecipeEditContextPanels", "updateRecipeEditorDirtyState"))

    assert result["initial"]["values"]["title"]["text"] == "Loaded"
    assert result["current"]["values"]["title"]["text"] == "Programmatically changed"
    assert result["current"]["values"]["time"]["text"] == "35 min"
    assert result["dirty"] is True
    assert result["dirtyState"] == "true"


def test_population_refreshes_summary_after_calculating_a_missing_total_time():
    population = app_function("populateRecipeEditor")
    start = population.index("    initializeRecipeEditTotalTimeCalculation();")
    end = population.index("    if (preserveSavedState)", start)
    metadata_initialization = population[start:end]
    script = r"""
setFields({recipeEditDisplayName: 'Recipe with calculated time', recipeEditTotalTime: ''});
nodes.recipeEditForm = {};
const recipeEditTotalTimeCalculationStates = new WeakMap();
function calculateRecipeEditTimeBreakdownMinutes() { return 45; }
function parseRecipeEditDurationMinutes(value) { return value ? parseFloat(value) : null; }
function formatRecipeEditDurationMinutes(value) { return `${value} min`; }
function recipeEditDurationMinutesMatch(left, right) { return left !== null && left === right; }
function syncRecipeEditTotalTimeStatus() {}
function updateRecipeEditStickyOffsets() {}
"""
    script += "\nfunction finishPopulationMetadata() {\n" + metadata_initialization + "\n}\n"
    script += r"""
finishPopulationMetadata();
const calculated = projection();
nodes.recipeEditDisplayName.value = 'Next recipe with a manual total';
nodes.recipeEditTotalTime.value = '60 min';
finishPopulationMetadata();
process.stdout.write(JSON.stringify({calculated, next: projection(), stored: nodes.recipeEditTotalTime.value}));
"""
    result = run_summary_javascript(script, app_functions=("initializeRecipeEditTotalTimeCalculation",))

    assert result["calculated"]["values"]["time"]["text"] == "45 min"
    assert result["calculated"]["accessibleMetrics"]["time"] == "Total time: 45 min. Edit total time."
    assert result["next"]["values"]["title"]["text"] == "Next recipe with a manual total"
    assert result["next"]["values"]["time"]["text"] == "60 min"
    assert result["stored"] == "60 min"
