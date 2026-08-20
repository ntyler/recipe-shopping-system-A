import json
from pathlib import Path
import re
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


def test_recipe_scale_is_an_accessible_free_entry_decimal_control():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    field_start = template.index('class="recipe-edit-scale-field')
    field_end = template.index('id="recipeEditScaleError"', field_start)
    field = template[field_start:field_end]

    assert 'class="recipe-edit-scale-control recipe-edit-metadata-value"' in field
    assert '<input type="text"' in field
    assert 'id="recipeEditScaleMultiplier"' in field
    assert 'name="scaling_multiplier"' in field
    assert 'value="1"' in field
    assert 'inputmode="decimal"' in field
    assert 'autocomplete="off"' in field
    assert 'spellcheck="false"' in field
    assert 'aria-label="Scale multiplier"' in field
    assert 'aria-describedby="recipeEditScaleError"' in field
    assert 'oninput="return applyRecipeScaleMultiplier(this)"' in field
    assert 'onblur="return commitRecipeEditScaleMultiplier(this)"' in field
    assert 'onkeydown="return handleRecipeEditScaleKeydown(event, this)"' in field
    assert "recipe-edit-scale-suffix" not in field
    assert "&times;" not in field
    assert '<input type="hidden"' not in field
    assert 'data-recipe-edit-scale-preset' not in template
    assert 'data-recipe-edit-scale-segments' not in template
    assert "function selectRecipeEditScalePreset" not in script
    assert "function syncRecipeEditScaleSegments" not in script
    assert "organizeRecipeEditScaleControl" not in script
    assert ".recipe-edit-scale-segments" not in css
    assert ".recipe-edit-scale-control" in css
    assert ".recipe-edit-scale-suffix" not in css
    assert ".recipe-edit-scale-error" in css


