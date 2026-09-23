"""Behavioral contracts for the Choices projection of canonical editor rows."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHOICES_JS = ROOT / "PushShoppingList/static/js/ingredient-choices.js"
APP_JS = ROOT / "PushShoppingList/static/js/app.js"


def app_function(name):
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index(f"function {name}(")
    end = source.find("\nfunction ", start + 1)
    return source[start:end] if end >= 0 else source[start:]


def run_choices_javascript(script, app_functions=()):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Ingredient Choices authoring contract")
    harness = CHOICES_JS.read_text(encoding="utf-8")
    harness += "\n" + "\n".join(app_function(name) for name in app_functions)
    harness += r"""
const written = [];
let dirtyUpdates = 0;
const document = {createElement: () => ({type: 'hidden', dataset: {}, value: ''})};
function makeRow(values, optionRows = []) {
    const row = {
        fields: {}, optionRows,
        appendChild(input) { this.fields[input.dataset.field] = input; },
        querySelector(selector) {
            if (selector === '[data-original-option-id]') return this.fields.original_option_id || null;
            const name = selector.match(/data-field="([^"]+)"/);
            return name ? this.fields[name[1]] || null : null;
        },
    };
    for (const [key, value] of Object.entries(values)) {
        row.fields[key] = {value: String(value ?? ''), type: 'text', dataset: {field: key}};
    }
    row.list = {innerHTML: ''};
    row.container = {
        querySelectorAll: () => optionRows,
        querySelector: () => row.list,
    };
    return row;
}
function recipeIngredientSubstitutionContainer(row) { return row.container; }
function recipeIngredientDirectField(row, field) { return row.fields[field] || null; }
function fieldValuesFromRow(row) {
    return Object.fromEntries(Object.entries(row.fields).map(([key, input]) => [key, input.value]));
}
function recipeIngredientMatchFlag(value) { return ['true', '1', 'yes'].includes(String(value).toLowerCase()); }
function nextRecipeIngredientAlternativeId() { throw new Error('Existing group IDs must remain stable'); }
function recipeIngredientRecipeViewAmount(value) { return [value.quantity, value.unit].filter(Boolean).join(' '); }
function recipeIngredientSubstitutionOptionRowHtml(component) { written.push(component); return '<row>'; }
function bindRecipeIngredientSubstitutionRows() {}
function updateRecipeIngredientSubstitutionState() {}
function updateRecipeIngredientSummary() {}
function updateRecipeIngredientRowIndexes() {}
function updateRecipeEditorDirtyState() { dirtyUpdates += 1; }
"""
    harness += "\n" + script
    result = subprocess.run(
        [node], input=harness, cwd=ROOT, check=True, capture_output=True, text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_explicit_bundle_replaces_source_while_legacy_original_stays_separate():
    result = run_choices_javascript(r"""
const source = {
    ingredient: 'butter', quantity: '1/2', unit: 'cup', preparation: 'melted',
    source_text: '1/2 cup butter (melted)', original_option_id: 'original:butter',
};
const butterEgg = [
    makeRow({ingredient: 'unsalted butter', alternative_id: 'butter-egg', option_type: 'original'}),
    makeRow({ingredient: 'egg', alternative_id: 'butter-egg', option_type: 'original'}),
    makeRow({ingredient: 'butter', alternative_id: 'butter-only', option_type: 'recipe_choice'}),
];
const explicit = makeRow(source, butterEgg);
const legacy = makeRow(source, [
    makeRow({ingredient: 'margarine', alternative_id: 'margarine', option_type: 'substitution'}),
]);
function snapshot(row) {
    return recipeChoiceGroups(row).map(group => ({id: group.id, values: group.values}));
}
process.stdout.write(JSON.stringify({explicit: snapshot(explicit), legacy: snapshot(legacy), label: recipeChoiceLabel(explicit)}));
""", app_functions=("recipeIngredientSubstitutionDomGroups",))

    assert [group["id"] for group in result["explicit"]] == ["butter-egg", "butter-only"]
    assert [item["ingredient"] for item in result["explicit"][0]["values"]] == ["unsalted butter", "egg"]
    assert all("quantity" not in item for group in result["explicit"] for item in group["values"])
    assert result["label"] == "1/2 cup butter (melted)"
    assert [group["id"] for group in result["legacy"]] == ["original:butter", "margarine"]
    assert result["legacy"][0]["values"][0]["quantity"] == "1/2"
    assert "quantity" not in result["legacy"][1]["values"][0]


def test_default_display_does_not_invent_a_selection_for_unresolved_legacy_groups():
    result = run_choices_javascript(r"""
