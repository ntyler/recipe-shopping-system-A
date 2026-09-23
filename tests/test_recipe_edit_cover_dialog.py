"""Cover popup lifecycle keeps the canonical image controls and editor context."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "PushShoppingList/static/js/recipe-edit-cover-dialog.js"


def run_cover_dialog_javascript(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the recipe cover dialog contract")
    script = HARNESS + SCRIPT.read_text(encoding="utf-8") + "\n" + scenario
    result = subprocess.run(
        [node], input=script, cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=10,
    )
    return json.loads(result.stdout)


HARNESS = r"""
const nodes = new Map();
const focusLog = [];
const promptCloses = [];
const menuCloses = [];
const observers = [];
const detachedImageLookupVisibility = [];
let standalone = true;
let activeTab = 'ingredients';
let dialogCreations = 0;
function node(tag, id = '') {
    const result = {
        tagName: tag.toUpperCase(), id, dataset: {}, attributes: {}, children: [], listeners: {},
        hidden: false, open: false, textContent: '', parentNode: null,
        classList: {
            values: new Set(),
            add(value) { this.values.add(value); },
            remove(value) { this.values.delete(value); },
            contains(value) { return this.values.has(value); },
            toggle(value, enabled) { if (enabled) this.values.add(value); else this.values.delete(value); },
        },
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name] ?? null; },
        hasAttribute(name) { return name in this.attributes; },
        removeAttribute(name) { delete this.attributes[name]; },
        appendChild(child) {
            if (child.parentNode) child.parentNode.children = child.parentNode.children.filter(item => item !== child);
            this.children.push(child);
            child.parentNode = this;
            if (child.id) nodes.set(child.id, child);
            if (child.id === 'canonical-cover-card' && this.parentNode?.tagName === 'DIALOG') {
                detachedImageLookupVisibility.push(Boolean(document.getElementById('recipeEditCoverImage')));
            }
            return child;
        },
        addEventListener(name, callback) { this.listeners[name] = callback; },
        querySelector(selector) {
            if (selector === '[data-cover-dialog-close]') return this.parts?.close || null;
            if (selector === '[data-cover-dialog-status]') return this.parts?.status || null;
            if (selector === '.recipe-edit-cover-dialog-body') return this.parts?.body || null;
            if (selector === '[data-recipe-image-change-actions]') return this.menuPresent ? {} : null;
            if (selector.startsWith('#')) {
                const find = parent => {
                    for (const child of parent.children) {
                        if (child.id === selector.slice(1)) return child;
                        const nested = find(child);
                        if (nested) return nested;
                    }
                    return null;
                };
                return find(this);
            }
            return null;
        },
        querySelectorAll() { return (this.focusControls || []).filter(control => !control.disabled); },
        getClientRects() { return this.noRects ? [] : [{}]; },
        getBoundingClientRect() { return {left: 100, right: 600, top: 80, bottom: 550}; },
        focus(options) { document.activeElement = this; focusLog.push({id: this.id, options}); },
        showModal() { this.open = true; this.showCount = (this.showCount || 0) + 1; },
        close() { this.open = false; this.listeners.close?.(); },
    };
    Object.defineProperty(result, 'isConnected', {
        get() {
            let ancestor = result;
            while (ancestor) {
                if (ancestor.isDocumentRoot) return true;
                ancestor = ancestor.parentNode;
            }
            return false;
        },
    });
    Object.defineProperty(result, 'src', {
        get() { return result.getAttribute('src') || ''; },
        set(value) { result.setAttribute('src', value); },
    });
    if (tag === 'dialog') {
        dialogCreations++;
        result.parts = {close: node('button', 'popup-close'), status: node('p'), body: node('div')};
        result.appendChild(result.parts.close);
        result.appendChild(result.parts.status);
        result.appendChild(result.parts.body);
    }
    if (id) nodes.set(id, result);
    return result;
}
const form = node('form', 'recipeEditForm');
const originalHost = node('section', 'recipe-image-tab');
form.appendChild(originalHost);
const card = node('section', 'canonical-cover-card');
const image = node('img', 'recipeEditCoverImage');
image.classList.add('recipe-cover-image');
image.setAttribute('role', 'button');
image.setAttribute('tabindex', '0');
image.setAttribute('title', 'Enlarge image');
image.setAttribute('alt', 'Saved corn bread');
card.appendChild(image);
originalHost.appendChild(card);
const prompt = node('div', 'recipeEditImagePromptModal');
prompt.hidden = true;
form.appendChild(prompt);
const sourceStatus = node('p', 'recipeEditStatus');
form.appendChild(sourceStatus);
const trigger = node('button', 'summary-cover-trigger');
const alternateTrigger = node('button', 'alternate-trigger');
const coverData = {path: 'saved/cover.png', url: 'https://example.test/cover.png', prompt: 'Existing prompt'};
const body = node('body');
body.isDocumentRoot = true;
body.appendChild(form);
body.appendChild(trigger);
body.appendChild(alternateTrigger);
const document = {
    body,
    activeElement: null,
    getElementById: id => nodes.get(id)?.isConnected ? nodes.get(id) : null,
    querySelector(selector) {
        if (selector === '.recipe-edit-image-card') return card;
        if (selector === '[data-summary-cover-dialog]') return trigger;
        return null;
    },
    createElement: tag => node(tag),
};
class MutationObserver {
    constructor(callback) { this.callback = callback; this.targets = []; observers.push(this); }
    observe(target, options) { this.targets.push({id: target.id, options}); }
}
function recipeEditorStandalonePageIsActive() { return standalone; }
function recipeImagePromptModal() { return prompt; }
function closeRecipeImagePromptModal(options = {}) { prompt.hidden = true; promptCloses.push(options); }
function closeRecipeImageChangeActions(options = {}) {
    menuCloses.push(options);
    const dialog = nodes.get('recipeEditCoverDialog');
    if (dialog) dialog.menuPresent = false;
}
function setRecipeEditActiveTab(tab) { activeTab = tab; }
function event(values = {}) {
    return {...values, prevented: false, preventDefault() { this.prevented = true; }};
}
"""


def test_organizing_moves_original_controls_into_one_dialog_inside_the_form():
    result = run_cover_dialog_javascript(r"""