def test_recipe_servings_and_scale_share_a_quiet_equal_height_control_family():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    styles_start = css.index(
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized\n"
        "    .recipe-edit-details-primary-grid\n"
        "    :is(.recipe-edit-servings-stepper, .recipe-edit-scale-control) {"
    )
    styles = css[
        styles_start:css.index(
            "body.recipe-edit-standalone-page .recipe-edit-ai-assistant-summary:focus-visible",
            styles_start,
        )
    ]

    assert 'aria-label="Decrease servings"' in template
    assert 'aria-label="Increase servings"' in template
    assert 'onclick="return stepRecipeEditServings(-1)"' in template
    assert 'onclick="return stepRecipeEditServings(1)"' in template
    assert '&minus;' in template
    assert '&plus;' in template
    assert 'id="recipeEditServingsCount"' in template
    assert 'min="1"' in template
    assert 'step="1"' in template
    assert 'inputmode="numeric"' in template
    assert 'oninput="return updateRecipeEditServingsFromStepper(this)"' in template
    assert '<span class="recipe-edit-servings-value">' in template
    assert '<span class="recipe-edit-servings-unit" aria-hidden="true">servings</span>' in template
    assert "height: 42px;" in styles
    assert "border: 1px solid transparent;" in styles
    assert "border-color: var(--app-primary-hover);" in styles
    stepper_rule = re.search(
        r"\.recipe-edit-servings-stepper\s*\{(?P<body>.*?)\}",
        styles,
        re.DOTALL,
    )
    assert stepper_rule
    stepper_body = stepper_rule.group("body")
    assert "display: inline-flex;" in stepper_body
    assert "width: fit-content;" in stepper_body
    assert "max-width: 100%;" in stepper_body
    assert "justify-self: start;" in stepper_body
    gap = re.search(r"gap:\s*(\d+)px;", stepper_body)
    assert gap and 8 <= int(gap.group(1)) <= 12
    assert "grid-template-columns:" not in stepper_body
    scale_rule = re.search(
        r"\.recipe-edit-scale-control\s*\{(?P<body>.*?)\}",
        styles,
        re.DOTALL,
    )
    assert scale_rule
    scale_body = scale_rule.group("body")
    assert "width: fit-content;" in scale_body
    assert "min-width: 42px;" in scale_body
    assert "max-width: 96px;" in scale_body
    assert "justify-self: start;" in scale_body
    button_rule = re.search(
        r"\.recipe-edit-servings-stepper\s*>\s*button\s*\{(?P<body>.*?)\}",
        styles,
        re.DOTALL,
    )
    assert button_rule
    button_body = button_rule.group("body")
    button_width = re.search(r"width:\s*(3[2-6])px;", button_body)
    button_height = re.search(r"height:\s*(3[2-6])px;", button_body)
    assert button_width and button_height
    assert button_width.group(1) == button_height.group(1)
    assert f"flex: 0 0 {button_width.group(1)}px;" in button_body
    assert "display: inline-flex;" in button_body
    assert "align-items: center;" in button_body
    assert "justify-content: center;" in button_body
    assert "margin: 0;" in button_body
    assert "padding: 0;" in button_body
    assert "background: transparent;" in button_body
    value_rule = re.search(
        r"\.recipe-edit-servings-value\s*\{(?P<body>.*?)\}",
        styles,
        re.DOTALL,
    )
    assert value_rule
    assert "flex: 0 1 auto;" in value_rule.group("body")
    assert "white-space: nowrap;" in value_rule.group("body")
    count_rule = re.search(
        r"\.recipe-edit-servings-stepper\s+#recipeEditServingsCount\s*\{(?P<body>.*?)\}",
        styles,
        re.DOTALL,
    )
    assert count_rule
    assert "field-sizing: content;" in count_rule.group("body")
    assert "width: auto;" in count_rule.group("body")
    assert "min-width: 1ch;" in count_rule.group("body")
    assert "max-width: 8ch;" in count_rule.group("body")
    assert "flex: 0 1 auto;" in count_rule.group("body")
    scale_input_rule = re.search(
        r"\.recipe-edit-scale-control\s+#recipeEditScaleMultiplier\s*\{(?P<body>.*?)\}",
        styles,
        re.DOTALL,
    )
    assert scale_input_rule
    assert "field-sizing: content;" in scale_input_rule.group("body")
    assert "width: auto;" in scale_input_rule.group("body")
    assert "min-width: 40px;" in scale_input_rule.group("body")
    assert "max-width: 94px;" in scale_input_rule.group("body")
    assert "box-sizing: border-box;" in scale_input_rule.group("body")
    assert "padding: 0 10px;" in scale_input_rule.group("body")
    assert ":is(.recipe-edit-servings-stepper, .recipe-edit-scale-control):focus-within" in styles
    assert ".recipe-edit-scale-control #recipeEditScaleMultiplier" in styles
    assert "white-space: nowrap;" in styles
    assert "box-shadow: inset 0 0 0 1px" not in styles
    assert "border-right:" not in styles


def test_recipe_scale_parser_accepts_required_decimal_matrix_and_existing_fractions():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    parser = script[
        script.index("function parseRecipeScaleMultiplier"):
        script.index("function formatRecipeScaleInputValue")
    ]
    values = [
        "0.25",
        "0.5",
        "0.75",
        "1",
        "1.25",
        "1.5",
        "2",
        "2.5",
        "3",
        "10",
        "1/2",
        "3/4",
        "1 1/2",
        "  1 / 2  ",
        ".25",
    ]
    result = run_node(
        parser
        + f"\nconst values = {json.dumps(values)};"
        + "\nprocess.stdout.write(JSON.stringify(values.map(value => validateRecipeEditScaleMultiplier(value))));"
    )

    assert result == [
        0.25,
        0.5,
        0.75,
        1,
        1.25,
        1.5,
        2,
        2.5,
        3,
        10,
        0.5,
        0.75,
        1.5,
        0.5,
        0.25,
    ]


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
        ".",
        "1.",
        "1..2",
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


def test_recipe_scale_decimal_matrix_is_canonical_and_never_compounds():
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
        add(name) { fieldClasses.add(name); },
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
    dispatchEvent() { return true; },
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
        invalid: scaleInput.attributes["aria-invalid"] || null,
        payload: collectRecipeScalingPayload(),
    };
}

populateRecipeScalingControls({ selected_multiplier: 1, base_servings: "4" }, "4");
const initial = snapshot();
const values = ["0.25", "0.5", "0.75", "1", "1.25", "1.5", "2", "2.5", "3", "10"];
const scaled = values.map(value => {
    scaleInput.value = value;
    applyRecipeScaleMultiplier(scaleInput);
    return snapshot();
});

