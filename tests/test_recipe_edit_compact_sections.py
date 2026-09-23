import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_compact_sections_move_live_controls_and_share_accessible_tab_navigation():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the editor DOM behavior test")
    app = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    tab_functions = app[app.index("function recipeEditTabKey("):app.index("function recipeEditInputValue(")]
    sections = (ROOT / "PushShoppingList/static/js/recipe-edit-sections.js").read_text(encoding="utf-8")
    harness = r'''
const assert = require("node:assert/strict");
class Element {
    constructor(tag = "div", className = "") {
        this.tagName = tag.toUpperCase(); this.className = className;
        this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
        this.hidden = false;
        this.classList = {
            remove: name => { this.className = this.className.split(" ").filter(value => value !== name).join(" "); },
            toggle: (name, on) => {
                this.classList.remove(name);
                if (on) this.className += " " + name;
            },
        };
    }
    appendChild(child) {
        if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(value => value !== child);
        this.children.push(child); child.parentElement = this; return child;
    }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
    fire(name, event = {}) { (this.listeners[name] || []).forEach(listener => listener(event)); }
    focus() { focused = this; }
    closest() {
        let current = this;
        while (current && !("recipeEditTabPanel" in current.dataset)) current = current.parentElement;
        return current;
    }
    querySelector(selector) { return selector === '[role="tablist"]' ? tabList : selector === ".recipe-edit-tab-panels" ? panelsRoot : null; }
    querySelectorAll(selector) {
        const key = selector === "[data-recipe-edit-tab]" ? "recipeEditTab" : "recipeEditTabPanel";
        const found = [];
        const walk = item => item.children.forEach(child => {
            if (key in child.dataset) found.push(child);
            walk(child);
        });
        walk(this); return found;
    }
    matches() { return this.attributes.role === "dialog" || /modal|backdrop/.test(this.className); }
}
let focused = null;
let standalone = false;
const body = new Element("body");
const tabsRoot = new Element();
const tabList = new Element();
const panelsRoot = new Element();
tabsRoot.append(tabList, panelsRoot);
const oldTabs = ["ingredients", "instructions", "equipment", "nutrition", "notes"];
oldTabs.forEach(key => {
    const button = new Element("button"); button.dataset.recipeEditTab = key;
    const panel = new Element("section"); panel.dataset.recipeEditTabPanel = key;
    tabList.appendChild(button); panelsRoot.appendChild(panel);
});
const sidebar = new Element("aside");
const info = new Element("section");
const cookbook = new Element(); cookbook.value = "existing-cookbook";
const menuSection = new Element(); menuSection.value = "desserts";
const priceField = new Element(); priceField.value = "12.50";
info.append(cookbook, menuSection, priceField);
const image = new Element("section");
const mobileImage = new Element();
const gallery = new Element("details");
const source = new Element("details");
const restaurant = new Element("details");
const ai = new Element("details", "recipe-edit-sticky-action-footer");
const health = new Element("details");
const confidence = new Element("details");
const dialog = new Element("div", "recipe-edit-source-documents-modal-backdrop");
dialog.hidden = true;
const remainingCard = new Element("section");
sidebar.append(image, gallery, source, restaurant, ai, health, confidence, dialog, remainingCard);
const controls = new Map([
    ["[data-recipe-edit-tabs]", tabsRoot],
    [".recipe-edit-info-panel:not(.recipe-edit-categories-panel)", info],
    ["#recipeEditCookbookField", cookbook],
    ["#recipeEditCategoryMenuSectionField", menuSection],
    [".recipe-edit-image-card", image],
    ["[data-recipe-edit-mobile-image-slot]", mobileImage],
    [".recipe-edit-ingredient-gallery-card", gallery],
    [".recipe-edit-source-documents-card", source],
    [".recipe-edit-restaurant-card", restaurant],
    [".recipe-edit-ai-assistant-card", ai],
    [".recipe-edit-health-card", health],
    [".recipe-edit-confidence-card", confidence],
    [".recipe-edit-context-sidebar", sidebar],
]);
const document = { body, querySelector: selector => controls.get(selector) || null, createElement: tag => new Element(tag) };
function recipeEditorStandalonePageIsActive() { return standalone; }
function recipeEditFieldContainer(id) { return id === "recipeEditMenuPrice" ? priceField : null; }
function clearRecipeIngredientScrollReserve() {}
function appMainScrollRegion() {}
function updateRecipeEditStickyOffsets() {}
'''
    assertions = r'''
assert.equal(organizeRecipeEditCompactSections(), false);
assert.equal(tabList.children.length, 5, "legacy modal is untouched");
standalone = true;
initRecipeEditTabs();
setRecipeEditActiveTab("notes");
let cookbookClicks = 0;
cookbook.addEventListener("click", () => cookbookClicks++);
assert.equal(organizeRecipeEditCompactSections(), true);
assert.equal(organizeRecipeEditCompactSections(), false, "organizer is idempotent");
assert.deepEqual(tabList.children.map(tab => tab.dataset.recipeEditTab), [
    ...oldTabs, "recipeimage", "recipeinformation", "cookbookassignment", "sourceinformation",
]);
assert.equal(tabList.children[4].attributes["aria-selected"], "true", "late tab binding preserves current selection");
const panels = Object.fromEntries(panelsRoot.children.map(panel => [panel.dataset.recipeEditTabPanel, panel]));
const inPanel = (control, key) => {
    let current = control;
    while (current && current !== panels[key]) current = current.parentElement;
    return current === panels[key];
};
assert(inPanel(info, "recipeinformation"));
assert(inPanel(ai, "recipeinformation"));
assert(inPanel(health, "recipeinformation"));
assert(inPanel(confidence, "recipeinformation"));
assert(inPanel(remainingCard, "recipeinformation"));
assert(inPanel(cookbook, "cookbookassignment"));
assert(inPanel(menuSection, "cookbookassignment"));
assert(inPanel(priceField, "cookbookassignment"));
assert.equal(cookbook.value, "existing-cookbook");
assert.equal(menuSection.value, "desserts");
assert.equal(priceField.value, "12.50");
cookbook.fire("click"); assert.equal(cookbookClicks, 1, "existing handlers survive the move");
assert(inPanel(image, "recipeimage")); assert(inPanel(mobileImage, "recipeimage")); assert(inPanel(gallery, "recipeimage"));
assert(inPanel(source, "sourceinformation")); assert(inPanel(restaurant, "sourceinformation"));
assert.equal(source.open, true); assert.equal(restaurant.open, true);
assert.equal(dialog.parentElement, tabsRoot, "dialogs have no hidden tab ancestor");
assert.equal(dialog.hidden, true, "dialog open state is preserved");
assert.equal(sidebar.children.length, 0); assert.equal(sidebar.hidden, true);
for (const key of ["recipeimage", "recipeinformation", "cookbookassignment", "sourceinformation"]) {
    const tab = tabList.children.find(button => button.dataset.recipeEditTab === key);
    assert.equal(tab.listeners.click.length, 1);
    assert.equal(tab.attributes["aria-controls"], panels[key].id);
    assert.equal(panels[key].attributes["aria-labelledby"], tab.id);
    tab.fire("click");
    assert.equal(tab.attributes["aria-selected"], "true");
    assert.equal(panels[key].hidden, false);
    assert.equal(panelsRoot.children.filter(panel => !panel.hidden).length, 1);
}
const sourceTab = tabList.children[8];
let prevented = false;
sourceTab.fire("keydown", {key: "ArrowRight", preventDefault() { prevented = true; }});
assert.equal(prevented, true); assert.equal(focused, tabList.children[0]);
tabList.children[0].fire("keydown", {key: "End", preventDefault() {}});
assert.equal(focused, sourceTab); assert.equal(panels.sourceinformation.hidden, false);
revealRecipeEditControlPanel(cookbook);
assert.equal(panels.cookbookassignment.hidden, false, "validation and AI field focus reveal the target section");
console.log(JSON.stringify({tabs: tabList.children.length, panels: panelsRoot.children.length}));
'''
    result = subprocess.run([node, "-e", harness + tab_functions + sections + assertions], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"tabs": 9, "panels": 9}