organizeRecipeEditCoverDialog();
organizeRecipeEditCoverDialog();
const dialog = document.getElementById('recipeEditCoverDialog');
process.stdout.write(JSON.stringify({
    dialogCreations, sameCard: dialog.parts.body.children[0] === card,
    withinForm: card.parentNode.parentNode.parentNode === form,
    samePrompt: prompt.parentNode === dialog, imageStillInCard: image.parentNode === card,
    oldHostEmpty: originalHost.children.length === 0,
    imageLightboxClass: image.classList.contains('recipe-cover-image'), imageAttributes: image.attributes,
    observerTargets: observers[0].targets, coverData, detachedImageLookupVisibility,
}));
""")

    assert result["dialogCreations"] == 1
    assert result["sameCard"] and result["withinForm"] and result["samePrompt"]
    assert result["imageStillInCard"] and result["oldHostEmpty"]
    assert result["imageLightboxClass"] is False
    assert result["detachedImageLookupVisibility"] == [False]
    assert result["imageAttributes"] == {"alt": "Saved corn bread"}
    assert [target["id"] for target in result["observerTargets"]] == ["recipeEditCoverImage", "recipeEditStatus"]
    assert result["coverData"]["prompt"] == "Existing prompt"


def test_open_preserves_active_tab_and_close_restores_exact_trigger_focus():
    result = run_cover_dialog_javascript(r"""
