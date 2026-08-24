import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from PushShoppingList.services.cuisine_category_service import (
    ISO_ALPHA2_COUNTRY_CODES,
)


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_cuisine_icon_assets_load_before_the_main_application_script():
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")

    catalog = "js/country-territory-catalog.js"
    helper = "js/cuisine-icon-visuals.js"
    application = "js/app.js"
    assert catalog in layout
    assert helper in layout
    assert layout.index(catalog) < layout.index(helper) < layout.index(application)
    assert "data-cuisine-flag-sprite-url" in layout
    assert "vendor/flag-icons/flags-4x3.svg" in layout


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
    assert '<optgroup label="Flags"' in template
    assert "data-cuisine-category-master-flag-options" in template
    assert '<optgroup label="Cuisine symbols">' in template
    assert "cuisine_flag_options" not in template
    assert '("plate", "Plate and utensils")' in template


def test_shared_renderer_draws_every_iso_flag_locally_and_keeps_legacy_symbols():
    node = shutil.which("node")
    if not node:
        return

    catalog_path = ROOT / "PushShoppingList/static/js/country-territory-catalog.js"
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
    currentScript: {
        dataset: { cuisineFlagSpriteUrl: "/static/vendor/flag-icons/flags-4x3.svg" },
    },
    createElement(tagName) { return new FakeElement(tagName); },
    createElementNS(_namespace, tagName) { return new FakeElement(tagName); },
};
eval(fs.readFileSync(process.argv[1], "utf8"));
eval(fs.readFileSync(process.argv[2], "utf8"));

const api = window.CuisineIconVisuals;
const vectors = api.supportedFlagCodes.map(code => api.createFlagSvg(code));
const gb = api.create(" FLAG:GB ");
const legacy = api.create("\u{1F372}");
const unsupported = api.create("flag:zz");
process.stdout.write(JSON.stringify({
    count: api.supportedFlagCodes.length,
    allVectors: vectors.every(svg => svg && svg.tagName === "svg" && svg.children[0]?.tagName === "use"),
    vectorClasses: vectors.every(svg => svg.classList.contains("cuisine-category-flag-svg")),
    allLocalUses: vectors.every((svg, index) => svg.children[0]?.attributes.href === `/static/vendor/flag-icons/flags-4x3.svg#flag-icons-${api.supportedFlagCodes[index]}`),
    gbToken: api.descriptor(" FLAG:GB ").token,
    gbLabel: api.descriptor("flag:gb").label,
    gbChild: gb.children[0]?.tagName,
    gbUseHref: gb.children[0]?.children[0]?.attributes.href,
    legacyKind: api.descriptor("\u{1F372}").kind,
    legacyGlyph: legacy.textContent,
    breadGlyph: api.descriptor("symbol:bread").glyph,
    symbolTokens: api.symbolTokens,
    unsupportedText: unsupported.children[0]?.textContent || unsupported.textContent,
    hasBouvet: window.CountryTerritoryCatalog.byCode("BV")?.name,
    rejectsKosovo: window.CountryTerritoryCatalog.byCode("xk"),
}));
"""
    completed = subprocess.run(
        [node, "-e", harness, str(catalog_path), str(helper_path)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["count"] == 249
    assert result["allVectors"] is True
    assert result["vectorClasses"] is True
    assert result["allLocalUses"] is True
    assert result["gbToken"] == "flag:gb"
    assert result["gbLabel"] == "United Kingdom flag"
    assert result["gbChild"] == "svg"
    assert result["gbUseHref"].endswith("/flags-4x3.svg#flag-icons-gb")
    assert result["legacyKind"] == "custom"
    assert result["legacyGlyph"] == "\U0001f372"
    assert result["breadGlyph"] == "\U0001f35e"
    assert result["symbolTokens"] == [
        "symbol:bread",
        "symbol:bowl",
        "symbol:curry",
        "symbol:globe",
        "symbol:noodles",
        "symbol:plate",
        "symbol:taco",
    ]
    assert result["unsupportedText"] == "\u25c6"
    assert result["hasBouvet"] == "Bouvet Island"
    assert result["rejectsKosovo"] is None


def test_country_catalog_and_local_sprite_cover_the_same_249_iso_entries():
    catalog = read_text("PushShoppingList/static/js/country-territory-catalog.js")
    catalog_codes = re.findall(r'^\s*\["([a-z]{2})",', catalog, re.MULTILINE)
    assert len(catalog_codes) == 249
    assert len(set(catalog_codes)) == 249
    assert not ({"xk", "eu", "un"} & set(catalog_codes))
    assert {code.upper() for code in catalog_codes} == ISO_ALPHA2_COUNTRY_CODES
    assert "dialCode" not in catalog
    assert "phoneEntries" not in catalog
    assert not re.search(r"(?:Ã|Â|�|\?[A-Za-z])", catalog)
    assert '["aq","Antarctica","Antarctica",[]]' in catalog

    sprite_path = ROOT / "PushShoppingList/static/vendor/flag-icons/flags-4x3.svg"
    root = ET.parse(sprite_path).getroot()
    symbol_ids = {
        element.attrib["id"]
        for element in root
        if element.tag.endswith("symbol") and "id" in element.attrib
    }
    assert symbol_ids == {f"flag-icons-{code}" for code in catalog_codes}

    all_ids = [
        element.attrib["id"]
        for element in root.iter()
        if "id" in element.attrib
    ]
    assert len(all_ids) == len(set(all_ids))
    for element in root.iter():
        for attribute, value in element.attrib.items():
            if attribute.endswith("href") and value.startswith("#"):
                assert value[1:] in set(all_ids)


def test_vendored_flag_icons_records_source_version_and_mit_license():
    readme = read_text("PushShoppingList/static/vendor/flag-icons/README.md")
    license_text = read_text("PushShoppingList/static/vendor/flag-icons/LICENSE")

    assert "flag-icons` 7.5.0" in readme
    assert "249 `iso: true`" in readme
    assert "same-origin asset request" in readme
    assert "The MIT License (MIT)" in license_text
    assert "Copyright (c) 2013 Panayiotis Lipiridis" in license_text


def test_cuisine_picker_js_populates_catalog_and_preserves_manual_choices():
    script = read_text("PushShoppingList/static/js/cuisine_categories.js")

    assert "const populateFlagOptions = () => {" in script
    assert "countryCatalog?.entries" in script
    assert "option.dataset.searchAliases" in script
    assert "marker.replaceWith(...groups);" in script
    assert "populateFlagOptions();" in script
    assert "let iconChoiceExplicit = false;" in script
    assert "const suggestFlagFromAbbreviation = () => {" in script
    assert "if (iconChoiceExplicit) return;" in script
    assert "state.textContent = suggestedIconToken" in script
    assert "&& record.token === suggestedIconToken" in script
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
    assert '.cuisine-category-master-icon-trigger[aria-invalid="true"]' in css
    assert "@media (max-width: 520px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