scaleInput.value = ".";
applyRecipeScaleMultiplier(scaleInput);
const invalidDraft = snapshot();

process.stdout.write(JSON.stringify({ initial, scaled, invalidDraft }));
"""
    result = run_node(harness)

    assert result["initial"]["text"] == "1"
    assert [snapshot["text"] for snapshot in result["scaled"]] == [
        "0.25",
        "0.5",
        "0.75",
        "1",
        "1.25",
        "1.5",
        "2",
        "2.5",
        "3",
        "10",
    ]
    assert [snapshot["active"] for snapshot in result["scaled"]] == [
        "0.25",
        "0.5",
        "0.75",
        "1",
        "1.25",
        "1.5",
        "2",
        "2.5",
        "3",
        "10",
    ]
    assert [snapshot["quantity"] for snapshot in result["scaled"]] == [
        "1/8",
        "1/4",
        "3/8",
        "1/2",
        "5/8",
        "3/4",
        "1",
        "1 1/4",
        "1 1/2",
        "5",
    ]
    assert [snapshot["shoppingMultiplier"] for snapshot in result["scaled"]] == [
        "0.25",
        "0.5",
        "0.75",
        "1",
        "1.25",
        "1.5",
        "2",
        "2.5",
        "3",
        "10",
    ]
    assert all(snapshot["servings"] == "4" for snapshot in result["scaled"])
    assert all(
        snapshot["payload"]["selected_multiplier"] == 1
        for snapshot in result["scaled"]
    )
    assert all(
        snapshot["payload"]["base_servings"] == "4"
        for snapshot in result["scaled"]
    )

    assert result["invalidDraft"]["text"] == "."
    assert result["invalidDraft"]["active"] == "10"
    assert result["invalidDraft"]["servings"] == "4"
    assert result["invalidDraft"]["quantity"] == "5"
    assert result["invalidDraft"]["shoppingMultiplier"] == "10"
    assert result["invalidDraft"]["errorVisible"] is False
    assert result["invalidDraft"]["invalid"] is None
    assert result["invalidDraft"]["payload"]["selected_multiplier"] == 1


def test_recipe_scale_invalid_commit_rolls_back_and_enter_commits_valid_value():
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
        add(name) { fieldClasses.add(name); },
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
    focus() {},
    select() {},
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
        quantity: quantityInput.value,
        shoppingMultiplier: legacyQuantityInput.value,
        errorVisible: !scaleError.hidden,
        message: scaleError.textContent,
        invalid: scaleInput.attributes["aria-invalid"] || null,
    };
}

populateRecipeScalingControls({ selected_multiplier: 1, base_servings: "4" }, "4");
scaleInput.value = "1.25";
applyRecipeScaleMultiplier(scaleInput);
commitRecipeEditScaleMultiplier(scaleInput);
const lastValid = snapshot();

const invalidValues = ["", "0", "-1", "letters", "1..2"];
const invalidResults = invalidValues.map(value => {
    scaleInput.value = value;
    applyRecipeScaleMultiplier(scaleInput);
    const draft = snapshot();
    commitRecipeEditScaleMultiplier(scaleInput);
    return { value, draft, committed: snapshot() };
});

scaleInput.value = "2.5";
const enter = {
    key: "Enter",
    prevented: false,
    preventDefault() { this.prevented = true; },
};
handleRecipeEditScaleKeydown(enter, scaleInput);
const afterEnter = snapshot();

process.stdout.write(JSON.stringify({ lastValid, invalidResults, enter, afterEnter }));
"""
    result = run_node(harness)

    assert result["lastValid"] == {
        "text": "1.25",
        "active": "1.25",
        "quantity": "5/8",
        "shoppingMultiplier": "1.25",
        "errorVisible": False,
        "message": "Scale must be a positive number, decimal, or fraction.",
        "invalid": None,
    }
    for invalid in result["invalidResults"]:
        assert invalid["draft"] == {
            "text": invalid["value"],
            "active": "1.25",
            "quantity": "5/8",
            "shoppingMultiplier": "1.25",
            "errorVisible": False,
            "message": "Scale must be a positive number, decimal, or fraction.",
            "invalid": None,
        }
        assert invalid["committed"] == {
            "text": "1.25",
            "active": "1.25",
            "quantity": "5/8",
            "shoppingMultiplier": "1.25",
            "errorVisible": True,
            "message": "Scale must be a positive number, decimal, or fraction.",
            "invalid": "true",
        }

    assert result["enter"]["prevented"] is True
    assert result["afterEnter"] == {
        "text": "2.5",
        "active": "2.5",
        "quantity": "1 1/4",
        "shoppingMultiplier": "2.5",
        "errorVisible": False,
        "message": "Scale must be a positive number, decimal, or fraction.",
        "invalid": None,
    }