const groups = [
    {id: 'butter-egg', values: [{ingredient: 'unsalted butter'}, {ingredient: 'egg'}]},
    {id: 'butter-only', values: [{ingredient: 'butter'}]},
];
const missing = recipeChoiceDefault(makeRow({}), groups);
const stale = recipeChoiceDefault(makeRow({default_option_id: 'removed-option'}), groups);
const explicit = recipeChoiceDefault(makeRow({default_option_id: 'butter-only'}), groups);
groups[0].values[0].preferred = true;
const legacyFlag = recipeChoiceDefault(makeRow({}), groups);
const explicitOverridesLegacyFlag = recipeChoiceDefault(makeRow({default_option_id: 'butter-only'}), groups);
process.stdout.write(JSON.stringify({missing, stale, explicit, legacyFlag, explicitOverridesLegacyFlag}));
""")

    assert result == {
        "missing": "", "stale": "", "explicit": "butter-only",
        "legacyFlag": "butter-egg", "explicitOverridesLegacyFlag": "butter-only",
    }


def test_option_reordering_preserves_amounts_notes_and_exactly_one_default():
    result = run_choices_javascript(r"""
const source = makeRow({
    ingredient: 'butter', quantity: '1/2', unit: 'cup', preparation: 'melted',
    source_text: '1/2 cup butter (melted)', default_option_id: 'bundle',
});
const groups = [
    {id: 'single', values: [{ingredient: 'butter', quantity: '1/2', unit: 'cup', notes: 'salted is fine'}]},
    {id: 'bundle', values: [
        {ingredient: 'egg', quantity: '', unit: '', preparation: 'beaten', notes: 'room temperature'},
        {ingredient: 'unsalted butter', quantity: '1/4', unit: 'cup'},
    ]},
];
const before = JSON.stringify(groups);
writeRecipeChoiceGroups(source, groups, 'bundle');
process.stdout.write(JSON.stringify({written, source: fieldValuesFromRow(source), unchanged: before === JSON.stringify(groups), dirtyUpdates}));
""")

    rows = result["written"]
    assert [item["ingredient"] for item in rows] == ["butter", "egg", "unsalted butter"]
    assert [item["quantity"] for item in rows] == ["1/2", "", "1/4"]
    assert rows[1]["unit"] == ""
    assert rows[1]["preparation"] == "beaten"
    assert rows[1]["notes"] == "room temperature"
    assert [item["alternative_order"] for item in rows] == [0, 1, 1]
    assert [item["alternative_component_order"] for item in rows] == [0, 0, 1]
    assert {item["alternative_id"] for item in rows if item["is_default"]} == {"bundle"}
    assert [item["option_type"] for item in rows] == ["original", "recipe_choice", "recipe_choice"]
    assert result["source"]["source_text"] == "1/2 cup butter (melted)"
    assert result["source"]["quantity"] == "1/2"
    assert result["source"]["default_option_id"] == "bundle"
    assert result["unchanged"] is True
    assert result["dirtyUpdates"] == 1


def test_component_amount_edits_at_scale_two_save_base_values_and_allow_clearing():
    result = run_choices_javascript(r"""
const component = makeRow({ingredient: 'egg', quantity: '', base_quantity: '', unit: '', base_unit: '', preparation: '', notes: ''});
const source = makeRow({ingredient: 'butter', quantity: '1/2', unit: 'cup'});
recipeChoiceContext = () => ({row: source, groups: [{rows: [component]}], optionIndex: 0, componentIndex: 0});
function currentRecipeEditScaleMultiplier() { return 2; }
function scaleQuantityForDisplay(value, multiplier) { return value ? String(Number(value) * multiplier) : ''; }
function edit(field, value) {
    handleRecipeChoiceInput({target: {dataset: {choiceField: field}, value, hasAttribute: () => false}});
}
edit('quantity', '3');
edit('unit', 'each');
edit('preparation', 'beaten');
edit('notes', 'room temperature');
const materialized = fieldValuesFromRow(component);
const saved = canonicalRecipeIngredientAmountForSave({...materialized});
edit('quantity', '');
edit('unit', '');
const cleared = canonicalRecipeIngredientAmountForSave(fieldValuesFromRow(component));
process.stdout.write(JSON.stringify({materialized, saved, cleared, source: fieldValuesFromRow(source)}));
""", app_functions=("applyRecipeScaleToIngredientRow", "canonicalRecipeIngredientAmountForSave"))

    assert result["materialized"]["quantity"] == "6"
    assert result["saved"]["quantity"] == "3"
    assert result["saved"]["base_quantity"] == "3"
    assert result["saved"]["preparation"] == "beaten"
    assert result["saved"]["notes"] == "room temperature"
    assert result["cleared"]["quantity"] == ""
    assert result["cleared"]["recipe_qty"] == ""
    assert result["cleared"]["unit"] == ""
    assert result["source"]["quantity"] == "1/2"


def test_preparation_edits_round_trip_through_actual_canonical_row_markup():
    # Preparation edits must reach the same canonical control the save
    # serializer reads, without a stale duplicate overriding the new value.
    harness = r"""
