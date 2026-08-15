import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "PushShoppingList/static/js/app.js"


def _recipe_image_prompt_functions():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    start = script.index("function recipeImagePromptModal()")
    end = script.index("function setRecipeEditorCoverImageViewLoaded", start)
    return script[start:end]


def _run_modal_scenario(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the image prompt modal regression")

    harness = _NODE_HARNESS + _recipe_image_prompt_functions() + scenario
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


_NODE_HARNESS = r"""
let recipeEditImagePromptTrigger = null;
const frames = [];
const listeners = new Map();
const bodyClasses = new Set();
const focusLog = [];
const statusMessages = [];
const dirtyArguments = [];
let imageChangeCloseCount = 0;

let document;

function makeFocusable(name) {
    return {
        name,
        hidden: false,
        disabled: false,
        isConnected: true,
        lastFocusOptions: null,
        getAttribute(attribute) {
            if (attribute === "aria-hidden") return null;
            return null;
        },
        focus(options) {
            document.activeElement = this;
            this.lastFocusOptions = options || null;
            focusLog.push({ name: this.name, options: options || null });
        },
    };
}

const closeButton = makeFocusable("close");
const cancelButton = makeFocusable("cancel");
const saveButton = makeFocusable("save");
const trigger = makeFocusable("trigger");
const outside = makeFocusable("outside");
const draft = makeFocusable("draft");
draft.scrollHeight = 2400;
draft.scrollWidth = 900;
draft.scrollTop = 0;
draft.scrollLeft = 0;
draft.selectionStart = 0;
draft.selectionEnd = 0;
draft.setSelectionRange = function(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
};
draft.scrollTo = function(options = {}) {
    if (Object.prototype.hasOwnProperty.call(options, "top")) this.scrollTop = options.top;
    if (Object.prototype.hasOwnProperty.call(options, "left")) this.scrollLeft = options.left;
};
let draftValue = "";
Object.defineProperty(draft, "value", {
    get() {
        return draftValue;
    },
    set(value) {
        draftValue = String(value);
        this.selectionStart = draftValue.length;
        this.selectionEnd = draftValue.length;
        this.scrollTop = this.scrollHeight;
        this.scrollLeft = this.scrollWidth;
    },
});
draft.focus = function(options) {
    document.activeElement = this;
    this.lastFocusOptions = options || null;
    focusLog.push({ name: this.name, options: options || null });
    // Match the browser failure mode: focusing a reused textarea reveals the
    // caret at the end unless the modal resets selection and scroll afterward.
    this.scrollTop = this.scrollHeight;
    this.scrollLeft = this.scrollWidth;
};

const focusableElements = [closeButton, draft, cancelButton, saveButton];
const modal = {
    hidden: true,
    querySelector(selector) {
        if (selector === "[data-recipe-edit-image-prompt-draft]") return draft;
        return null;
    },
    querySelectorAll() {
        return focusableElements;
    },
    contains(element) {
        return focusableElements.includes(element);
    },
};
const promptText = { textContent: "" };
const recipeEditForm = { name: "recipeEditForm" };

document = {
    activeElement: outside,
    body: {
        classList: {
            add(name) { bodyClasses.add(name); },
            remove(name) { bodyClasses.delete(name); },
            contains(name) { return bodyClasses.has(name); },
        },
    },
    querySelector(selector) {
        if (selector === "[data-recipe-edit-image-prompt-modal]") return modal;
        return null;
    },
    getElementById(id) {
        if (id === "recipeEditCoverPromptText") return promptText;
        if (id === "recipeEditForm") return recipeEditForm;
        return null;
    },
    addEventListener(type, handler) {
        listeners.set(type, handler);
    },
    removeEventListener(type, handler) {
        if (listeners.get(type) === handler) listeners.delete(type);
    },
};

const window = {
    requestAnimationFrame(callback) {
        frames.push(callback);
        return frames.length;
    },
};

function closeRecipeImageChangeActions() {
    imageChangeCloseCount += 1;
}

function recipeEditorPersistableText(value) {
    return String(value || "").trim();
}

function updateRecipeEditorDirtyState(form) {
    dirtyArguments.push(form === recipeEditForm);
}

function setRecipeEditStatus(message) {
    statusMessages.push(message);
}

function drainAnimationFrames() {
    while (frames.length) frames.shift()();
}

function keyboardEvent(key, shiftKey = false) {
    return {
        key,
        shiftKey,
        defaultPrevented: false,
        propagationStopped: false,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { this.propagationStopped = true; },
    };
}

function dispatchKey(key, shiftKey = false) {
    const event = keyboardEvent(key, shiftKey);
    const handler = listeners.get("keydown");
    if (!handler) throw new Error(`No keydown listener registered for ${key}`);
    handler(event);
    return event;
}
"""


def test_recipe_image_prompt_open_preserves_full_prompt_and_focuses_its_beginning():
    result = _run_modal_scenario(
        r"""
const originalPrompt = "\nOpening composition detail  \n"
    + Array.from({ length: 80 }, (_, index) => `Prompt line ${index + 1}`).join("\n")
    + "\nFinal lighting detail  ";
promptText.textContent = originalPrompt;
draft.scrollTop = 731;
draft.scrollLeft = 43;

const returnValue = openRecipeImagePromptModal(trigger);
const beforeFrame = {
    populated: draft.value === originalPrompt,
    modalVisible: !modal.hidden,
    bodyLocked: bodyClasses.has("recipe-image-prompt-modal-open"),
    frameCount: frames.length,
};
drainAnimationFrames();

process.stdout.write(JSON.stringify({
    returnValue,
    beforeFrame,
    promptPreserved: promptText.textContent === originalPrompt,
    draftPreserved: draft.value === originalPrompt,
    focusedElement: document.activeElement?.name || "",
    focusOptions: draft.lastFocusOptions,
    selectionStart: draft.selectionStart,
    selectionEnd: draft.selectionEnd,
    scrollTop: draft.scrollTop,
    scrollLeft: draft.scrollLeft,
    listenerRegistered: listeners.has("keydown"),
    imageChangeCloseCount,
}));
"""
    )

    assert result == {
        "returnValue": False,
        "beforeFrame": {
            "populated": True,
            "modalVisible": True,
            "bodyLocked": True,
            "frameCount": 1,
        },
        "promptPreserved": True,
        "draftPreserved": True,
        "focusedElement": "draft",
        "focusOptions": {"preventScroll": True},
        "selectionStart": 0,
        "selectionEnd": 0,
        "scrollTop": 0,
        "scrollLeft": 0,
        "listenerRegistered": True,
        "imageChangeCloseCount": 1,
    }


def test_recipe_image_prompt_traps_focus_and_escape_restores_trigger_without_saving():
    result = _run_modal_scenario(
        r"""
const originalPrompt = "Saved prompt\nwith multiple lines";
promptText.textContent = originalPrompt;
openRecipeImagePromptModal(trigger);
const bodyLockedOnOpen = bodyClasses.has("recipe-image-prompt-modal-open");
drainAnimationFrames();

saveButton.focus();
const forwardTab = dispatchKey("Tab");
const afterForwardTab = document.activeElement?.name || "";
closeButton.focus();
const backwardTab = dispatchKey("Tab", true);
const afterBackwardTab = document.activeElement?.name || "";
document.activeElement = outside;
const outsideTab = dispatchKey("Tab");
const afterOutsideTab = document.activeElement?.name || "";

draft.value = "Unsaved Escape change";
draft.focus();
const escape = dispatchKey("Escape");

process.stdout.write(JSON.stringify({
    bodyLockedOnOpen,
    forwardTab: {
        prevented: forwardTab.defaultPrevented,
        stopped: forwardTab.propagationStopped,
        focus: afterForwardTab,
    },
    backwardTab: {
        prevented: backwardTab.defaultPrevented,
        stopped: backwardTab.propagationStopped,
        focus: afterBackwardTab,
    },
    outsideTab: {
        prevented: outsideTab.defaultPrevented,
        stopped: outsideTab.propagationStopped,
        focus: afterOutsideTab,
    },
    escape: {
        prevented: escape.defaultPrevented,
        stopped: escape.propagationStopped,
    },
    modalHidden: modal.hidden,
    bodyLockedAfterEscape: bodyClasses.has("recipe-image-prompt-modal-open"),
    listenerRegistered: listeners.has("keydown"),
    prompt: promptText.textContent,
    dirtyCalls: dirtyArguments.length,
    statuses: statusMessages,
    focusedElement: document.activeElement?.name || "",
    triggerFocusOptions: trigger.lastFocusOptions,
}));
"""
    )

    assert result == {
        "bodyLockedOnOpen": True,
        "forwardTab": {"prevented": True, "stopped": True, "focus": "close"},
        "backwardTab": {"prevented": True, "stopped": True, "focus": "save"},
        "outsideTab": {"prevented": True, "stopped": True, "focus": "close"},
        "escape": {"prevented": True, "stopped": True},
        "modalHidden": True,
        "bodyLockedAfterEscape": False,
        "listenerRegistered": False,
        "prompt": "Saved prompt\nwith multiple lines",
        "dirtyCalls": 0,
        "statuses": [],
        "focusedElement": "trigger",
        "triggerFocusOptions": {"preventScroll": True},
    }


def test_recipe_image_prompt_cancel_discards_draft_while_save_updates_existing_state():
    result = _run_modal_scenario(
        r"""
const originalPrompt = "Existing saved prompt";
promptText.textContent = originalPrompt;
openRecipeImagePromptModal(trigger);
drainAnimationFrames();
draft.value = "Unsaved Cancel change";
const bodyLockedBeforeCancel = bodyClasses.has("recipe-image-prompt-modal-open");
const cancelReturnValue = closeRecipeImagePromptModal();
const afterCancel = {
    prompt: promptText.textContent,
    modalHidden: modal.hidden,
    bodyLocked: bodyClasses.has("recipe-image-prompt-modal-open"),
    dirtyCalls: dirtyArguments.length,
    statuses: [...statusMessages],
    focusedElement: document.activeElement?.name || "",
};

openRecipeImagePromptModal(trigger);
drainAnimationFrames();
const reopenedDraft = draft.value;
draft.value = "  Replacement prompt\nSecond line  ";
const saveReturnValue = saveRecipeImagePrompt();

process.stdout.write(JSON.stringify({
    bodyLockedBeforeCancel,
    cancelReturnValue,
    afterCancel,
    reopenedDraft,
    saveReturnValue,
    afterSave: {
        prompt: promptText.textContent,
        modalHidden: modal.hidden,
        bodyLocked: bodyClasses.has("recipe-image-prompt-modal-open"),
        listenerRegistered: listeners.has("keydown"),
        dirtyArguments,
        statuses: statusMessages,
        focusedElement: document.activeElement?.name || "",
        triggerFocusOptions: trigger.lastFocusOptions,
    },
}));
"""
    )

    assert result == {
        "bodyLockedBeforeCancel": True,
        "cancelReturnValue": False,
        "afterCancel": {
            "prompt": "Existing saved prompt",
            "modalHidden": True,
            "bodyLocked": False,
            "dirtyCalls": 0,
            "statuses": [],
            "focusedElement": "trigger",
        },
        "reopenedDraft": "Existing saved prompt",
        "saveReturnValue": False,
        "afterSave": {
            "prompt": "Replacement prompt\nSecond line",
            "modalHidden": True,
            "bodyLocked": False,
            "listenerRegistered": False,
            "dirtyArguments": [True],
            "statuses": ["Image prompt updated. Save Recipe to keep this change."],
            "focusedElement": "trigger",
            "triggerFocusOptions": {"preventScroll": True},
        },
    }