def test_recipe_scale_save_validation_catches_uncommitted_invalid_draft():
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
        "recipeEditCanonicalTitleControl()"
    )
    assert "showRecipeEditorValidationErrors(errors)" in validator
    assert 'firstControl.focus({ preventScroll: true })' in reveal
    assert "validateRecipeEditScaleField" not in control
    assert "setRecipeScaleValidationMessage(\"\")" in control


def test_recipe_servings_stepper_updates_direct_edits_and_never_crosses_minimum():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    servings_control = script[
        script.index("function recipeEditServingsParts"):
        script.index("function closeRecipeEditMetadataTooltips")
    ]
    harness = r"""
function normalizeRecipeEditTagText(value) {
    return String(value || "").trim();
}
const events = [];
let focusCount = 0;
const servingsInput = {
    value: "4 servings",
    dataset: {},
    dispatchEvent(event) { events.push(event.type); return true; },
};
const countInput = {
    value: "",
    focus() { focusCount += 1; },
};
const decrement = { disabled: false };
const document = {
    getElementById(id) {
        return {
            recipeEditServings: servingsInput,
            recipeEditServingsCount: countInput,
        }[id] || null;
    },
    querySelector(selector) {
        return selector === "[data-recipe-edit-servings-decrement]" ? decrement : null;
    },
};
""" + servings_control + r"""

function snapshot() {
    return {
        stored: servingsInput.value,
        count: countInput.value,
        decrementDisabled: decrement.disabled,
        events: [...events],
        focusCount,
    };
}

syncRecipeEditServingsStepper();
const initial = snapshot();

events.length = 0;
stepRecipeEditServings(-1);
const decremented = snapshot();

events.length = 0;
countInput.value = "1";
updateRecipeEditServingsFromStepper(countInput);
const atMinimum = snapshot();

events.length = 0;
stepRecipeEditServings(-1);
const attemptedBelowMinimum = snapshot();

events.length = 0;
countInput.value = "12";
updateRecipeEditServingsFromStepper(countInput);
const directEdit = snapshot();

events.length = 0;
stepRecipeEditServings(1);
const incremented = snapshot();

process.stdout.write(JSON.stringify({
    initial,
    decremented,
    atMinimum,
    attemptedBelowMinimum,
    directEdit,
    incremented,
}));
"""
    result = run_node(harness)

    assert result["initial"] == {
        "stored": "4 servings",
        "count": "4",
        "decrementDisabled": False,
        "events": [],
        "focusCount": 0,
    }
    assert result["decremented"] == {
        "stored": "3 servings",
        "count": "3",
        "decrementDisabled": False,
        "events": ["input", "change"],
        "focusCount": 1,
    }
    assert result["atMinimum"] == {
        "stored": "1 servings",
        "count": "1",
        "decrementDisabled": True,
        "events": ["input", "change"],
        "focusCount": 1,
    }
    assert result["attemptedBelowMinimum"] == {
        "stored": "1 servings",
        "count": "1",
        "decrementDisabled": True,
        "events": ["input", "change"],
        "focusCount": 2,
    }
    assert result["directEdit"] == {
        "stored": "12 servings",
        "count": "12",
        "decrementDisabled": False,
        "events": ["input", "change"],
        "focusCount": 2,
    }
    assert result["incremented"] == {
        "stored": "13 servings",
        "count": "13",
        "decrementDisabled": False,
        "events": ["input", "change"],
        "focusCount": 3,
    }


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
