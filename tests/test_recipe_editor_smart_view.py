import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html"
SCRIPT_PATH = ROOT / "PushShoppingList/static/js/app.js"
CSS_PATH = ROOT / "PushShoppingList/static/css/app.css"


def _function(script, name, next_name):
    start = script.index(f"function {name}")
    end = script.index(f"function {next_name}", start)
    return script[start:end]


def _css_rule(css, selector, start=0):
    rule_start = css.index(selector, start)
    declaration_start = css.index("{", rule_start)
    rule_end = css.index("\n}", declaration_start)
    return css[rule_start:rule_end]


def test_smart_view_replaces_the_placeholder_and_reuses_shared_actions():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    ingredient_start = template.index('id="recipeEditPanelIngredients"')
    ingredient_end = template.index('id="recipeEditPanelEquipment"', ingredient_start)
    ingredient_section = template[ingredient_start:ingredient_end]
    render = _function(
        script,
        "renderRecipeIngredientSmartView()",
        "toggleRecipeIngredientSmartView",
    )
    edit = _function(
        script,
        "editRecipeIngredientFromSmartView(button)",
        "toggleRecipeIngredientRecipeView",
    )

    assert "Smart View will be implemented in Phase 3." not in ingredient_section
    assert 'data-recipe-ingredient-view-panel="smart"' in ingredient_section
    assert 'role="list"' in ingredient_section
    assert "data-recipe-ingredient-smart-grid" in ingredient_section
    assert "data-recipe-ingredient-smart-empty" in ingredient_section
    assert ingredient_section.count("data-recipe-ingredient-smart-add") == 1
    assert ingredient_section.count("addRecipeIngredientFromCurrentView()") == 6

    assert "recipeEditIngredientRows().flatMap(row =>" in render
    assert "fieldValuesFromRow(row)" in render
    assert "recipeIngredientSubstitutionDomGroups(" in render
    assert "recipeIngredientSmartViewEntries(row, values, alternativeGroups)" in render
    assert "existingCards.get(key)" in render
    assert "grid.appendChild(card)" in render
    assert "fetch(" not in render
    assert "smartViewIngredients" not in script

    assert "card?.recipeIngredientSourceRow" in edit
    assert 'setRecipeEditIngredientView("table", { persist: false });' in edit
    assert "setRecipeIngredientEditMode(row, true, { trigger: button })" in edit
    assert "function addRecipeIngredientFromCurrentView()" in script
    assert "return addRecipeIngredientRow({}, { expanded: true });" in script


def test_smart_cards_reuse_images_status_store_sections_and_structured_options():
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    image = _function(
        script,
        "syncRecipeIngredientSmartViewImage(imageCell, values = {})",
        "createRecipeIngredientSmartViewCard",
    )
    card = _function(
        script,
        "renderRecipeIngredientSmartViewCard(",
        "layoutRecipeIngredientSmartView",
    )
    options = _function(
        script,
        "renderRecipeIngredientSmartViewOptions(",
        "renderRecipeIngredientSmartViewDetails",
    )
    details = _function(
        script,
        "renderRecipeIngredientSmartViewDetails(",
        "syncRecipeIngredientSmartViewCardExpanded",
    )

    assert "recipeIngredientImageUrl(values)" in image
    assert 'recipeImageVariantUrl(imageUrl, "thumb")' in image
    assert "recipeImageVariantSrcSet(imageUrl)" in image
    assert "handleRecipeIngredientSmartViewImageError(image)" in image
    assert "handleRecipeIngredientReadImageError(image)" in script
    assert "initDeferredImages(imageCell)" in image
    assert 'image.alt = "";' in image
    assert "image.sizes = `${recipeImageThumbnailSize}px`;" in image

    assert "choiceParentValues" in card
    assert "choiceAlternativeGroups" in card
    assert "recipeIngredientRecipeViewChoiceGroups(" in card
    assert "recipeIngredientChoiceItemSummary(" in card
    assert "recipeIngredientViewName(values, choice.groups.length > 0)" in card
    assert "recipeIngredientViewAmount(values)" in card
    assert "recipeIngredientRecipeViewStatus(sourceRow, values)" in card
    assert "status.hidden = !statusDetails;" in card
    assert 'optionCount.textContent = choice.groups.length ? choice.summary.label : "";' in card
    assert "renderRecipeIngredientRecipeViewStore(" in card

    assert 'const defaultGroups = choiceGroups.filter(group => group.isDefaultOption);' in options
    assert 'const alternativeChoiceGroups = choiceGroups.filter(group => !group.isDefaultOption);' in options
    assert "group.values.forEach(values =>" in script
    assert "recipeIngredientChoiceItemSummary(" in script
    assert "recipeIngredientViewAmount(values)" in script
    assert 'label: "Default"' in options
    assert 'label: `Alternatives (${alternativeChoiceGroups.length})`' in options

    assert '"Buy As"' in details
    assert "recipeIngredientViewMeaningfulBuyAs(" in details
    assert "recipeIngredientRecipeViewName(values, true)" in details
    assert '"Store Section"' in details
    assert "recipeIngredientStoreSectionIconHtml(storeSection)" in details
    assert '"Preparation"' in details
    assert '"Type"' in details
    assert "recipeIngredientTypeLabel(values)" in details
    assert 'notes || "Click to add notes\\u2026"' in details