function escapeAttribute(value) { return String(value ?? ''); }
function escapeHtml(value) { return String(value ?? ''); }
function recipeIngredientSubstitutionAlternativeId(value) { return value.alternative_id; }
function recipeIngredientImageUrl() { return ''; }
function recipeImageVariantUrl() { return ''; }
function recipeImageVariantSrcSet() { return ''; }
function recipeIngredientSubstitutionMatchQuality() { return {label: '', className: ''}; }
function recipeIngredientMatchSnapshot() { return {}; }
function recipeIngredientSubstitutionRatio() { return ''; }
function recipeIngredientTypeValue() { return 'standard'; }
function ensureRecipeIngredientUnitOption() {}
function recipeEditSvgIcon() { return ''; }
function recipeIngredientBadgesHtml() { return ''; }
function recipeStoreSectionOptions() { return ''; }
function recipeIngredientTypeOptions() { return ''; }
function recipeIngredientInferredValue() { return 'false'; }
function canonicalizeRecipeIngredientUnitControl() { return true; }
"""
    harness += app_function("recipeIngredientSubstitutionOptionRowHtml")
    harness += app_function("fieldValuesFromRow")
    harness += r"""
const html = recipeIngredientSubstitutionOptionRowHtml({
    ingredient: 'egg', alternative_id: 'butter-egg', preparation: 'whole', notes: 'room temperature',
});
const controls = [...html.matchAll(/<input\b([^>]+)>/g)].flatMap(match => {
    const field = match[1].match(/data-field="([^"]+)"/);
    if (!field) return [];
    return [{
        dataset: {field: field[1]}, value: match[1].match(/value="([^"]*)"/)?.[1] || '',
        type: match[1].match(/type="([^"]*)"/)?.[1] || 'text',
    }];
});
const row = {querySelectorAll: () => controls};
controls.forEach(input => { input.closest = () => row; });
recipeIngredientDirectField = (_row, field) => controls.find(input => input.dataset.field === field);
recipeChoiceSetField(row, 'preparation', 'beaten');
recipeChoiceSetField(row, 'notes', 'whisk until smooth');
process.stdout.write(JSON.stringify(fieldValuesFromRow(row)));
"""
    result = run_choices_javascript(harness)

    assert result["preparation"] == "beaten"
    assert result["notes"] == "whisk until smooth"


def test_reopening_explicit_empty_preparation_does_not_copy_notes():
    result = run_choices_javascript(r"""
const rows = recipeIngredientSubstitutionRows({substitutions: [
    {ingredient: 'egg', alternative_id: 'bundle', preparation: '', notes: 'room temperature'},
    {ingredient: 'butter', alternative_id: 'other', preparation: 'melted', notes: ''},
]});
process.stdout.write(JSON.stringify(rows));
""", app_functions=("recipeIngredientSubstitutionRows", "recipeIngredientSubstitutionAlternativeId", "recipeIngredientSubstitutionGroupId"))

    assert result[0]["preparation"] == ""
    assert result[0]["notes"] == "room temperature"
    assert result[1]["preparation"] == "melted"
    assert result[1]["notes"] == ""


def test_scale_changes_refresh_choices_after_standard_and_bundle_amounts_update():
    result = run_choices_javascript(r"""
const standard = makeRow({ingredient: 'flour', quantity: '3', base_quantity: '3', unit: 'cup', base_unit: 'cup'});
const butter = makeRow({ingredient: 'unsalted butter', quantity: '0.25', base_quantity: '0.25', unit: 'cup', base_unit: 'cup'});
const egg = makeRow({ingredient: 'egg', quantity: '', base_quantity: '', unit: '', base_unit: ''});
const source = makeRow({ingredient: 'butter', quantity: '0.5', base_quantity: '0.5', unit: 'cup', base_unit: 'cup', source_text: '1/2 cup butter (melted)'}, [butter, egg]);
const rows = [standard, source];
rows.forEach(row => { row.querySelectorAll = () => row.optionRows; });
const scaleInput = {dataset: {}};
const legacyInput = {value: '1'};
document.getElementById = () => legacyInput;
function recipeEditIngredientRows() { return rows; }
function formatRecipeScaleInputValue(value) { return String(value); }
function scaleQuantityForDisplay(value, multiplier) { return value ? String(Number(value) * multiplier) : ''; }
const renders = [];
renderRecipeIngredientChoicesView = () => {
    renders.push({
        amounts: [standard, source, butter, egg].map(row => row.fields.quantity.value),
        multiplier: scaleInput.dataset.activeMultiplier,
        legacyMultiplier: legacyInput.value,
        sourceLabel: source.fields.source_text.value,
    });
};
applyRecipeScaleValue(scaleInput, 2);
applyRecipeScaleValue(scaleInput, 1);
process.stdout.write(JSON.stringify({renders, egg: fieldValuesFromRow(egg)}));
""", app_functions=("applyRecipeScaleValue", "applyRecipeScaleToIngredientRow"))

    assert result["renders"] == [
        {
            "amounts": ["6", "1", "0.5", ""],
            "multiplier": "2", "legacyMultiplier": "2",
            "sourceLabel": "1/2 cup butter (melted)",
        },
        {
            "amounts": ["3", "0.5", "0.25", ""],
            "multiplier": "1", "legacyMultiplier": "1",
            "sourceLabel": "1/2 cup butter (melted)",
        },
    ]
    assert result["egg"]["quantity"] == ""
    assert result["egg"]["base_quantity"] == ""
    assert result["egg"]["unit"] == ""