image.src = '/thumb.png';
image.dataset.fullSrc = '/full.png';
image.setAttribute('srcset', '/thumb.png 200w');
const before = JSON.stringify(coverData);
openRecipeEditCoverDialog(alternateTrigger);
openRecipeEditCoverDialog(trigger);
const dialog = document.getElementById('recipeEditCoverDialog');
const opened = {
    open: dialog.open, bodyClass: body.classList.contains('recipe-edit-cover-dialog-open'),
    fullSrc: image.src, srcset: image.getAttribute('srcset'), showCount: dialog.showCount,
    focused: focusLog.at(-1), activeTab,
};
prompt.hidden = false;
closeRecipeEditCoverDialog();
process.stdout.write(JSON.stringify({opened, closed: !dialog.open, activeTab,
    bodyClass: body.classList.contains('recipe-edit-cover-dialog-open'), promptHidden: prompt.hidden,
    promptCloses, returnedFocus: focusLog.at(-1), unchanged: before === JSON.stringify(coverData)}));
""")

    assert result["opened"] == {
        "open": True, "bodyClass": True, "fullSrc": "/full.png", "srcset": None,
        "showCount": 1, "focused": {"id": "popup-close", "options": {"preventScroll": True}},
        "activeTab": "ingredients",
    }
    assert result["closed"] and result["promptHidden"] and result["unchanged"]
    assert result["bodyClass"] is False
    assert result["returnedFocus"] == {"id": "alternate-trigger", "options": {"preventScroll": True}}
    assert all(call.get("restoreFocus") is False for call in result["promptCloses"])
    assert result["activeTab"] == "ingredients"


def test_escape_closes_nested_prompt_then_menu_before_the_parent_dialog():
    result = run_cover_dialog_javascript(r"""
openRecipeEditCoverDialog();
const dialog = document.getElementById('recipeEditCoverDialog');
prompt.hidden = false;
const promptEscape = event();
dialog.listeners.cancel(promptEscape);
const afterPrompt = {dialogOpen: dialog.open, promptHidden: prompt.hidden, prevented: promptEscape.prevented};
dialog.menuPresent = true;
const menuEscape = event();
dialog.listeners.cancel(menuEscape);
const afterMenu = {dialogOpen: dialog.open, menuPresent: dialog.menuPresent, prevented: menuEscape.prevented, closeOptions: menuCloses.at(-1)};
const dialogEscape = event();
dialog.listeners.cancel(dialogEscape);
process.stdout.write(JSON.stringify({afterPrompt, afterMenu, finalOpen: dialog.open, finalPrevented: dialogEscape.prevented, returnedFocus: focusLog.at(-1)}));
""")

    assert result["afterPrompt"] == {"dialogOpen": True, "promptHidden": True, "prevented": True}
    assert result["afterMenu"] == {
        "dialogOpen": True, "menuPresent": False, "prevented": True,
        "closeOptions": {"restoreFocus": True},
    }
    assert result["finalOpen"] is False and result["finalPrevented"] is True
    assert result["returnedFocus"]["id"] == "summary-cover-trigger"


def test_observed_image_and_status_updates_use_full_resolution_and_empty_state():
    result = run_cover_dialog_javascript(r"""
openRecipeEditCoverDialog();
const dialog = document.getElementById('recipeEditCoverDialog');
const initialLabel = trigger.getAttribute('aria-label');
image.src = '/new-card.png';
image.dataset.fullSrc = '/new-full.png';
image.setAttribute('srcset', '/new-card.png 200w');
sourceStatus.textContent = 'Image upload failed. Try another file.';
sourceStatus.classList.add('error');
observers[0].callback();
const status = dialog.parts.status;
const updated = {src: image.src, srcset: image.getAttribute('srcset'), label: trigger.getAttribute('aria-label'), message: status.textContent, hidden: status.hidden, error: status.classList.contains('error')};
image.removeAttribute('src');
delete image.dataset.fullSrc;
sourceStatus.textContent = '';
sourceStatus.classList.remove('error');
observers[0].callback();
process.stdout.write(JSON.stringify({initialLabel, updated,
    removed: {src: image.src, label: trigger.getAttribute('aria-label'), message: status.textContent, hidden: status.hidden, error: status.classList.contains('error')}}));
