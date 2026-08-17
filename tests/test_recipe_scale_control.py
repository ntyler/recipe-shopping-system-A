import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html"
SCRIPT_PATH = ROOT / "PushShoppingList/static/js/app.js"
CSS_PATH = ROOT / "PushShoppingList/static/css/app.css"


def run_node(source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the recipe scale control regression")
    completed = subprocess.run(
        [node],
        input=source,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def scale_control_script(script):
    return script[
        script.index("function populateRecipeScalingControls"):
        script.index("function firstRecipeEditorFoodReviewMarker")
    ]


def test_recipe_scale_is_an_accessible_four_option_segmented_control():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    field_start = template.index('class="recipe-edit-scale-field')
    field_end = template.index('id="recipeEditScaleError"', field_start)
    field = template[field_start:field_end]

    assert '<input type="hidden"' in field
    assert 'id="recipeEditScaleMultiplier"' in field
    assert 'name="scaling_multiplier"' in field
    assert 'data-recipe-edit-scale-segments' in field
    assert 'role="group"' in field
    assert 'aria-label="Recipe scale"' in field
    assert field.count('data-recipe-edit-scale-preset=') == 4
    assert 'data-recipe-edit-scale-preset="0.5"' in field
    assert 'data-recipe-edit-scale-preset="1"' in field
    assert 'data-recipe-edit-scale-preset="2"' in field
    assert 'data-recipe-edit-scale-preset="3"' in field
    assert '&frac12;&times;' in field
    assert 'aria-label="Scale recipe to 0.5 times"' in field
    assert 'aria-label="Scale recipe to 1 time"' in field
    assert 'aria-label="Scale recipe to 2 times"' in field
    assert 'aria-label="Scale recipe to 3 times"' in field
    assert 'onclick="return selectRecipeEditScalePreset' in field
    assert "RECIPE_EDIT_SCALE_PRESETS" not in script
    assert "RECIPE_EDIT_CUSTOM_SCALE_VALUE" not in script
    assert "organizeRecipeEditScaleControl(scaleField)" in script
    assert "function selectRecipeEditScalePreset" in script
    assert "function syncRecipeEditScaleSegments" in script
    assert ".recipe-edit-scale-segments" in css
    assert "button.is-selected" in css
    assert ".recipe-edit-scale-error" in css
    assert "var(--app-primary-hover)" in css


def test_recipe_servings_and_scale_share_a_quiet_equal_height_control_family():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    styles_start = css.index(
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized\n"
        "    .recipe-edit-details-primary-grid\n"
        "    :is(.recipe-edit-servings-stepper, .recipe-edit-scale-segments) {"
    )
    styles = css[styles_start:css.index("body.recipe-edit-standalone-page .recipe-edit-scale-current", styles_start)]

    assert 'aria-label="Decrease servings"' in template
    assert 'aria-label="Increase servings"' in template
    assert '<span class="recipe-edit-servings-value">' in template
    assert '<span class="recipe-edit-servings-unit" aria-hidden="true">servings</span>' in template
    assert "height: 42px;" in styles
    assert "border: 1px solid var(--app-border);" in styles
    assert "grid-template-columns: 40px minmax(0, 1fr) 40px;" in styles
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in styles
    assert "button:hover:not(.is-selected)" in styles
    assert "button.is-selected" in styles
    assert "background: color-mix(in srgb, var(--app-primary-soft) 72%, transparent);" in styles
    assert "box-shadow: inset 0 0 0 1px" not in styles
    assert "border-right:" not in styles


def test_recipe_scale_parser_accepts_decimals_fractions_and_mixed_fractions():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    parser = script[
        script.index("function parseRecipeScaleMultiplier"):
        script.index("function formatRecipeScaleInputValue")
    ]
    values = [
        "0.5",
        "1/2",
        "3/4",
        "1.5",
        "1 1/2",
        "2",
        "  1 / 2  ",
        ".25",
    ]
    result = run_node(
        parser
        + f"\nconst values = {json.dumps(values)};"
        + "\nprocess.stdout.write(JSON.stringify(values.map(value => validateRecipeEditScaleMultiplier(value))));"
    )

    assert result == [0.5, 0.5, 0.75, 1.5, 1.5, 2, 0.5, 0.25]


def test_recipe_scale_parser_rejects_invalid_entries():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    parser = script[
        script.index("function parseRecipeScaleMultiplier"):
        script.index("function formatRecipeScaleInputValue")
    ]
    values = [
        "",
        "   ",
        "0",
        "0.0",
        "-1",
        "-1/2",
        "1/0",
        "1 1/0",
        "1//2",
        "1/2/3",
        "1  /",
        "one",
        "1x",
        "NaN",
        "Infinity",
    ]
    result = run_node(
        parser
        + f"\nconst values = {json.dumps(values)};"
        + "\nprocess.stdout.write(JSON.stringify(values.map(value => validateRecipeEditScaleMultiplier(value))));"
    )

    assert result == [None] * len(values)


def test_recipe_scale_keeps_servings_canonical_and_updates_one_shopping_multiplier():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    control = scale_control_script(script)
    calculations = script[
        script.index("function scaleServingsForDisplay"):
        script.index("function cssEscape")
    ]
    harness = r"""
const RECIPE_EDIT_SCALE_ERROR_MESSAGE = "Scale must be a positive number, decimal, or fraction.";
const fieldClasses = new Set();
const field = {
    classList: {
        remove(name) { fieldClasses.delete(name); },
    },
};
const scaleInput = {
    value: "",
    dataset: {},
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = String(value); },
    removeAttribute(name) { delete this.attributes[name]; delete this.dataset[name]; },
    closest(selector) { return selector === "label" ? field : null; },
};
const scaleError = { hidden: true, textContent: "" };
const servingsInput = { value: "4", dataset: {} };
const legacyQuantityInput = { value: "1" };
const quantityInput = { value: "1/2" };
const baseQuantityInput = { value: "1/2" };
const unitInput = { value: "cup" };
const baseUnitInput = { value: "cup" };
const ingredientRow = {
    querySelector(selector) {
        return {
            '[data-field="quantity"]': quantityInput,
            '[data-field="base_quantity"]': baseQuantityInput,
            '[data-field="unit"]': unitInput,
            '[data-field="base_unit"]': baseUnitInput,
        }[selector] || null;
    },
    querySelectorAll() { return []; },
};
const elements = {
    recipeEditScaleMultiplier: scaleInput,
    recipeEditScaleError: scaleError,
    recipeEditServings: servingsInput,
    recipeEditQuantity: legacyQuantityInput,
};
const document = {
    getElementById(id) { return elements[id] || null; },
};
function recipeMultipliersMatch(left, right) {
    return Math.abs(Number(left) - Number(right)) < 0.000001;
}
function recipeEditIngredientRows() { return [ingredientRow]; }
let recipeEditScalingOptions = [];
""" + control + calculations + r"""

function snapshot() {
    return {
        text: scaleInput.value,
        active: scaleInput.dataset.activeMultiplier,
        servings: servingsInput.value,
        quantity: quantityInput.value,
        shoppingMultiplier: legacyQuantityInput.value,
        errorVisible: !scaleError.hidden,
        payload: collectRecipeScalingPayload(),
    };
}

populateRecipeScalingControls({ selected_multiplier: 1, base_servings: "4" }, "4");
const initial = snapshot();

scaleInput.value = "1/2";
applyRecipeScaleMultiplier(scaleInput);
const fraction = snapshot();

scaleInput.value = "1 1/2";
applyRecipeScaleMultiplier(scaleInput);
const mixed = snapshot();

scaleInput.value = "1//2";
applyRecipeScaleMultiplier(scaleInput);
const invalidDraft = snapshot();

process.stdout.write(JSON.stringify({ initial, fraction, mixed, invalidDraft }));
"""
    result = run_node(harness)

    assert result["initial"]["text"] == "1"
    assert result["fraction"]["text"] == "1/2"
    assert result["fraction"]["active"] == "0.5"
    assert result["fraction"]["servings"] == "4"
    assert result["fraction"]["quantity"] == "1/4"
    assert result["fraction"]["shoppingMultiplier"] == "0.5"
    assert result["fraction"]["payload"]["selected_multiplier"] == 1
    assert result["fraction"]["payload"]["base_servings"] == "4"

    assert result["mixed"]["text"] == "1 1/2"
    assert result["mixed"]["active"] == "1.5"
    assert result["mixed"]["servings"] == "4"
    assert result["mixed"]["quantity"] == "3/4"
    assert result["mixed"]["shoppingMultiplier"] == "1.5"
    assert result["mixed"]["payload"]["selected_multiplier"] == 1

    assert result["invalidDraft"]["text"] == "1//2"
    assert result["invalidDraft"]["active"] == "1.5"
    assert result["invalidDraft"]["servings"] == "4"
    assert result["invalidDraft"]["quantity"] == "3/4"
    assert result["invalidDraft"]["shoppingMultiplier"] == "1.5"
    assert result["invalidDraft"]["errorVisible"] is False
    assert result["invalidDraft"]["payload"]["selected_multiplier"] == 1


def test_recipe_scale_validation_runs_only_on_save_and_keeps_invalid_text():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    control = scale_control_script(script)
    validation_helper = script[
        script.index("function validateRecipeEditScaleField"):
        script.index("function validateRecipeEditor")
    ]
    validator = script[
        script.index("function validateRecipeEditor(form, payload)"):
        script.index("function applyRecipeEditorServerFieldErrors")
    ]
    reveal = script[
        script.index("function showRecipeEditorValidationErrors"):
        script.index("function validateRecipeEditScaleField")
    ]
    harness = r"""
const RECIPE_EDIT_SCALE_ERROR_MESSAGE = "Scale must be a positive number, decimal, or fraction.";
const field = { classList: { remove() {} } };
const scaleInput = {
    value: "1//2",
    dataset: {},
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = String(value); },
    removeAttribute(name) { delete this.attributes[name]; },
    closest(selector) { return selector === "label" ? field : null; },
};
const scaleError = { hidden: true, textContent: "" };
const document = {
    getElementById(id) {
        return { recipeEditScaleMultiplier: scaleInput, recipeEditScaleError: scaleError }[id] || null;
    },
};
function addRecipeEditorValidationError(errors, message, control, fieldName) {
    control.setAttribute("aria-invalid", "true");
    control.dataset.recipeEditValidationInvalid = "true";
    errors.push({ message, control, field: fieldName });
}
function recipeMultipliersMatch(left, right) { return Number(left) === Number(right); }
function recipeEditIngredientRows() { return []; }
let recipeEditScalingOptions = [];
""" + control + validation_helper + r"""
const errors = [];
const valid = validateRecipeEditScaleField(errors);
process.stdout.write(JSON.stringify({
    valid,
    value: scaleInput.value,
    errorCount: errors.length,
    message: scaleError.textContent,
    errorVisible: !scaleError.hidden,
    invalid: scaleInput.attributes["aria-invalid"],
    field: errors[0] && errors[0].field,
}));
"""
    result = run_node(harness)

    assert result == {
        "valid": False,
        "value": "1//2",
        "errorCount": 1,
        "message": "Scale must be a positive number, decimal, or fraction.",
        "errorVisible": True,
        "invalid": "true",
        "field": "scaling.selected_multiplier",
    }
    assert validator.index("validateRecipeEditScaleField(errors)") < validator.index(
        'document.getElementById("recipeEditTitleInput")'
    )
    assert "showRecipeEditorValidationErrors(errors)" in validator
    assert 'firstControl.focus({ preventScroll: true })' in reveal
    assert "validateRecipeEditScaleField" not in control
    assert "setRecipeScaleValidationMessage(\"\")" in control


def test_scaled_ingredient_edit_is_converted_back_to_a_canonical_base_amount():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    base_tracking = script[
        script.index("function updateRecipeIngredientBaseFromManualEdit"):
        script.index("function bindRecipeIngredientFoodRuleWarning")
    ]
    parser = script[
        script.index("function parseRecipeScaleMultiplier"):
        script.index("function formatRecipeScaleMultiplierLabel")
    ]
    calculations = script[
        script.index("function scaleServingsForDisplay"):
        script.index("function cssEscape")
    ]
    canonicalizer = script[
        script.index("function canonicalRecipeIngredientAmountForSave"):
        script.index("function collectRecipeNutritionRows")
    ]
    harness = r"""
const scaleInput = { value: "2", dataset: { activeMultiplier: "2" } };
const quantityInput = { value: "3" };
const baseQuantityInput = { value: "1" };
const unitInput = { value: "cups" };
const baseUnitInput = { value: "cup" };
const recipeQtyInput = { value: "1" };
const row = {
    querySelector(selector) {
        return {
            '[data-field="quantity"]': quantityInput,
            '[data-field="base_quantity"]': baseQuantityInput,
            '[data-field="unit"]': unitInput,
            '[data-field="base_unit"]': baseUnitInput,
            '[data-field="recipe_qty"]': recipeQtyInput,
        }[selector] || null;
    },
};
const document = {
    getElementById(id) { return id === "recipeEditScaleMultiplier" ? scaleInput : null; },
};
""" + parser + base_tracking + calculations + canonicalizer + r"""
updateRecipeIngredientBaseFromManualEdit(row);
const saved = canonicalRecipeIngredientAmountForSave({
    quantity: quantityInput.value,
    unit: unitInput.value,
    base_quantity: baseQuantityInput.value,
    base_unit: baseUnitInput.value,
});
process.stdout.write(JSON.stringify({
    baseQuantity: baseQuantityInput.value,
    baseUnit: baseUnitInput.value,
    recipeQty: recipeQtyInput.value,
    saved,
}));
"""

    result = run_node(harness)

    assert result["baseQuantity"] == "1 1/2"
    assert result["baseUnit"] == "cups"
    assert result["recipeQty"] == "1 1/2"
    assert result["saved"]["quantity"] == "1 1/2"
    assert result["saved"]["base_quantity"] == "1 1/2"