def test_smart_thumbnail_layout_is_variable_driven_and_keeps_interface_icons_fixed():
    css = CSS_PATH.read_text(encoding="utf-8")
    smart_css = css[css.index("Ingredient editor v82:"):css.index("Ingredient editor v83:")]
    mobile_css = smart_css[smart_css.index("@media (max-width: 760px)"):]
    desktop_header = _css_rule(
        smart_css,
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-smart-header",
    )
    mobile_header = _css_rule(
        mobile_css,
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-smart-header",
    )
    image_rule = _css_rule(
        smart_css,
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-smart-image {",
    )

    assert "calc(var(--recipe-edit-thumbnail-size, 64px) + 2px)" in desktop_header
    assert "max(78px, calc(var(--recipe-edit-thumbnail-size, 64px) + 22px))" in desktop_header
    assert "width: var(--recipe-edit-thumbnail-size, 64px);" in image_rule
    assert "height: var(--recipe-edit-thumbnail-size, 64px);" in image_rule
    assert "calc(var(--recipe-edit-thumbnail-size, 64px) + 2px)" in mobile_header
    assert "60px" not in desktop_header + image_rule
    assert "54px" not in mobile_header

    fallback_icon = _css_rule(
        smart_css,
        "> .recipe-edit-substitution-image-fallback :is(.recipe-edit-inline-icon, svg)",
    )
    action_buttons = _css_rule(
        smart_css,
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-smart-edit,",
    )
    action_icons = _css_rule(
        smart_css,
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-smart-edit .recipe-edit-inline-icon,",
    )
    store_icons = _css_rule(
        smart_css,
        ".recipe-edit-store-section-icon {",
    )
    detail_icons = _css_rule(
        smart_css,
        ":is(.recipe-edit-store-section-icon, .recipe-edit-inline-icon, svg)",
    )
    option_marker = _css_rule(
        smart_css,
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-smart-option-marker {",
    )
    option_marker_icon = _css_rule(
        smart_css,
        ".recipe-edit-ingredient-smart-option-marker\n    .recipe-edit-inline-icon",
    )

    assert "width: 22px;" in fallback_icon and "height: 22px;" in fallback_icon
    assert "width: 34px;" in action_buttons and "height: 34px;" in action_buttons
    assert "width: 15px;" in action_icons and "height: 15px;" in action_icons
    assert "width: 12px;" in store_icons and "height: 12px;" in store_icons
    assert "width: 13px;" in detail_icons and "height: 13px;" in detail_icons
    assert "width: 14px;" in option_marker and "height: 14px;" in option_marker
    assert "width: 10px;" in option_marker_icon and "height: 10px;" in option_marker_icon
    for fixed_icon_rule in (
        fallback_icon,
        action_buttons,
        action_icons,
        store_icons,
        detail_icons,
        option_marker,
        option_marker_icon,
    ):
        assert "--recipe-edit-thumbnail-size" not in fixed_icon_rule


def test_smart_thumbnail_setting_updates_image_hints_persists_and_relayouts():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Smart thumbnail runtime regression")

    normalize = _function(
        script,
        "normalizeRecipeImageThumbnailSize(value)",
        "rememberedRecipeImageThumbnailSize",
    )
    schedule = _function(
        script,
        "scheduleRecipeIngredientSmartViewLayout()",
        "initRecipeIngredientSmartViewLayout",
    )
    apply_size = _function(
        script,
        "applyRecipeImageThumbnailSize(size, options = {})",
        "initRecipeImageThumbnailSizeControls",
    )
    reset_size = _function(
        script,
        "resetRecipeImageThumbnailSize(button)",
        "recipeImageProviderFieldHtml",
    )
    harness = r"""
const RECIPE_IMAGE_THUMBNAIL_SIZE_STORAGE_KEY = "recipe-image-thumbnail-size";
const RECIPE_IMAGE_THUMBNAIL_DEFAULT_SIZE = 64;
const RECIPE_IMAGE_THUMBNAIL_MIN_SIZE = 32;
const RECIPE_IMAGE_THUMBNAIL_MAX_SIZE = 80;
const RECIPE_IMAGE_THUMBNAIL_STEP_SIZE = 8;
let recipeImageThumbnailSize = RECIPE_IMAGE_THUMBNAIL_DEFAULT_SIZE;
let recipeEditIngredientSmartViewLayoutFrame = 0;
let layoutCount = 0;
let nextFrameId = 0;
const frames = [];
const styleValues = {};
const storageWrites = [];
const smartImages = [{ sizes: "64px" }, { sizes: "64px" }];
const recipeViewImage = { sizes: "120px" };
const equipmentImage = { sizes: "120px" };
const instructionImage = { sizes: "(max-width: 900px) 92vw, 720px" };
const labels = [{ textContent: "64px" }, { textContent: "64px" }];
const decreaseButtons = [{ disabled: false }];
const increaseButtons = [{ disabled: false }];
const window = {
    requestAnimationFrame(callback) {
        frames.push(callback);
        nextFrameId += 1;
        return nextFrameId;
    },
    localStorage: {
        setItem(key, value) { storageWrites.push([key, value]); },
    },
};
const document = {
    documentElement: {
        style: {
            setProperty(name, value) { styleValues[name] = value; },
        },
    },
    querySelectorAll(selector) {
        if (selector === ".recipe-edit-ingredient-smart-image > img") return smartImages;
        if (selector === "[data-recipe-thumbnail-size-value]") return labels;
        if (selector === "[data-recipe-thumbnail-size-decrease]") return decreaseButtons;
        if (selector === "[data-recipe-thumbnail-size-increase]") return increaseButtons;
        throw new Error(`Unexpected selector: ${selector}`);
    },
};
function layoutRecipeIngredientSmartView() {
    recipeEditIngredientSmartViewLayoutFrame = 0;
    layoutCount += 1;
}
function updateRecipeImageThumbnailSizeControls(size = recipeImageThumbnailSize) {
    document.querySelectorAll("[data-recipe-thumbnail-size-value]").forEach(label => {
        label.textContent = `${size}px`;
    });
    document.querySelectorAll("[data-recipe-thumbnail-size-decrease]").forEach(button => {
        button.disabled = size <= RECIPE_IMAGE_THUMBNAIL_MIN_SIZE;
    });
    document.querySelectorAll("[data-recipe-thumbnail-size-increase]").forEach(button => {
        button.disabled = size >= RECIPE_IMAGE_THUMBNAIL_MAX_SIZE;
    });
}
function drainFrame() {
    const callback = frames.shift();
    if (!callback) throw new Error("Expected a scheduled Smart-grid layout frame");
    callback();
}
""" + normalize + schedule + apply_size + reset_size + r"""

const states = [];
applyRecipeImageThumbnailSize(32, { persist: true });
states.push({
    size: recipeImageThumbnailSize,
    imageSizes: smartImages.map(image => image.sizes),
    label: labels[0].textContent,
    decreaseDisabled: decreaseButtons[0].disabled,
    increaseDisabled: increaseButtons[0].disabled,
    queuedLayouts: frames.length,
});
drainFrame();

applyRecipeImageThumbnailSize(80, { persist: true });
states.push({
    size: recipeImageThumbnailSize,
    imageSizes: smartImages.map(image => image.sizes),
    label: labels[0].textContent,
    decreaseDisabled: decreaseButtons[0].disabled,
    increaseDisabled: increaseButtons[0].disabled,
    queuedLayouts: frames.length,
});
drainFrame();

resetRecipeImageThumbnailSize();
states.push({
    size: recipeImageThumbnailSize,
    imageSizes: smartImages.map(image => image.sizes),
    label: labels[0].textContent,
    decreaseDisabled: decreaseButtons[0].disabled,
    increaseDisabled: increaseButtons[0].disabled,
    queuedLayouts: frames.length,
});
drainFrame();

process.stdout.write(JSON.stringify({
    states,
    styleValues,
    storageWrites,
    layoutCount,
    otherImageSizes: [recipeViewImage.sizes, equipmentImage.sizes, instructionImage.sizes],
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["states"] == [
        {
            "size": 32,
            "imageSizes": ["32px", "32px"],
            "label": "32px",
            "decreaseDisabled": True,
            "increaseDisabled": False,
            "queuedLayouts": 1,
        },
        {
            "size": 80,
            "imageSizes": ["80px", "80px"],
            "label": "80px",
            "decreaseDisabled": False,
            "increaseDisabled": True,
            "queuedLayouts": 1,
        },
        {
            "size": 64,
            "imageSizes": ["64px", "64px"],
            "label": "64px",
            "decreaseDisabled": False,
            "increaseDisabled": False,
            "queuedLayouts": 1,
        },
    ]
    assert result["styleValues"] == {
        "--recipe-edit-thumbnail-size": "64px",
        "--recipe-edit-thumbnail-slot": "66px",
    }
    assert result["storageWrites"] == [
        ["recipe-image-thumbnail-size", "32"],
        ["recipe-image-thumbnail-size", "80"],
        ["recipe-image-thumbnail-size", "64"],
    ]
    assert result["layoutCount"] == 3
    assert result["otherImageSizes"] == [
        "120px",
        "120px",
        "(max-width: 900px) 92vw, 720px",
    ]


def test_smart_collapsed_cards_prioritize_units_sizes_and_actionable_statuses():
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    amount = _function(
        script,
        "recipeIngredientViewAmount(values = {})",
        "recipeIngredientViewPluralName",
    )
    name = _function(
        script,
        "recipeIngredientViewName(values = {}, hasChoices = false)",
        "recipeIngredientViewMeaningfulBuyAs",
    )
    buy_as = _function(
        script,
        'recipeIngredientViewMeaningfulBuyAs(values = {}, displayName = "")',
        "syncRecipeIngredientSmartViewImage",
    )

    assert "const quantityText = normalizeQuantityFractionText(values.quantity_text);" in amount
    assert "const quantity = normalizeQuantityFractionText(values.quantity || values.amount);" in amount
    assert 'const size = String(values.size || "").trim();' in amount
    assert 'const unit = String(values.unit || "").trim();' in amount
    assert "quantityNumber > 1" in amount
    assert 'return [amount, ...details].filter(Boolean).join(" ");' in amount

    assert "recipeIngredientViewNamesDifferOnlyByCount(name, buyAs)" in name
    assert "quantityNumber > 1" in name
    assert "return buyAs;" in name
    assert "recipeIngredientViewNamesDifferOnlyByCount(ingredient, buyAs)" in buy_as
    assert 'String(values.ingredient || displayName || "").trim()' in buy_as


def test_recipe_view_phone_rows_consolidate_metadata_and_preparation():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    create = _function(
        script,
        "createRecipeIngredientRecipeViewItem(row)",
        "renderRecipeIngredientRecipeViewSecondary",
    )
    render = _function(
        script,
        "renderRecipeIngredientRecipeViewItem(item, row, values, alternativeGroups)",
        "renderRecipeIngredientRecipeView()",
    )
    mobile_css = css[css.index("Ingredient editor v91:"):]

    assert "data-recipe-view-name-primary" in create
    assert "data-recipe-view-preparation" in create
    assert "data-recipe-view-metadata" in create
    assert "showSeparatePreparation" in render
    assert 'metadata.querySelector(":scope > :not([hidden])")' in render
    assert "grid-template-columns: 82px minmax(0, 1fr) 34px;" in mobile_css
    assert "white-space: normal;" in mobile_css
    assert ".recipe-edit-ingredient-recipe-item.has-choices" in mobile_css
    assert ".recipe-edit-ingredient-recipe-secondary:not([hidden])" in mobile_css
    assert ".recipe-edit-ingredient-recipe-metadata:not([hidden])" in mobile_css
    assert "grid-column: 2 / -1;" in mobile_css
    assert 'content: "\\00b7  ";' in mobile_css


def test_smart_expansion_is_single_stable_view_only_state_and_accessible():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    toggle = _function(
        script,
        "toggleRecipeIngredientSmartView(button)",
        "editRecipeIngredientFromSmartView",
    )
    expanded = _function(
        script,
        "syncRecipeIngredientSmartViewCardExpanded(card, expanded)",
        "renderRecipeIngredientSmartViewCard",
    )
    layout = _function(
        script,
        "layoutRecipeIngredientSmartView()",
        "scheduleRecipeIngredientSmartViewLayout",
    )

    assert 'let recipeEditExpandedSmartViewIngredientId = "";' in script
    assert "recipeEditExpandedSmartViewIngredientId !== key" in toggle
    assert "syncRecipeIngredientSmartViewCardExpanded(openCard, false);" in toggle
    assert "recipeEditExpandedSmartViewIngredientId = shouldExpand ? key : \"\";" in toggle
    assert "toggleRecipeIngredientExpansionWithAnchor(" in toggle
    assert toggle.index("toggleRecipeIngredientExpansionWithAnchor(") < toggle.index(
        "const shouldExpand"
    )
    assert toggle.index("const shouldExpand") < toggle.index(
        "scheduleRecipeIngredientSmartViewLayout();"
    )
    assert "updateRecipeEditorDirtyState" not in toggle
    assert "scrollIntoView" not in toggle
    assert "scrollTop" not in toggle

    assert 'disclosure.setAttribute("aria-expanded", String(expanded));' in expanded
    assert 'disclosure.setAttribute("aria-controls", details?.id || "");' in expanded
    assert '${expanded ? "Collapse" : "Expand"} ${name || "ingredient"} details' in expanded
    assert 'edit.setAttribute("aria-label", `Edit ${name}`);' in script

    assert "const columnCount = width >= 700 ? 2 : 1;" in layout
    assert "index % 2" in layout
    assert "card.style.gridRow = `${start} / span ${height}`;" in layout
    assert ".recipe-edit-ingredient-smart-grid" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert '.recipe-edit-ingredient-smart-grid[data-smart-columns="1"]' in css
    assert ".recipe-edit-ingredient-smart-card.is-expanded" in css
    assert ".recipe-edit-ingredient-smart-disclosure:focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_smart_expansion_preserves_the_clicked_card_through_masonry_scroll_clamping():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Smart View scroll-anchor regression")

    scroll_helpers_start = script.index("function recipeIngredientScrollMaximum")
    scroll_helpers_end = script.index(
        "function setRecipeIngredientSubstitutionsExpanded",
        scroll_helpers_start,
    )
    scroll_helpers = script[scroll_helpers_start:scroll_helpers_end]
    schedule = _function(
        script,
        "scheduleRecipeIngredientSmartViewLayout()",
        "initRecipeIngredientSmartViewLayout",
    )
    toggle = _function(
        script,
        "toggleRecipeIngredientSmartView(button)",
        "selectRecipeIngredientSmartViewOption",
    )
    harness = r"""
const recipeEditIngredientScrollReserveStates = new WeakMap();
let recipeEditExpandedSmartViewIngredientId = "";
let recipeEditIngredientSmartViewLayoutFrame = 0;
let nextFrameId = 1;
let clampCount = 0;
let expectedAnchorRow = null;
let expectedAnchorControl = null;
const queuedFrames = [];
const queuedFrameKinds = [];

const document = {
    createElement() {
        return {
            className: "",
            dataset: {},
            parentElement: null,
            style: {
                height: "",
                removeProperty(name) {
                    if (name === "height") this.height = "";
                },
            },
            setAttribute() {},
            remove() {
                const parent = this.parentElement;
                if (!parent) return;
                if (parent.spacer === this) parent.spacer = null;
                this.parentElement = null;
            },
        };
    },
};
const window = {
    requestAnimationFrame(callback) {
        const id = nextFrameId++;
        queuedFrameKinds.push(
            callback === layoutRecipeIngredientSmartView ? "layout" : "anchor",
        );
        queuedFrames.push({ id, callback });
        return id;
    },
    cancelAnimationFrame(id) {
        const index = queuedFrames.findIndex(frame => frame.id === id);
        if (index >= 0) queuedFrames.splice(index, 1);
    },
    scrollBy() {
        throw new Error("Smart View should use its element scroll container");
    },
};
const scrollContainer = {
    baseScrollHeight: 600,
    clientHeight: 500,
    _scrollTop: 100,
    spacer: null,
    isConnected: true,
    classList: {
        values: new Set(),
        add(value) { this.values.add(value); },
        remove(value) { this.values.delete(value); },
    },
    get scrollHeight() {
        return this.baseScrollHeight
            + Number.parseFloat(this.spacer?.style.height || "0");
    },
    get scrollTop() {
        const maximum = Math.max(0, this.scrollHeight - this.clientHeight);
        if (this._scrollTop > maximum) {
            this._scrollTop = maximum;
            clampCount += 1;
        }
        return this._scrollTop;
    },
    set scrollTop(value) {
        const maximum = Math.max(0, this.scrollHeight - this.clientHeight);
        this._scrollTop = Math.min(maximum, Math.max(0, Number(value) || 0));
    },
    addEventListener() {},
    appendChild(element) {
        this.spacer = element;
        element.parentElement = this;
    },
};
const grid = {
    querySelector() {
        return card.expanded ? card : null;
    },
};
const card = {
    dataset: { smartViewIngredientId: "onion" },
    parentElement: grid,
    isConnected: true,
    expanded: false,
    documentTop: 570,
    classList: {
        contains(name) {
            return name === "is-expanded" && card.expanded;
        },
    },
    closest() { return null; },
    getBoundingClientRect() {
        return { top: this.documentTop - scrollContainer.scrollTop };
    },
};
const button = {
    closest() { return card; },
};

function recipeIngredientExpansionViewportAnchor(row, control) {
    expectedAnchorRow = row;
    expectedAnchorControl = control;
    return row;
}
function recipeIngredientVerticalScrollContainer() { return scrollContainer; }
function syncRecipeIngredientSmartViewCardExpanded(target, expanded) {
    target.expanded = expanded;
    scrollContainer.baseScrollHeight = expanded ? 1000 : 650;
}
function layoutRecipeIngredientSmartView() {
    recipeEditIngredientSmartViewLayoutFrame = 0;
    scrollContainer.baseScrollHeight = card.expanded ? 1000 : 600;
    card.documentTop = card.expanded ? 620 : 570;
}
function drainAnimationFrames() {
    while (queuedFrames.length) {
        const frame = queuedFrames.shift();
        frame.callback();
    }
}
""" + scroll_helpers + schedule + toggle + r"""

const collapsedTop = card.getBoundingClientRect().top;
toggleRecipeIngredientSmartView(button);
drainAnimationFrames();
const expandQueue = queuedFrameKinds.splice(0);
const expandedTop = card.getBoundingClientRect().top;

// Match the reported failure: scroll to the native maximum before collapsing
// a lower card, then let the content shrink and clamp scrollTop synchronously.
scrollContainer.scrollTop = 500;
const beforeCollapseTop = card.getBoundingClientRect().top;
toggleRecipeIngredientSmartView(button);
drainAnimationFrames();
const collapseQueue = queuedFrameKinds.splice(0);
const afterCollapseTop = card.getBoundingClientRect().top;
const reserveState = recipeEditIngredientScrollReserveStates.get(scrollContainer);

process.stdout.write(JSON.stringify({
    anchorRowIsCard: expectedAnchorRow === card,
    anchorControlIsButton: expectedAnchorControl === button,
    expandQueue,
    collapseQueue,
    collapsedTop,
    expandedTop,
    beforeCollapseTop,
    afterCollapseTop,
    clampCount,
    reserveHeight: reserveState?.height || 0,
    stabilizing: scrollContainer.classList.values.has(
        "recipe-edit-ingredient-scroll-stabilizing",
    ),
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["anchorRowIsCard"] is True
    assert result["anchorControlIsButton"] is True
    assert result["expandQueue"][:2] == ["layout", "anchor"]
    assert result["collapseQueue"][:2] == ["layout", "anchor"]
    assert abs(result["expandedTop"] - result["collapsedTop"]) <= 0.5
    assert abs(result["afterCollapseTop"] - result["beforeCollapseTop"]) <= 0.5
    assert result["clampCount"] >= 1
    assert result["reserveHeight"] > 0
    assert result["stabilizing"] is False


def test_smart_projection_refreshes_with_row_edits_and_reordering():
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    summary = _function(
        script,
        "updateRecipeIngredientSummary(row)",
        "recipeEditIngredientRows",
    )
    indexes = _function(
        script,
        "updateRecipeIngredientRowIndexes()",
        "toggleRecipeEditRowMenu",
    )
    actions = _function(
        script,
        "syncRecipeEditIngredientViewActions(section, view)",
        "recipeIngredientRecipeViewAmount",
    )

    assert "renderRecipeIngredientRecipeView();" in summary
    assert "renderRecipeIngredientSmartView();" in summary
    assert "renderRecipeIngredientRecipeView();" in indexes
    assert "renderRecipeIngredientSmartView();" in indexes
    assert 'action.hidden = view !== "table";' in actions
    assert 'const tableIsActive = view === "table";' in actions


def test_smart_view_projects_the_selected_choice_components_as_main_cards():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Smart View projection regression")

    projection = _function(
        script,
        "recipeIngredientSmartViewEntries(row, values, alternativeGroups)",
        "layoutRecipeIngredientSmartView",
    )
    assert "showChoiceControls: true" in projection
    assert "showChoiceControls: componentIndex === 0" not in projection
    selected_rows = _function(
        script,
        "recipeIngredientSelectedOptionProjectionRows(selectedChoice)",
        "syncRecipeIngredientSelectedOptionLineItems",
    )
    harness = """
const parentRow = { id: "corn-choice" };
const components = [
    { id: "fresh-corn", values: { ingredient: "corn", preparation: "fresh" } },
    { id: "cumin", values: { ingredient: "cumin" } },
    { id: "onion", values: { ingredient: "onion" } },
];
let selectedRows = components;
function ensureRecipeIngredientExpansionId() { return "ingredient-corn"; }
function recipeIngredientRecipeViewChoiceGroups() {
    return { selectedChoice: { rows: selectedRows } };
}
function fieldValuesFromRow(row) { return row.values; }
""" + selected_rows + projection + """

const projected = recipeIngredientSmartViewEntries(
    parentRow,
    { ingredient: "corn", preparation: "fresh" },
    [{ alternativeId: "fresh", rows: components }],
);
selectedRows = [components[0]];
const singleComponent = recipeIngredientSmartViewEntries(
    parentRow,
    { ingredient: "corn", preparation: "fresh" },
    [{ alternativeId: "fresh", rows: components }],
);
process.stdout.write(JSON.stringify({
    projected: projected.map(entry => ({
        key: entry.key,
        source: entry.sourceRow.id,
        ingredient: entry.values.ingredient,
        showChoiceControls: entry.showChoiceControls,
        projected: entry.isProjectedChoiceComponent,
    })),
    singleComponent: singleComponent.map(entry => ({
        key: entry.key,
        source: entry.sourceRow.id,
        projected: entry.isProjectedChoiceComponent,
    })),
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "projected": [
            {
                "key": "ingredient-corn",
                "source": "fresh-corn",
                "ingredient": "corn",
                "showChoiceControls": True,
                "projected": True,
            },
            {
                "key": "ingredient-corn:selected-choice-component:1",
                "source": "cumin",
                "ingredient": "cumin",
                "showChoiceControls": True,
                "projected": True,
            },
            {
                "key": "ingredient-corn:selected-choice-component:2",
                "source": "onion",
                "ingredient": "onion",
                "showChoiceControls": True,
                "projected": True,
            },
        ],
        "singleComponent": [
            {
                "key": "ingredient-corn",
                "source": "corn-choice",
                "projected": False,
            },
        ],
    }


def test_smart_view_switching_choices_replaces_stale_projected_cards():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Smart View switching regression")

    projection = _function(
        script,
        "recipeIngredientSmartViewEntries(row, values, alternativeGroups)",
        "layoutRecipeIngredientSmartView",
    )
    selected_rows = _function(
        script,
        "recipeIngredientSelectedOptionProjectionRows(selectedChoice)",
        "syncRecipeIngredientSelectedOptionLineItems",
    )
    render = _function(
        script,
        "renderRecipeIngredientSmartView()",
        "toggleRecipeIngredientSmartView",
    )
    harness = """
const freshRows = [
    { id: "fresh-corn", values: { ingredient: "corn", preparation: "fresh" } },
    { id: "cumin", values: { ingredient: "cumin", preparation: "" } },
    { id: "fresh-onion", values: { ingredient: "onion", preparation: "" } },
];
const frozenRows = [
    { id: "frozen-corn", values: { ingredient: "corn", preparation: "frozen" } },
    { id: "frozen-onion", values: { ingredient: "onion", preparation: "" } },
];
const parentRow = {
    id: "corn-choice",
    values: { ingredient: "corn", preparation: "fresh" },
    querySelectorAll() { return [...freshRows, ...frozenRows]; },
};
const groups = [
    { alternativeId: "fresh", rows: freshRows },
    { alternativeId: "frozen", rows: frozenRows },
];
let selectedRows = freshRows;
let recipeEditExpandedSmartViewIngredientId = "";
let createdCardCount = 0;
const removedKeys = [];
const grid = {
    children: [],
    hidden: false,
    appendChild(card) {
        const currentIndex = this.children.indexOf(card);
        if (currentIndex >= 0) this.children.splice(currentIndex, 1);
        this.children.push(card);
        card.parentElement = this;
        card.isConnected = true;
    },
};
const empty = { hidden: true };
const add = { hidden: false };
const document = {
    querySelector(selector) {
        if (selector === "[data-recipe-ingredient-smart-grid]") return grid;
        if (selector === "[data-recipe-ingredient-smart-empty]") return empty;
        if (selector === "[data-recipe-ingredient-smart-add]") return add;
        return null;
    },
};
function ensureRecipeIngredientExpansionId() { return "ingredient-corn"; }
function recipeIngredientRecipeViewChoiceGroups() {
    return { selectedChoice: { rows: selectedRows } };
}
function fieldValuesFromRow(row) { return row.values; }
function recipeEditIngredientRows() { return [parentRow]; }
function recipeIngredientSubstitutionDomGroups() { return groups; }
function recipeIngredientRecipeViewHasContent() { return true; }
function createRecipeIngredientSmartViewCard() {
    createdCardCount += 1;
    return {
        dataset: {},
        isConnected: true,
        remove() {
            removedKeys.push(this.dataset.smartViewIngredientId);
            const index = grid.children.indexOf(this);
            if (index >= 0) grid.children.splice(index, 1);
            this.isConnected = false;
        },
    };
}
function renderRecipeIngredientSmartViewCard(card, row, values, alternatives, options) {
    card.dataset.smartViewIngredientId = options.key;
    card.renderedIngredient = values.ingredient;
    card.renderedPreparation = values.preparation || "";
    card.recipeIngredientSourceRow = options.sourceRow;
}
function initRecipeIngredientSmartViewLayout() {}
function scheduleRecipeIngredientSmartViewLayout() {}
""" + selected_rows + projection + render + """

function snapshot() {
    return grid.children.map(card => ({
        key: card.dataset.smartViewIngredientId,
        ingredient: card.renderedIngredient,
        preparation: card.renderedPreparation,
        source: card.recipeIngredientSourceRow.id,
    }));
}
renderRecipeIngredientSmartView();
const fresh = snapshot();
selectedRows = frozenRows;
renderRecipeIngredientSmartView();
const frozen = snapshot();
selectedRows = freshRows;
renderRecipeIngredientSmartView();
const freshAgain = snapshot();
process.stdout.write(JSON.stringify({
    fresh,
    frozen,
    freshAgain,
    removedKeys,
    createdCardCount,
    canonicalRowCount: recipeEditIngredientRows().length,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert [item["source"] for item in result["fresh"]] == [
        "fresh-corn",
        "cumin",
        "fresh-onion",
    ]
    assert [item["source"] for item in result["frozen"]] == [
        "frozen-corn",
        "frozen-onion",
    ]
    assert [item["source"] for item in result["freshAgain"]] == [
        "fresh-corn",
        "cumin",
        "fresh-onion",
    ]
    assert len({item["key"] for item in result["fresh"]}) == 3
    assert len({item["key"] for item in result["frozen"]}) == 2
    assert result["removedKeys"] == [
        "ingredient-corn:selected-choice-component:2",
    ]
    assert result["createdCardCount"] == 4
    assert result["canonicalRowCount"] == 1


def test_smart_option_sets_select_through_shared_choice_state_and_support_keyboard():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    option = _function(
        script,
        "createRecipeIngredientSmartViewOption(",
        "renderRecipeIngredientSmartViewOptions",
    )
    details = _function(
        script,
        "renderRecipeIngredientSmartViewDetails(",
        "syncRecipeIngredientSmartViewCardExpanded",
    )
    select = _function(
        script,
        "selectRecipeIngredientSmartViewOption(button, event = null)",
        "navigateRecipeIngredientSmartViewOptions",
    )
    keyboard = _function(
        script,
        "navigateRecipeIngredientSmartViewOptions(button, event)",
        "editRecipeIngredientFromSmartView",
    )
    apply_selection = _function(
        script,
        "applyRecipeIngredientOptionSelection(ingredientRow, optionId)",
        "setRecipeIngredientOptionSelected",
    )
    choice_groups = _function(
        script,
        "recipeIngredientRecipeViewChoiceGroups(row, parentValues, alternativeGroups)",
        "createRecipeIngredientRecipeViewItem",
    )
    shared_mutation = _function(
        script,
        "setRecipeIngredientDefaultOption(row, alternativeGroups, optionId, selectedGroupIndex = -1)",
        "createRecipeIngredientDefaultOptionSummary",
    )

    assert 'document.createElement("button")' in option
    assert 'option.setAttribute("role", "radio")' in option
    assert 'option.setAttribute("aria-checked", String(Boolean(group.isSelected)))' in option
    assert "group.values.forEach(values =>" in option
    assert 'option.addEventListener("click"' in option
    assert 'option.addEventListener("keydown"' in option
    assert 'optionList.setAttribute("role", "radiogroup")' in details

    assert "card?.recipeIngredientChoiceParentRow" in select
    assert "card?.recipeIngredientSourceRow" in select
    assert "applyRecipeIngredientOptionSelection(row, optionId)" in select
    assert 'setRecipeEditStatus("Ingredient option selected. Save Recipe to keep it.")' in select
    assert 'selectedOption?.focus({ preventScroll: true });' in select
    assert 'event.key === "Enter" || event.key === " "' in keyboard
    for key in ("ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"):
        assert key in keyboard

    assert "recipeIngredientSubstitutionDomGroups(" in apply_selection
    assert "group => group.alternativeId === normalizedOptionId" in apply_selection
    assert "setRecipeIngredientDefaultOption(" in apply_selection
    assert "group.rows.every(optionRow =>" in apply_selection
    assert 'String(value.option_type || "").trim() === "original"' in choice_groups
    assert "recipeIngredientMatchFlag(value.is_default)" not in choice_groups
    assert "updateRecipeIngredientSubstitutionState(row);" in shared_mutation
    assert "updateRecipeIngredientSummary(row);" in shared_mutation
    assert "updateRecipeEditorDirtyState();" in shared_mutation
    assert "smartViewIngredients" not in select
    assert ".recipe-edit-ingredient-smart-option:focus-visible" in css


def test_smart_choice_focus_moves_to_surviving_component_when_selection_shrinks():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Smart View focus regression")

    select = _function(
        script,
        "selectRecipeIngredientSmartViewOption(button, event = null)",
        "navigateRecipeIngredientSmartViewOptions",
    )
    harness = """
const row = { id: "corn-choice", isConnected: true, values: { ingredient: "corn" } };
const oldOnionRow = { id: "fresh-onion", values: { ingredient: "onion" } };
const frozenCornRow = { id: "frozen-corn", values: { ingredient: "corn" } };
const frozenOnionRow = { id: "frozen-onion", values: { ingredient: "onion" } };
let focusedCard = "";
let expandedCard = "";
let layoutCount = 0;
let statusText = "";
let recipeEditExpandedSmartViewIngredientId = "";
function makeCard(key, sourceRow, expanded = false) {
    const state = { expanded };
    const option = {
        dataset: { smartViewOptionId: "frozen" },
        focus() { focusedCard = key; },
    };
    return {
        dataset: { smartViewIngredientId: key },
        recipeIngredientChoiceParentRow: row,
        recipeIngredientSourceRow: sourceRow,
        isConnected: true,
        classList: {
            contains(name) { return name === "is-expanded" && state.expanded; },
        },
        querySelectorAll() { return [option]; },
        setExpanded(value) { state.expanded = value; },
    };
}
const oldCard = makeCard("ingredient-corn:selected-choice-component:2", oldOnionRow, true);
const frozenCornCard = makeCard("ingredient-corn", frozenCornRow);
const frozenOnionCard = makeCard(
    "ingredient-corn:selected-choice-component:1",
    frozenOnionRow,
);
const grid = { children: [oldCard] };
const button = {
    dataset: { smartViewOptionId: "frozen" },
    closest() { return oldCard; },
};
const document = {
    querySelector(selector) {
        return selector === "[data-recipe-ingredient-smart-grid]" ? grid : null;
    },
};
const window = { requestAnimationFrame(callback) { callback(); } };
function fieldValuesFromRow(sourceRow) { return sourceRow.values; }
function recipeIngredientComparableText(value) { return String(value || "").trim().toLowerCase(); }
function applyRecipeIngredientOptionSelection() {
    oldCard.isConnected = false;
    grid.children = [frozenCornCard, frozenOnionCard];
    return true;
}
function syncRecipeIngredientSmartViewCardExpanded(card, expanded) {
    card.setExpanded(expanded);
    if (expanded) expandedCard = card.dataset.smartViewIngredientId;
}
function scheduleRecipeIngredientSmartViewLayout() { layoutCount += 1; }
function setRecipeEditStatus(value) { statusText = value; }
""" + select + """

selectRecipeIngredientSmartViewOption(button);
process.stdout.write(JSON.stringify({
    focusedCard,
    expandedCard,
    expandedId: recipeEditExpandedSmartViewIngredientId,
    layoutCount,
    statusText,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "focusedCard": "ingredient-corn:selected-choice-component:1",
        "expandedCard": "ingredient-corn:selected-choice-component:1",
        "expandedId": "ingredient-corn:selected-choice-component:1",
        "layoutCount": 1,
        "statusText": "Ingredient option selected. Save Recipe to keep it.",
    }