""")

    assert result["initialLabel"] == "Add recipe image"
    assert result["updated"] == {
        "src": "/new-full.png", "srcset": None, "label": "Edit recipe image",
        "message": "Image upload failed. Try another file.", "hidden": False, "error": True,
    }
    assert result["removed"] == {
        "src": "", "label": "Add recipe image", "message": "", "hidden": True, "error": False,
    }


def test_backdrop_clicks_close_only_outside_dialog_bounds_and_legacy_editor_is_untouched():
    result = run_cover_dialog_javascript(r"""
standalone = false;
openRecipeEditCoverDialog();
const legacyCreated = dialogCreations;
standalone = true;
openRecipeEditCoverDialog();
const dialog = document.getElementById('recipeEditCoverDialog');
dialog.listeners.click(event({target: card, clientX: 0, clientY: 0}));
dialog.listeners.click(event({target: dialog, clientX: 120, clientY: 100}));
const insideOpen = dialog.open;
dialog.listeners.click(event({target: dialog, clientX: 80, clientY: 100}));
process.stdout.write(JSON.stringify({legacyCreated, insideOpen, closed: !dialog.open}));
""")

    assert result == {"legacyCreated": 0, "insideOpen": True, "closed": True}


def test_tab_wraps_visible_controls_and_yields_to_nested_prompt_focus_trap():
    result = run_cover_dialog_javascript(r"""
openRecipeEditCoverDialog();
const dialog = document.getElementById('recipeEditCoverDialog');
const first = dialog.parts.close;
const middle = node('button', 'upload-image');
const last = node('button', 'edit-image-prompt');
const hiddenFirst = node('button', 'hidden-before');
const hiddenLast = node('button', 'hidden-after');
hiddenFirst.hidden = true;
hiddenLast.hidden = true;
const cssHidden = node('button', 'css-hidden');
cssHidden.noRects = true;
const disabled = node('button', 'disabled');
disabled.disabled = true;
dialog.focusControls = [hiddenFirst, first, middle, cssHidden, disabled, last, hiddenLast];
document.activeElement = last;
const forward = event({key: 'Tab', currentTarget: dialog});
dialog.listeners.keydown(forward);
const forwardTarget = document.activeElement.id;
const backward = event({key: 'Tab', shiftKey: true, currentTarget: dialog});
dialog.listeners.keydown(backward);
const backwardTarget = document.activeElement.id;
document.activeElement = middle;
const interior = event({key: 'Tab', currentTarget: dialog});
dialog.listeners.keydown(interior);
prompt.hidden = false;
document.activeElement = last;
const nested = event({key: 'Tab', currentTarget: dialog});
const beforeNestedFocusCount = focusLog.length;
dialog.listeners.keydown(nested);
const nestedFocusCount = focusLog.length;
prompt.hidden = true;
dialog.focusControls = [hiddenFirst, cssHidden, disabled];
const empty = event({key: 'Tab', currentTarget: dialog});
dialog.listeners.keydown(empty);
process.stdout.write(JSON.stringify({forwardTarget, backwardTarget,
    forwardPrevented: forward.prevented, backwardPrevented: backward.prevented,
    interiorPrevented: interior.prevented, nestedPrevented: nested.prevented,
    nestedUnchangedFocus: beforeNestedFocusCount === nestedFocusCount, emptyPrevented: empty.prevented}));
""")

    assert result == {
        "forwardTarget": "popup-close", "backwardTarget": "edit-image-prompt",
        "forwardPrevented": True, "backwardPrevented": True,
        "interiorPrevented": False, "nestedPrevented": False,
        "nestedUnchangedFocus": True, "emptyPrevented": False,
    }
