import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_cuisine_icon_visuals_load_before_the_main_application_script():
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")

    helper = "js/cuisine-icon-visuals.js"
    application = "js/app.js"
    assert helper in layout
    assert layout.index(helper) < layout.index(application)


def test_cuisine_icon_picker_has_progressive_select_and_accessible_combobox_contract():
    template = read_text("PushShoppingList/templates/cuisine_categories.html")

    assert "data-cuisine-category-master-icon-picker" in template
    assert "data-cuisine-category-master-icon>" in template
    assert 'role="combobox"' in template
    assert 'aria-haspopup="listbox"' in template
    assert 'aria-expanded="false"' in template
    assert 'aria-controls="cuisineCategoryIconListbox"' in template
    assert 'id="cuisineCategoryIconListbox"' in template
    assert 'role="listbox"' in template
    assert "data-cuisine-category-master-icon-search" in template
    assert '<optgroup label="Flags">' in template
    assert '<optgroup label="Cuisine symbols">' in template
    assert '("gb", "United Kingdom")' in template
    assert '("jp", "Japan")' in template
    assert '("plate", "Plate and utensils")' in template


def test_shared_renderer_normalizes_tokens_draws_local_flags_and_keeps_legacy_symbols():
    node = shutil.which("node")
    if not node:
        return

    helper_path = ROOT / "PushShoppingList/static/js/cuisine-icon-visuals.js"
    harness = r"""
const fs = require("fs");

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(...values) { values.forEach(value => this.values.add(value)); }
    remove(...values) { values.forEach(value => this.values.delete(value)); }
    toggle(value, force) {
        if (force === undefined) force = !this.values.has(value);
        if (force) this.values.add(value); else this.values.delete(value);
        return force;
    }
    contains(value) { return this.values.has(value); }
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.attributes = {};
        this.children = [];
        this.classList = new FakeClassList();
        this.dataset = {};
        this.innerHTML = "";
        this._textContent = "";
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...children) { this.children = children; this._textContent = ""; }
    set textContent(value) { this._textContent = String(value); this.children = []; }
    get textContent() { return this._textContent; }
}

global.window = {};
global.document = {
    createElement(tagName) { return new FakeElement(tagName); },
    createElementNS(_namespace, tagName) { return new FakeElement(tagName); },
};
eval(fs.readFileSync(process.argv[1], "utf8"));

const api = window.CuisineIconVisuals;
const vectors = api.supportedFlagCodes.map(code => api.createFlagSvg(code));
const gb = api.create(" FLAG:GB ");
const legacy = api.create("🍲");
const unsupported = api.create("flag:zz");
process.stdout.write(JSON.stringify({
    count: api.supportedFlagCodes.length,
    allVectors: vectors.every(svg => svg && svg.tagName === "svg" && svg.innerHTML.length > 60),
    vectorClasses: vectors.every(svg => svg.classList.contains("cuisine-category-flag-svg")),
    gbToken: api.descriptor(" FLAG:GB ").token,
    gbLabel: api.descriptor("flag:gb").label,
    gbChild: gb.children[0]?.tagName,
    gbMarkupHasShapes: /<(rect|path|polygon)/.test(gb.children[0]?.innerHTML || ""),
    legacyKind: api.descriptor("🍲").kind,
    legacyGlyph: legacy.textContent,
    breadGlyph: api.descriptor("symbol:bread").glyph,
    symbolTokens: api.symbolTokens,
    unsupportedText: unsupported.children[0]?.textContent || unsupported.textContent,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(helper_path)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["count"] == 30
    assert result["allVectors"] is True
    assert result["vectorClasses"] is True
    assert result["gbToken"] == "flag:gb"
    assert result["gbLabel"] == "United Kingdom flag"
    assert result["gbChild"] == "svg"
    assert result["gbMarkupHasShapes"] is True
    assert result["legacyKind"] == "custom"
    assert result["legacyGlyph"] == "🍲"
    assert result["breadGlyph"] == "🍞"
    assert result["symbolTokens"] == [
        "symbol:bread",
        "symbol:bowl",
        "symbol:curry",
        "symbol:globe",
        "symbol:noodles",
        "symbol:plate",
        "symbol:taco",
    ]
    # Unsupported tokens remain visible without falling back to country-code letters.
    assert result["unsupportedText"] == "◆"


def test_cuisine_picker_js_preserves_manual_choices_and_supports_keyboard_navigation():
    script = read_text("PushShoppingList/static/js/cuisine_categories.js")

    assert "let iconChoiceExplicit = false;" in script
    assert "const suggestFlagFromAbbreviation = () => {" in script
    assert "if (iconChoiceExplicit) return;" in script
    assert "iconVisuals?.supportedFlagCodes" in script
    assert 'setIconSelection(option.dataset.cuisineCategoryMasterIconOption, { explicit: true });' in script
    assert 'abbreviationInput.addEventListener("input", suggestFlagFromAbbreviation);' in script
    assert '["ArrowDown", "ArrowUp", "Home", "End"]' in script
    assert 'event.key === "Escape"' in script
    assert 'iconTrigger.setAttribute("aria-expanded", "true");' in script
    assert 'iconTrigger.setAttribute("aria-expanded", "false");' in script
    assert "iconChoiceExplicit = Boolean(item);" in script
    assert "iconTrigger.focus({ preventScroll: true })" in script
    assert "iconInput.focus" not in script
    assert "requestAnimationFrame(() => iconInput.focus" not in script


def test_cuisine_picker_focusout_waits_for_pointer_selection_to_commit():
    script = read_text("PushShoppingList/static/js/cuisine_categories.js")

    assert 'iconPicker.addEventListener("focusout", () => {' in script
    assert "window.setTimeout(() => {" in script
    assert "if (!iconPicker.contains(document.activeElement)) closeIconPicker();" in script
    assert "queueMicrotask(" not in script


def test_cuisine_picker_styles_are_scoped_responsive_and_use_local_flag_svgs():
    css = read_text("PushShoppingList/static/css/app.css")

    assert ".cuisine-category-flag-svg {" in css
    assert "forced-color-adjust: none;" in css
    assert ".cuisine-category-master-icon-picker.is-enhanced" in css
    assert ".cuisine-category-master-icon-menu[hidden]" in css
    assert ".cuisine-category-master-icon-option.is-selected" in css
    assert ".cuisine-category-master-icon-trigger[aria-invalid=\"true\"]" in css
    assert "@media (max-width: 520px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
