import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import menu_mega_json_service
from PushShoppingList.services import menu_store_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_custom_tag_choices_are_reusable_and_case_insensitive():
    assert cookbook_service.clean_custom_categories(
        ["  Weeknight   Dinners ", "weeknight dinners", "Family Favorites"]
    ) == ["Weeknight Dinners", "Family Favorites"]

    choices = cookbook_service.cookbook_custom_tag_choices({
        "cookbooks": [
            {
                "recipes": [
                    {"custom_categories": ["Family Favorites", "Weeknight Dinners"]},
                    {"custom_categories": ["family favorites", "Freezer Meals"]},
                ]
            }
        ]
    })

    assert choices == ["Family Favorites", "Freezer Meals", "Weeknight Dinners"]


def test_cookbook_category_choices_use_workspace_cuisine_registry(monkeypatch):
    from PushShoppingList.services import cuisine_category_service

    monkeypatch.setattr(
        cuisine_category_service,
        "active_workspace_cuisine_category_labels",
        lambda user_id=None: ["Italian", "  Caribbean  ", "italian", ""],
    )

    choices = cookbook_service.cookbook_category_choices(user_id="cuisine-user")

    assert choices["cuisine"] == ["Italian", "Caribbean"]
    assert choices["meal_type"] == list(cookbook_service.COOKBOOK_CATEGORY_CHOICES["meal_type"])


def test_cookbook_category_choices_keep_safe_cuisine_fallback(monkeypatch):
    from PushShoppingList.services import cuisine_category_service

    def unavailable_registry(user_id=None):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        cuisine_category_service,
        "active_workspace_cuisine_category_labels",
        unavailable_registry,
    )

    assert cookbook_service.cookbook_category_choices()["cuisine"] == list(
        cookbook_service.COOKBOOK_CATEGORY_CHOICES["cuisine"]
    )


def test_cookbook_category_choices_honor_intentionally_empty_registry(monkeypatch):
    from PushShoppingList.services import cuisine_category_service

    monkeypatch.setattr(
        cuisine_category_service,
        "active_workspace_cuisine_category_labels",
        lambda user_id=None: [],
    )

    assert cookbook_service.cookbook_category_choices()["cuisine"] == []


def test_recipe_editor_cuisine_registry_management_and_refresh_contract():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert 'data-recipe-edit-multiselect-manage-url="/admin/master-data/cuisine-categories"' in template
    assert 'data-recipe-edit-multiselect-manage-label="Manage Cuisine Categories' in template
    assert (
        'data-recipe-edit-multiselect-manage-aria-label="Manage Cuisine Categories in a new tab"'
        in template
    )
    assert 'manage.target = "_blank";' in script
    assert 'manage.rel = "noopener";' in script
    assert 'manage.dataset.recipeEditMultiselectManage = "";' in script
    assert 'masterDataViewerUrl("/api/master-data/cuisine-categories")' in script
    assert 'window.addEventListener("focus", () => {' in script
    assert "refreshRecipeEditCuisineCategoryRegistry();" in script
    assert ".recipe-edit-multiselect-manage" in css
    assert "text-decoration: none;" in css[
        css.index(".recipe-edit-multiselect-manage"):
        css.index("}", css.index(".recipe-edit-multiselect-manage"))
    ]


def test_recipe_editor_cuisine_registry_refresh_preserves_selected_legacy_values():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    normalizers = script[
        script.index("function normalizeRecipeEditTagText"):
        script.index("function recipeEditMultiselectField")
    ]
    registry_logic = script[
        script.index("function recipeEditCuisineRegistryCategoryRows"):
        script.index("function canonicalRecipeEditMultiselectValue")
    ]
    harness = r'''
const listeners = {};
const rendered = [];
let recipeEditOriginalSnapshot = null;
const selectedInput = { value: "Legacy Cuisine, Unregistered Cuisine, Italian" };
const primaryInput = { value: "Legacy Cuisine" };
const source = {
    dataset: {},
    children: [],
    replaceChildren(...children) { this.children = children; },
};
const field = {
    querySelector(selector) {
        return selector === "[data-recipe-edit-multiselect-options]" ? source : null;
    },
};
const document = {
    body: { dataset: { recipeEditPage: "true" } },
    createElement() { return { dataset: {} }; },
    getElementById(id) {
        if (id === "recipeEditCuisineTags") return selectedInput;
        if (id === "recipeEditCategoryCuisine") return primaryInput;
        return null;
    },
};
const window = {
    addEventListener(name, callback) { listeners[name] = callback; },
};
function recipeEditMultiselectField(kind) { return kind === "cuisine" ? field : null; }
function renderRecipeEditMultiselect(kind) { rendered.push(kind); }
function setRecipeEditCuisineCategories(values) {
    selectedInput.value = values.join(", ");
    primaryInput.value = values[0] || "";
    renderRecipeEditMultiselect("cuisine");
}
function masterDataViewerUrl(value) { return value; }
let requestedUrl = "";
let nextPayload = null;
function fetch(url) {
    requestedUrl = url;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(nextPayload) });
}
const console = { warn() {} };
''' + normalizers + registry_logic + r'''

const parsed = recipeEditActiveCuisineRegistryLabels({
    categories: [
        { name: "Italian", active: true },
        { name: "Mexican", active: true },
        { name: "Retired Cuisine", active: false },
        { name: "italian", active: true },
    ],
});
const firstChanged = updateRecipeEditCuisineRegistryOptions(parsed);
const firstChoices = source.children.map(item => item.dataset.recipeEditMultiselectOption);

nextPayload = {
    registry: {
        items: [
            { label: "Japanese", active: true, aliases: ["Legacy Cuisine"] },
            { label: "Korean", active: true },
            { label: "Italian", active: false },
        ],
    },
};
refreshRecipeEditCuisineCategoryRegistry().then(secondChanged => {
    const secondChoices = source.children.map(item => item.dataset.recipeEditMultiselectOption);
    nextPayload = { categories: [] };
    return refreshRecipeEditCuisineCategoryRegistry().then(emptyChanged => ({
        secondChanged,
        secondChoices,
        emptyChanged,
    }));
}).then(({ secondChanged, secondChoices, emptyChanged }) => {
    process.stdout.write(JSON.stringify({
        parsed,
        firstChanged,
        firstChoices,
        secondChanged,
        secondChoices,
        emptyChanged,
        emptyChoices: source.children.map(item => item.dataset.recipeEditMultiselectOption),
        selected: selectedInput.value,
        primary: primaryInput.value,
        requestedUrl,
        rendered,
        focusBound: typeof listeners.focus === "function",
    }));
});
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["parsed"] == ["Italian", "Mexican"]
    assert result["firstChanged"] is True
    assert result["firstChoices"] == [
        "Italian",
        "Mexican",
        "Legacy Cuisine",
        "Unregistered Cuisine",
    ]
    assert result["secondChanged"] is True
    assert result["secondChoices"] == [
        "Japanese",
        "Korean",
        "Unregistered Cuisine",
        "Italian",
    ]
    assert result["emptyChanged"] is True
    assert result["emptyChoices"] == ["Japanese", "Unregistered Cuisine", "Italian"]
    assert result["selected"] == "Japanese, Unregistered Cuisine, Italian"
    assert result["primary"] == "Japanese"
    assert result["requestedUrl"] == "/api/master-data/cuisine-categories"
    assert result["rendered"] == ["cuisine", "cuisine", "cuisine"]
    assert result["focusBound"] is True


def test_recipe_editor_cuisine_registry_refresh_canonicalizes_late_alias_with_same_signature():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    normalizers = script[
        script.index("function normalizeRecipeEditTagText"):
        script.index("function recipeEditMultiselectField")
    ]
    registry_logic = script[
        script.index("function recipeEditCuisineRegistryCategoryRows"):
        script.index("function canonicalRecipeEditMultiselectValue")
    ]
    harness = r'''
const rendered = [];
let recipeEditOriginalSnapshot = null;
const recipeEditSavedFormSnapshots = new WeakMap();
const selectedInput = { value: "Legacy Cuisine" };
const primaryInput = { value: "Legacy Cuisine" };
const source = {
    dataset: { recipeEditCuisineRegistrySignature: "Japanese" },
    children: [{ dataset: { recipeEditMultiselectOption: "Japanese" } }],
    replaceCount: 0,
    replaceChildren(...children) {
        this.children = children;
        this.replaceCount += 1;
    },
};
const field = {
    querySelector(selector) {
        return selector === "[data-recipe-edit-multiselect-options]" ? source : null;
    },
};
const document = {
    createElement() { return { dataset: {} }; },
    getElementById(id) {
        if (id === "recipeEditCuisineTags") return selectedInput;
        if (id === "recipeEditCategoryCuisine") return primaryInput;
        return null;
    },
};
const window = { addEventListener() {} };
function recipeEditMultiselectField(kind) { return kind === "cuisine" ? field : null; }
function renderRecipeEditMultiselect(kind) { rendered.push(kind); }
function setRecipeEditCuisineCategories(values) {
    selectedInput.value = values.join(", ");
    primaryInput.value = values[0] || "";
    renderRecipeEditMultiselect("cuisine");
}
function masterDataViewerUrl(value) { return value; }
function fetch() { return Promise.resolve({ ok: false }); }
const console = { warn() {} };
''' + normalizers + registry_logic + r'''

const changed = updateRecipeEditCuisineRegistryOptions(
    ["Japanese"],
    new Map([["legacy cuisine", "Japanese"]]),
);
process.stdout.write(JSON.stringify({
    changed,
    selected: selectedInput.value,
    primary: primaryInput.value,
    replaceCount: source.replaceCount,
    rendered,
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "changed": True,
        "selected": "Japanese",
        "primary": "Japanese",
        "replaceCount": 0,
        "rendered": ["cuisine"],
    }


def test_recipe_editor_cuisine_registry_refresh_adopts_flagged_presentation_without_dirty_state():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    normalizers = script[
        script.index("function normalizeRecipeEditTagText"):
        script.index("function recipeEditMultiselectField")
    ]
    registry_logic = script[
        script.index("function recipeEditCuisineRegistryCategoryRows"):
        script.index("function canonicalRecipeEditMultiselectValue")
    ]
    dirty_logic = script[
        script.index("function recipeEditorCurrentSaveSnapshot"):
        script.index("function clearRecipeEditorValidation")
    ]
    harness = r'''
const rendered = [];
let currentDescription = "Saved description";
let recipeEditOriginalSnapshot = {
    description: "Saved description",
    cuisine: "United Kingdom",
    cuisine_tags: ["United Kingdom", "Chinese"],
};
const recipeEditSavedFormSnapshots = new WeakMap();
const selectedInput = { value: "United Kingdom, Chinese" };
const primaryInput = { value: "United Kingdom" };
const canonicalOptions = ["🇬🇧 United Kingdom", "🇨🇳 Chinese"];
const source = {
    dataset: { recipeEditCuisineRegistrySignature: canonicalOptions.join("\u001f") },
    children: canonicalOptions.map(value => ({
        dataset: { recipeEditMultiselectOption: value },
    })),
    replaceCount: 0,
    replaceChildren(...children) {
        this.children = children;
        this.replaceCount += 1;
    },
};
const field = {
    querySelector(selector) {
        return selector === "[data-recipe-edit-multiselect-options]" ? source : null;
    },
};
const form = {
    dataset: {
        originalCategoryValues: JSON.stringify({
            cuisine: "United Kingdom",
            meal_type: "Dinner",
        }),
    },
    querySelectorAll() { return []; },
};
const document = {
    body: { dataset: { recipeEditPage: "true" } },
    createElement() { return { dataset: {} }; },
    getElementById(id) {
        if (id === "recipeEditCuisineTags") return selectedInput;
        if (id === "recipeEditCategoryCuisine") return primaryInput;
        if (id === "recipeEditForm") return form;
        return null;
    },
};
const window = { addEventListener() {} };
function recipeEditMultiselectField(kind) { return kind === "cuisine" ? field : null; }
function renderRecipeEditMultiselect(kind) { rendered.push(kind); }
function setRecipeEditCuisineCategories(values) {
    selectedInput.value = values.join(", ");
    primaryInput.value = values[0] || "";
    renderRecipeEditMultiselect("cuisine");
}
function collectRecipeEditorPayload() {
    return {
        recipe: {
            description: currentDescription,
            cuisine: primaryInput.value,
            cuisine_tags: selectedInput.value
                .split(/[,;\n]+/)
                .map(value => value.trim())
                .filter(Boolean),
        },
    };
}
function collectRecipeEditorCategoryValues() {
    return { cuisine: primaryInput.value, meal_type: "Dinner" };
}
function collectRecipeEditorCategorySources() {
    return { cuisine: "user_selected", meal_type: "user_selected" };
}
function masterDataViewerUrl(value) { return value; }
function fetch() { return Promise.resolve({ ok: false }); }
const console = { warn() {} };
''' + normalizers + registry_logic + dirty_logic + r'''

recipeEditSavedFormSnapshots.set(form, recipeEditorCurrentSaveSnapshot(form));
const payload = {
    categories: [
        {
            name: "🇬🇧 United Kingdom",
            active: true,
            aliases: ["United Kingdom"],
        },
        {
            name: "🇨🇳 Chinese",
            active: true,
            aliases: ["Chinese"],
        },
    ],
};
const aliases = recipeEditCuisineRegistryAliasMap(payload);
const changed = updateRecipeEditCuisineRegistryOptions(
    recipeEditActiveCuisineRegistryLabels(payload),
    aliases,
);
const dirty = recipeEditorHasUnsavedChanges(form);
const savedSnapshot = JSON.parse(recipeEditSavedFormSnapshots.get(form));
const originalCategoryValues = JSON.parse(form.dataset.originalCategoryValues);

process.stdout.write(JSON.stringify({
    changed,
    dirty,
    selected: selectedInput.value,
    primary: primaryInput.value,
    choices: source.children.map(item => item.dataset.recipeEditMultiselectOption),
    replaceCount: source.replaceCount,
    rendered,
    ukAlias: aliases.get(recipeEditTagKey("United Kingdom")),
    chineseAlias: aliases.get(recipeEditTagKey("Chinese")),
    savedCuisine: savedSnapshot.payload.recipe.cuisine,
    savedCuisineTags: savedSnapshot.payload.recipe.cuisine_tags,
    savedCategoryCuisine: savedSnapshot.category_values.cuisine,
    originalCategoryCuisine: originalCategoryValues.cuisine,
    originalSnapshotCuisine: recipeEditOriginalSnapshot.cuisine,
    originalSnapshotCuisineTags: recipeEditOriginalSnapshot.cuisine_tags,
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "changed": True,
        "dirty": False,
        "selected": "🇬🇧 United Kingdom, 🇨🇳 Chinese",
        "primary": "🇬🇧 United Kingdom",
        "choices": ["🇬🇧 United Kingdom", "🇨🇳 Chinese"],
        "replaceCount": 0,
        "rendered": ["cuisine"],
        "ukAlias": "🇬🇧 United Kingdom",
        "chineseAlias": "🇨🇳 Chinese",
        "savedCuisine": "🇬🇧 United Kingdom",
        "savedCuisineTags": ["🇬🇧 United Kingdom", "🇨🇳 Chinese"],
        "savedCategoryCuisine": "🇬🇧 United Kingdom",
        "originalCategoryCuisine": "🇬🇧 United Kingdom",
        "originalSnapshotCuisine": "🇬🇧 United Kingdom",
        "originalSnapshotCuisineTags": [
            "🇬🇧 United Kingdom",
            "🇨🇳 Chinese",
        ],
    }


def test_recipe_editor_cuisine_alias_refresh_rebases_only_alias_baselines():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    normalizers = script[
        script.index("function normalizeRecipeEditTagText"):
        script.index("function recipeEditMultiselectField")
    ]
    registry_logic = script[
        script.index("function recipeEditCuisineRegistryCategoryRows"):
        script.index("function canonicalRecipeEditMultiselectValue")
    ]
    dirty_logic = script[
        script.index("function recipeEditorCurrentSaveSnapshot"):
        script.index("function clearRecipeEditorValidation")
    ]
    harness = r'''
let currentDescription = "Saved description";
let recipeEditOriginalSnapshot = {
    description: "Saved description",
    cuisine_tags: ["Legacy Cuisine"],
};
const recipeEditSavedFormSnapshots = new WeakMap();
const selectedInput = { value: "Legacy Cuisine" };
const primaryInput = { value: "Legacy Cuisine" };
const form = {
    dataset: {
        originalCategoryValues: JSON.stringify({
            cuisine: "Legacy Cuisine",
            meal_type: "Dinner",
        }),
    },
    querySelectorAll() { return []; },
};
const source = {
    dataset: { recipeEditCuisineRegistrySignature: "Japanese" },
    children: [{ dataset: { recipeEditMultiselectOption: "Japanese" } }],
    replaceChildren(...children) { this.children = children; },
};
const field = {
    querySelector(selector) {
        return selector === "[data-recipe-edit-multiselect-options]" ? source : null;
    },
};
const document = {
    createElement() { return { dataset: {} }; },
    getElementById(id) {
        if (id === "recipeEditCuisineTags") return selectedInput;
        if (id === "recipeEditCategoryCuisine") return primaryInput;
        if (id === "recipeEditForm") return form;
        return null;
    },
};
const window = { addEventListener() {} };
function recipeEditMultiselectField(kind) { return kind === "cuisine" ? field : null; }
function renderRecipeEditMultiselect() {}
function setRecipeEditCuisineCategories(values) {
    selectedInput.value = values.join(", ");
    primaryInput.value = values[0] || "";
}
function collectRecipeEditorPayload() {
    return {
        recipe: {
            description: currentDescription,
            cuisine_tags: selectedInput.value.split(/[,;\n]+/).map(value => value.trim()).filter(Boolean),
        },
    };
}
function collectRecipeEditorCategoryValues() {
    return { cuisine: primaryInput.value, meal_type: "Dinner" };
}
function collectRecipeEditorCategorySources() {
    return { cuisine: "user_selected", meal_type: "user_selected" };
}
function masterDataViewerUrl(value) { return value; }
function fetch() { return Promise.resolve({ ok: false }); }
const console = { warn() {} };
''' + normalizers + registry_logic + dirty_logic + r'''

recipeEditSavedFormSnapshots.set(form, recipeEditorCurrentSaveSnapshot(form));
currentDescription = "Unsaved description";
updateRecipeEditCuisineRegistryOptions(
    ["Japanese"],
    new Map([["legacy cuisine", "Japanese"]]),
);
const dirtyWithOtherEdit = recipeEditorHasUnsavedChanges(form);
const savedSnapshot = JSON.parse(recipeEditSavedFormSnapshots.get(form));
const originalCategoryValues = JSON.parse(form.dataset.originalCategoryValues);
currentDescription = "Saved description";
const dirtyAfterRevertingOtherEdit = recipeEditorHasUnsavedChanges(form);

process.stdout.write(JSON.stringify({
    selected: selectedInput.value,
    primary: primaryInput.value,
    dirtyWithOtherEdit,
    dirtyAfterRevertingOtherEdit,
    savedDescription: savedSnapshot.payload.recipe.description,
    savedCuisineTags: savedSnapshot.payload.recipe.cuisine_tags,
    savedCategoryCuisine: savedSnapshot.category_values.cuisine,
    originalCategoryCuisine: originalCategoryValues.cuisine,
    originalSnapshotCuisineTags: recipeEditOriginalSnapshot.cuisine_tags,
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["selected"] == "Japanese"
    assert result["primary"] == "Japanese"
    assert result["dirtyWithOtherEdit"] is True
    assert result["dirtyAfterRevertingOtherEdit"] is False
    assert result["savedDescription"] == "Saved description"
    assert result["savedCuisineTags"] == ["Japanese"]
    assert result["savedCategoryCuisine"] == "Japanese"
    assert result["originalCategoryCuisine"] == "Japanese"
    assert result["originalSnapshotCuisineTags"] == ["Japanese"]


def test_recipe_editor_renders_compact_classification_token_controls():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    category_start = template.index('id="recipeEditCategoriesSection"')
    tabs_start = template.index('class="recipe-edit-tabs-card"')
    category_markup = template[category_start:tabs_start]
    field_ids = [
        "recipeEditCategoryMealType",
        "recipeEditCategoryMainIngredient",
        "recipeEditCategoryCookingMethod",
        "recipeEditCategoryOccasion",
        "recipeEditCategoryDietaryPreference",
        "recipeEditCategoryCuisine",
        "recipeEditCategoryCustomCategories",
    ]

    assert template.count('id="recipeEditCategoriesSection"') == 1
    assert template.index('class="recipe-edit-info-panel"') < category_start < tabs_start
    assert template.index("recipeEditCategoriesSection") < template.index("recipeEditIngredientsTitle")
    assert 'class="recipe-edit-inline-categories"' in category_markup
    assert 'aria-label="Recipe categories"' in category_markup
    assert [category_markup.index(field_id) for field_id in field_ids] == sorted(
        category_markup.index(field_id) for field_id in field_ids
    )
    for field_id in field_ids:
        assert category_markup.count(f'id="{field_id}"') == 1
    assert "Cuisine Categories" in category_markup
    assert "Dietary Preferences" in category_markup
    assert "Custom Tags" in category_markup
    assert "Use inferred" not in category_markup
    assert category_markup.count('data-recipe-edit-multiselect-field="cuisine"') == 1
    assert category_markup.count('data-recipe-edit-multiselect-field="dietary"') == 1
    assert category_markup.count('data-recipe-edit-multiselect-field="custom"') == 1
    assert 'id="recipeEditCategoryPrepTimeGroup"' in category_markup
    prep_start = category_markup.index('id="recipeEditCategoryPrepTimeGroup"')
    assert 'type="hidden"' in category_markup[prep_start:category_markup.index(">", prep_start)]

    assert 'role="group"' in category_markup
    assert 'aria-labelledby="recipeEditCustomTagsLabel"' in category_markup
    assert 'id="recipeEditCategoryCustomCategories"' in category_markup
    custom_start = category_markup.index('id="recipeEditCategoryCustomCategories"')
    custom_control = category_markup[custom_start:category_markup.index(">", custom_start)]
    assert 'type="hidden"' in custom_control
    assert 'name="custom_categories"' in custom_control
    assert template.count('id="recipeEditCuisineTags"') == 1
    assert 'name="cuisine_tags"' in category_markup
    assert template.index('id="recipeEditCuisineTags"') > category_start
    assert 'data-recipe-edit-multiselect-option="{{ choice }}"' in category_markup
    assert "cookbook_view.custom_tag_choices" in category_markup

    for removed_ui in (
        "Recipe Categories",
        "Edit Recipe Categories",
        "recipeEditCategoriesBody",
        "data-recipe-edit-category-summary",
        "data-recipe-edit-category-collapse",
        "data-recipe-edit-category-more",
    ):
        assert removed_ui not in category_markup

    assert "Have ChatGPT Decide All" in category_markup
    assert "Have ChatGPT Decide Missing" in category_markup
    assert "recipeEditCategoryMenuSectionField" in category_markup
    assert "Edit Menu Section" in category_markup

    organizer = script[
        script.index("function organizeRecipeEditInformationCard"):
        script.index("function organizeRecipeEditAiAssistant")
    ]
    assert 'classificationHeading.textContent = "Classification"' in organizer
    assert "[mealTypeField, cuisineCategoryField, dietaryPreferenceField]" in organizer
    assert "[mainIngredientField, cookingMethodField, occasionField, customCategoriesField]" in organizer
    assert "classificationSecondaryRow," in organizer
    assert organizer.index("classificationPrimaryRow,") < organizer.index("classificationSecondaryRow,")
    assert "More classification details" not in organizer
    assert "recipeEditClassificationDetailsPanel" not in organizer
    assert "createRecipeEditOptionalDetails" not in script
    assert 'customCategoriesField?.classList.remove("recipe-edit-wide")' in organizer
    assert "AI-filled fields &mdash; edit or clear anything that looks wrong" in organizer
    assert "prepareRecipeEditCategorySuggestionField" in organizer
    assert 'initializeRecipeEditMultiselectField(dietaryPreferenceField, "dietary")' in organizer
    assert 'initializeRecipeEditMultiselectField(cuisineCategoryField, "cuisine")' in organizer
    assert 'initializeRecipeEditMultiselectField(customCategoriesField, "custom")' in organizer
    assert "tagRow" not in organizer

    assert "function populateRecipeEditCategories" in script
    assert "function saveRecipeEditorCategories" in script
    assert "saveRecipeEditorCategories(sourceUrl, payload.original_url)" in script
    assert 'values.custom_categories = Array.isArray(recipe.custom_categories)' in script
    assert 'setRecipeEditCustomCategories(values.custom_categories, { notify: false });' in script
    assert "function setRecipeEditCuisineCategories" in script
    assert "function setRecipeEditDietaryPreferences" in script
    assert "function initializeRecipeEditMultiselectField" in script
    assert "function openRecipeEditMultiselect" in script
    assert "function closeRecipeEditMultiselect" in script
    assert "function createRecipeEditCustomTagFromSearch" in script
    assert "function announceRecipeEditMultiselect" in script
    assert "function positionRecipeEditMultiselectPopover" in script
    assert "function recipeEditCustomTagHasDelimiter" in script
    assert "function handleRecipeEditMultiselectSearchKeydown" in script
    assert 'trigger.type = "button";' in script
    assert 'trigger.dataset.recipeEditMultiselectTrigger = "";' in script
    assert 'trigger.innerHTML = \'<span aria-hidden="true">+</span>\';' in script
    assert script.count('addLabel: "Add cuisine"') == 1
    assert script.count('addLabel: "Add dietary preference"') == 1
    assert script.count('addLabel: "Add custom tag"') == 1
    assert 'trigger.setAttribute("aria-label", copy.addLabel);' in script
    assert 'trigger.setAttribute("aria-haspopup", "listbox");' in script
    assert 'trigger.setAttribute("aria-expanded", "false");' in script
    assert "trigger.title = copy.addLabel;" in script
    assert "control.append(chips, trigger, popover, status);" in script
    assert 'popover.hidden = true;' in script
    assert 'parts.popover.hidden = false;' in script
    assert 'parts.trigger.setAttribute("aria-expanded", "true");' in script
    assert 'parts.trigger.focus({ preventScroll: true });' in script
    assert 'current?.search.focus({ preventScroll: true });' in script
    assert 'closeRecipeEditMultiselect(kind, { focusTrigger: true });' in script
    assert 'search.addEventListener("keydown", event => handleRecipeEditMultiselectSearchKeydown(event, kind));' in script
    assert 'listbox.setAttribute("aria-multiselectable", "true");' in script
    assert "listbox.tabIndex = -1;" in script
    assert 'button.setAttribute("aria-selected", selected ? "true" : "false");' in script
    assert 'button.classList.add("is-selected");' in script
    assert 'return !queryKey || key.includes(queryKey);' in script
    assert 'return !selectedKeys.has(key)' not in script
    assert "function addRecipeEditMultiselectSearchValues" not in script
    assert "function updateRecipeEditMultiselectAddButton" not in script
    assert "recipe-edit-multiselect-entry" not in script
    assert "recipe-edit-multiselect-add" not in script
    assert "function recipeEditStructuredCategoryMatch" in script
    assert 'data.recipeEditCreateTag' not in script
    assert "dataset.recipeEditCreateTag" in script
    assert 'formData.set("custom_categories", values.custom_categories || "");' in script
    assert "function setRecipeEditCustomCategories" in script
    assert "function clearRecipeEditCustomCategory" in script
    assert "function renderRecipeEditCustomCategoryChips" in script
    assert 'remove.setAttribute("aria-label", `Remove ${copy.chipLabel} ${value}`)' in script
    assert "normalizeRecipeEditCustomTag" in script
    assert "uniqueRecipeEditMultiselectValues" in script
    assert "recipeEditStructuredCategoryMatch(query)" in script
    assert 'setRecipeEditCustomCategories(mergedCustom' in script
    assert "function renderRecipeEditCategorySummary" not in script
    assert "function toggleRecipeEditCategories" not in script
    assert "function acceptRecipeEditCategorySuggestion" not in script
    assert "function editRecipeEditCategorySuggestion" not in script
    assert "function dismissRecipeEditCategorySuggestion" not in script
    assert "recipeEditAiFieldActions" not in script
    assert "updateRecipeEditorDirtyState(form);" in script[
        script.index("function applyRecipeEditCategorySuggestions"):
        script.index("async function decideRecipeEditCategoriesWithChatGPT")
    ]
    assert 'field !== "prep_time_group"' in script
    assert "recipe-edit-tag-chip-ai" not in script

    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    category_css = css[css.index(marker):]
    assert ".recipe-edit-classification-grid" in category_css
    assert ".recipe-edit-optional-details" not in category_css
    assert ".recipe-edit-ai-suggestion-summary" in category_css
    assert ".recipe-edit-ai-field-actions" not in category_css
    assert ".recipe-edit-multiselect-control" in category_css
    control_selector = (
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized "
        ".recipe-edit-multiselect-control {"
    )
    control_start = category_css.rindex(control_selector)
    control_rule = category_css[control_start:category_css.index("}", control_start)]
    assert "border: 0;" in control_rule
    assert ".recipe-edit-multiselect-trigger" in category_css
    assert ".recipe-edit-multiselect-popover" in category_css
    assert ".recipe-edit-multiselect-field.is-flipped .recipe-edit-multiselect-popover" in category_css
    assert ".recipe-edit-multiselect-search-wrap" in category_css
    assert ".recipe-edit-multiselect-done" in category_css
    assert ".recipe-edit-multiselect-options" in category_css
    assert ".recipe-edit-multiselect-entry" not in category_css
    assert ".recipe-edit-multiselect-add" not in category_css
    assert ".recipe-edit-classification-secondary-grid" in category_css
    assert "width: min(100%, 960px);" in category_css
    assert "grid-template-columns: minmax(180px, 220px) repeat(2, minmax(260px, 320px));" in category_css
    assert "column-gap: clamp(32px, 2vw, 40px);" in category_css
    assert category_css.count(
        'input:not([type="hidden"]):not(.recipe-edit-multiselect-search)'
    ) == 3
    assert ".recipe-edit-multiselect-search-wrap > input.recipe-edit-multiselect-search" in category_css
    assert "display: contents;" in category_css
    assert "width: fit-content;" in category_css
    assert "min-height: 42px;" in category_css
    assert "width: 32px;" in category_css
    assert "min-width: 32px;" in category_css
    assert "height: 32px;" in category_css
    assert "flex: 0 0 32px;" in category_css
    assert "width: min(320px, calc(100vw - 32px));" in category_css
    assert "min-width: min(280px, calc(100vw - 32px));" in category_css
    assert "max-width: min(360px, calc(100vw - 32px));" in category_css
    assert "height: 36px;" in category_css
    assert "min-height: 36px;" in category_css
    assert "max-width: 100%;" in category_css
    assert "flex-wrap: wrap;" in category_css
    assert ".recipe-edit-multiselect-option.is-selected" in category_css
    assert 'content: "✓";' in category_css
    assert "@container recipe-details (max-width: 940px)" in category_css
    assert "@container recipe-details (max-width: 620px)" in category_css
    assert "@container recipe-details (max-width: 520px)" in category_css
    assert "@media (max-width: 1100px)" in category_css
    assert "@media (max-width: 640px)" in category_css
    assert category_css.count("> .recipe-edit-custom-categories-field {") == 3
    assert category_css.count("> [data-recipe-edit-category-field=\"dietary_preference\"] {") == 2
    assert category_css.count("grid-column: 1 / -1;") >= 2

    classification_container = category_css[
        category_css.index("@container recipe-details (max-width: 940px)"):
        category_css.index("@media (max-width: 1100px)")
    ]
    assert ".recipe-edit-classification-primary-grid" in classification_container
    assert ".recipe-edit-classification-secondary-grid" in classification_container
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in classification_container
    assert "column-gap: clamp(24px, 3vw, 32px);" in classification_container
    assert ".recipe-edit-details-primary-grid" not in classification_container

    narrow_classification_container = category_css[
        category_css.index("@container recipe-details (max-width: 620px)"):
        category_css.index("@container recipe-details (max-width: 520px)")
    ]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in narrow_classification_container

    for declaration in (
        "--recipe-edit-compact-multiselect-min-width: 0;",
        "--recipe-edit-compact-multiselect-max-width: 300px;",
        "--recipe-edit-compact-multiselect-max-width: 320px;",
        "width: fit-content;",
        "min-width: var(--recipe-edit-compact-multiselect-min-width);",
        "max-width: var(--recipe-edit-compact-multiselect-max-width);",
    ):
        assert declaration in category_css

    for declaration in (
        "--recipe-edit-compact-select-field-sizing: content;",
        "--recipe-edit-compact-select-flex: 0 1 auto;",
        "--recipe-edit-compact-select-width: auto;",
        "--recipe-edit-compact-select-min-width: 132px;",
        "--recipe-edit-compact-select-max-width: 190px;",
        "--recipe-edit-compact-select-justify-self: start;",
    ):
        assert declaration in category_css

    for property_name in ("field-sizing", "flex", "width", "min-width", "max-width"):
        assert f"{property_name}: var(--recipe-edit-compact-select-" in category_css

    compact_select_ids = (
        "recipeEditCategoryMealType",
        "recipeEditCategoryMainIngredient",
        "recipeEditCategoryCookingMethod",
        "recipeEditCategoryOccasion",
    )
    for field_id in compact_select_ids:
        assert f"#{field_id}" in category_css
        assert css.count(f"#{field_id}") >= 6
    assert "):not([disabled]):not([readonly]):not([aria-invalid=\"true\"])" in css
    assert "):not([disabled]):not([readonly]):is(:focus, :focus-visible) {" in css

    mobile_start = category_css.index("@media (max-width: 640px)")
    mobile = category_css[mobile_start:]
    for declaration in (
        "--recipe-edit-compact-select-field-sizing: fixed;",
        "--recipe-edit-compact-select-flex: 1 1 auto;",
        "--recipe-edit-compact-select-width: 100%;",
        "--recipe-edit-compact-select-min-width: 0;",
        "--recipe-edit-compact-select-max-width: 100%;",
        "--recipe-edit-compact-select-justify-self: stretch;",
    ):
        assert declaration in mobile
    for field_name in ("cuisine", "dietary_preference", "custom_categories"):
        assert f'[data-recipe-edit-category-field="{field_name}"]' in mobile
    for declaration in (
        "width: 100%;",
        "min-width: 0;",
        "max-width: 100%;",
        "justify-self: stretch;",
    ):
        assert declaration in mobile

    assert 'cuisine_tags: recipeEditCuisineTagValues(),' in script
    assert 'dietary_preferences: recipeEditDietaryPreferenceValues(),' in script
    assert '"cuisine_tags": split_recipe_menu_text_list(' in read_text(
        "PushShoppingList/services/recipe_edit_service.py"
    )


def test_recipe_category_select_fills_from_saved_text_content():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    field_binding = script[
        script.index("function categoryFieldOptionKey"):
        script.index("function openCookbookCategoryEditor")
    ]
    harness = r'''
function makeOption(value, textContent, preserved = false) {
    return {
        value,
        textContent,
        dataset: preserved ? { preservedCategoryValue: "1" } : {},
        owner: null,
        remove() {
            const index = this.owner.options.indexOf(this);
            if (index >= 0) this.owner.options.splice(index, 1);
        },
    };
}

function makeSelect() {
    const field = {
        tagName: "SELECT",
        value: "",
        options: [
            makeOption("", "Not selected"),
            makeOption("🍽️ Dinner", "🍽️ Dinner"),
        ],
        add(option) {
            option.owner = this;
            this.options.push(option);
        },
    };
    field.options.forEach(option => { option.owner = field; });
    return field;
}

const document = {
    createElement(tagName) {
        if (tagName !== "option") throw new Error(`Unexpected element: ${tagName}`);
        return makeOption("", "");
    },
};
''' + field_binding + r'''

const mealType = makeSelect();
const form = { elements: { meal_type: mealType } };

setCookbookCategoryFieldValue(form, "meal_type", "Dinner");
const matchedVisibleText = {
    value: mealType.value,
    preservedCount: mealType.options.filter(option => option.dataset.preservedCategoryValue === "1").length,
};

setCookbookCategoryFieldValue(form, "meal_type", "Brunch");
const preservedSavedText = {
    value: mealType.value,
    text: mealType.options.find(option => option.value === mealType.value)?.textContent,
    preservedCount: mealType.options.filter(option => option.dataset.preservedCategoryValue === "1").length,
};

setCookbookCategoryFieldValue(form, "meal_type", "Dinner");
const staleOptionRemoved = {
    value: mealType.value,
    preservedCount: mealType.options.filter(option => option.dataset.preservedCategoryValue === "1").length,
};

process.stdout.write(JSON.stringify({ matchedVisibleText, preservedSavedText, staleOptionRemoved }));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "matchedVisibleText": {
            "value": "🍽️ Dinner",
            "preservedCount": 0,
        },
        "preservedSavedText": {
            "value": "Brunch",
            "text": "Brunch",
            "preservedCount": 1,
        },
        "staleOptionRemoved": {
            "value": "🍽️ Dinner",
            "preservedCount": 0,
        },
    }


def test_recipe_classification_token_search_commits_only_valid_unique_values():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    normalizers = script[
        script.index("function normalizeRecipeEditTagText"):
        script.index("function recipeEditMultiselectField")
    ]
    unique_values = script[
        script.index("function canonicalRecipeEditMultiselectValue"):
        script.index("function recipeEditCuisineTagValues")
    ]
    copy = script[
        script.index("function recipeEditMultiselectCopy"):
        script.index("function recipeEditStructuredCategoryMatch")
    ]
    selection_behavior = script[
        script.index("function selectRecipeEditMultiselectValue"):
        script.index("function useRecipeEditStructuredCategorySuggestion")
    ]
    keyboard_behavior = script[
        script.index("function handleRecipeEditMultiselectSearchKeydown"):
        script.index("function initializeRecipeEditMultiselectField")
    ]

    harness = r'''
const state = { cuisine: [], dietary: [], custom: [] };
const available = {
    cuisine: ["🇵🇪 Peruvian", "🇮🇹 Italian"],
    dietary: ["🍽️ Flexible", "🌱 Vegan"],
    custom: ["Creamy", "Spicy", "Audit Tag"],
};
const announcements = [];
let formSubmissions = 0;
const CATEGORY_SOURCE_USER_SELECTED = "user_selected";
const window = { requestAnimationFrame(callback) { callback(); } };

function recipeEditMultiselectOptions(kind) { return available[kind].slice(); }
function recipeEditMultiselectValues(kind) { return state[kind].slice(); }
function setRecipeEditMultiselectValues(kind, values) {
    state[kind] = uniqueRecipeEditMultiselectValues(values, kind);
}
function announceRecipeEditMultiselect(kind, message) {
    announcements.push({ kind, message });
}
function renderRecipeEditMultiselectOptions() {}
function openRecipeEditMultiselect(kind) {
    const parts = allParts[kind];
    parts.open = true;
    parts.search.focus();
}
function closeRecipeEditMultiselect(kind, options = {}) {
    const parts = allParts[kind];
    parts.open = false;
    parts.search.value = "";
    if (options.focusTrigger) parts.trigger.focus();
}
function removeRecipeEditMultiselectValue() {}

function makeOption(kind, value, selected = false) {
    return {
        dataset: { recipeEditMultiselectValue: value },
        classList: { contains(name) { return name === "is-selected" && selected; } },
        click() { selectRecipeEditMultiselectValue(kind, value); },
        focus() {},
    };
}

function createParts() {
    const parts = {
        open: false,
        options: [],
        search: {
            value: "",
            focused: false,
            focus() { this.focused = true; },
        },
        trigger: {
            focused: false,
            focus() { this.focused = true; },
        },
    };
    parts.listbox = {
        querySelectorAll() { return parts.options; },
    };
    return parts;
}

const allParts = {
    cuisine: createParts(),
    dietary: createParts(),
    custom: createParts(),
};
function recipeEditMultiselectParts(kind) { return allParts[kind]; }
''' + normalizers + unique_values + copy + selection_behavior + keyboard_behavior + r'''

function press(kind, key, value, options = []) {
    const parts = allParts[kind];
    parts.search.value = value;
    parts.search.focused = false;
    parts.options = options;
    let prevented = false;
    handleRecipeEditMultiselectSearchKeydown({
        key,
        preventDefault() { prevented = true; },
    }, kind);
    if (key === "Enter" && !prevented) formSubmissions += 1;
    return {
        prevented,
        open: parts.open,
        focused: parts.search.focused,
        triggerFocused: parts.trigger.focused,
        values: state[kind].slice(),
    };
}

const cuisineAdd = press(
    "cuisine",
    "Enter",
    "peruvian",
    [makeOption("cuisine", "🇵🇪 Peruvian")],
);
const cuisineDuplicate = press(
    "cuisine",
    "Enter",
    "PERUVIAN",
    [makeOption("cuisine", "🇵🇪 Peruvian", true)],
);
const cuisineUnknown = press("cuisine", "Enter", "Martian", []);
const dietaryAdd = press(
    "dietary",
    "Enter",
    "vegan",
    [makeOption("dietary", "🌱 Vegan")],
);
const existingCustom = press(
    "custom",
    "Enter",
    "  creamy ",
    [makeOption("custom", "Creamy")],
);
const newCustom = press("custom", "Enter", "  mediterranean  ", []);
const duplicateCustom = press("custom", "Enter", "mediterranean", []);
const delimitedSavedCustom = press(
    "custom",
    "Enter",
    "Audit, Tag",
    [makeOption("custom", "Audit Tag")],
);
const delimitedNewCustom = press("custom", "Enter", "New, Split", []);
const blankCustom = press("custom", "Enter", "   ", []);
allParts.custom.open = true;
const beforeEscape = state.custom.slice();
const escape = press("custom", "Escape", "sp", []);

process.stdout.write(JSON.stringify({
    cuisineAdd,
    cuisineDuplicate,
    cuisineUnknown,
    dietaryAdd,
    existingCustom,
    newCustom,
    duplicateCustom,
    delimitedSavedCustom,
    delimitedNewCustom,
    blankCustom,
    escape,
    beforeEscape,
    finalState: state,
    announcements,
    formSubmissions,
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["cuisineAdd"] == {
        "prevented": True,
        "open": True,
        "focused": True,
        "triggerFocused": False,
        "values": ["🇵🇪 Peruvian"],
    }
    assert result["cuisineDuplicate"]["values"] == ["🇵🇪 Peruvian"]
    assert result["cuisineUnknown"]["values"] == ["🇵🇪 Peruvian"]
    assert result["dietaryAdd"]["values"] == ["🌱 Vegan"]
    assert result["existingCustom"]["values"] == ["Creamy"]
    assert result["newCustom"]["values"] == ["Creamy", "Mediterranean"]
    assert result["duplicateCustom"]["values"] == ["Creamy", "Mediterranean"]
    assert result["delimitedSavedCustom"]["values"] == ["Creamy", "Mediterranean", "Audit Tag"]
    assert result["delimitedNewCustom"]["values"] == ["Creamy", "Mediterranean", "Audit Tag"]
    assert result["blankCustom"]["values"] == ["Creamy", "Mediterranean", "Audit Tag"]
    assert result["beforeEscape"] == ["Creamy", "Mediterranean", "Audit Tag"]
    assert result["escape"] == {
        "prevented": True,
        "open": False,
        "focused": False,
        "triggerFocused": True,
        "values": ["Creamy", "Mediterranean", "Audit Tag"],
    }
    assert any("already selected" in item["message"] for item in result["announcements"])
    assert any("one tag at a time" in item["message"] for item in result["announcements"])
    assert result["formSubmissions"] == 0


def test_recipe_classification_multiselects_preserve_primary_hidden_values():
    node = shutil.which("node")
    if not node:
        return

    script = read_text("PushShoppingList/static/js/app.js")
    normalizers = script[
        script.index("function normalizeRecipeEditTagText"):
        script.index("function recipeEditMultiselectField")
    ]
    value_logic = script[
        script.index("function canonicalRecipeEditMultiselectValue"):
        script.index("function setRecipeEditCustomCategories")
    ]
    harness = r'''
const CATEGORY_SOURCE_USER_SELECTED = "user_selected";
const available = {
    cuisine: ["🇵🇪 Peruvian", "🇮🇹 Italian"],
    dietary: ["🍽️ Flexible", "🌱 Vegan"],
};
let eventCount = 0;
let sourceUpdates = 0;
const inputs = Object.fromEntries([
    "recipeEditCuisineTags",
    "recipeEditCategoryCuisine",
    "recipeEditDietaryPreferences",
    "recipeEditCategoryDietaryPreference",
].map(id => [id, {
    id,
    value: "",
    dispatchEvent() { eventCount += 1; },
}]));
const document = {
    getElementById(id) { return id === "recipeEditForm" ? {} : inputs[id] || null; },
};
function Event(type) { this.type = type; }
function recipeEditMultiselectOptions(kind) { return available[kind] || []; }
function renderRecipeEditMultiselect() {}
function setFormCategorySource() { sourceUpdates += 1; }
''' + normalizers + value_logic + r'''

setRecipeEditCuisineCategories(["Peruvian"], { notify: false, primary: "Peruvian" });
const initialCuisine = {
    primary: inputs.recipeEditCategoryCuisine.value,
    list: inputs.recipeEditCuisineTags.value,
    events: eventCount,
};
setRecipeEditCuisineCategories([...recipeEditCuisineTagValues(), "Italian"]);
const addedCuisine = {
    primary: inputs.recipeEditCategoryCuisine.value,
    list: inputs.recipeEditCuisineTags.value,
};
setRecipeEditCuisineCategories(["Italian"]);
const promotedCuisine = {
    primary: inputs.recipeEditCategoryCuisine.value,
    list: inputs.recipeEditCuisineTags.value,
};
setRecipeEditCuisineCategories([]);
const clearedCuisine = {
    primary: inputs.recipeEditCategoryCuisine.value,
    list: inputs.recipeEditCuisineTags.value,
};

setRecipeEditDietaryPreferences(["Flexible"], { notify: false, primary: "Flexible" });
setRecipeEditDietaryPreferences([...recipeEditDietaryPreferenceValues(), "Vegan"]);
const addedDietary = {
    primary: inputs.recipeEditCategoryDietaryPreference.value,
    list: inputs.recipeEditDietaryPreferences.value,
};
setRecipeEditDietaryPreferences(["Vegan"]);
const promotedDietary = {
    primary: inputs.recipeEditCategoryDietaryPreference.value,
    list: inputs.recipeEditDietaryPreferences.value,
};
setRecipeEditDietaryPreferences([]);
const clearedDietary = {
    primary: inputs.recipeEditCategoryDietaryPreference.value,
    list: inputs.recipeEditDietaryPreferences.value,
};

process.stdout.write(JSON.stringify({
    initialCuisine,
    addedCuisine,
    promotedCuisine,
    clearedCuisine,
    addedDietary,
    promotedDietary,
    clearedDietary,
    eventCount,
    sourceUpdates,
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["initialCuisine"] == {
        "primary": "🇵🇪 Peruvian",
        "list": "🇵🇪 Peruvian",
        "events": 0,
    }
    assert result["addedCuisine"] == {
        "primary": "🇵🇪 Peruvian",
        "list": "🇵🇪 Peruvian, 🇮🇹 Italian",
    }
    assert result["promotedCuisine"] == {
        "primary": "🇮🇹 Italian",
        "list": "🇮🇹 Italian",
    }
    assert result["clearedCuisine"] == {"primary": "", "list": ""}
    assert result["addedDietary"] == {
        "primary": "🍽️ Flexible",
        "list": "🍽️ Flexible, 🌱 Vegan",
    }
    assert result["promotedDietary"] == {
        "primary": "🌱 Vegan",
        "list": "🌱 Vegan",
    }
    assert result["clearedDietary"] == {"primary": "", "list": ""}
    assert result["eventCount"] == 24
    assert result["sourceUpdates"] == 6


def test_recipe_editor_mobile_footer_uses_compact_ai_controls():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")

    footer = template[template.index('<div class="recipe-edit-actions">'):template.index("</div>", template.index('<div class="recipe-edit-actions">'))]
    assert 'data-short-label="Overwrite"' in footer
    assert 'data-short-label="Preview"' in footer
    assert 'data-short-label="Infer"' in footer

    mobile_start = css.index("@media (max-width: 760px)", css.index(".recipe-edit-ai-infer"))
    phone_start = css.index("@media (max-width: 520px)", mobile_start)
    mobile_css = css[mobile_start:phone_start]
    phone_css = css[phone_start:css.index("}", css.index("grid-template-columns: repeat(3", phone_start)) + 1]

    assert "grid-template-columns: repeat(6, minmax(0, 1fr));" in mobile_css
    assert ".recipe-edit-actions .recipe-edit-ai-overwrite-toggle" in mobile_css
    assert "width: auto;" in mobile_css
    assert "flex-basis: auto;" in mobile_css
    assert "content: attr(data-short-label);" in mobile_css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in phone_css
    assert ".recipe-edit-ai-overwrite-toggle {\n                width: 100%;" not in mobile_css
    assert ".recipe-edit-ai-infer {\n                flex-basis: 100%;" not in mobile_css


def test_recipe_editor_infer_missing_details_runs_full_ai_followups():
    script = read_text("PushShoppingList/static/js/app.js")
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")

    assert "async function estimateRecipeNutrition(button, options = {})" in script
    assert "async function decideRecipeEditCategoriesWithChatGPT(button, mode = \"missing\", options = {})" in script
    assert "async function runRecipeEditorInferenceFollowups()" in script
    assert "let recipeEditInferenceContext = {};" in script
    assert "cookbook_id: recipeEditInferenceContext.cookbook_id || \"\"" in script
    assert "cookbook_name: recipeEditInferenceContext.cookbook_name || \"\"" in script
    assert "await estimateRecipeNutrition(null, {" in script
    assert "forceEstimate: true" in script
    assert "force_estimate: forceEstimate" in script
    assert "await decideRecipeEditCategoriesWithChatGPT(null, \"all\", {" in script
    assert "const followupResult = previewOnly ? null : await runRecipeEditorInferenceFollowups();" in script
    assert "Save Recipe to keep nutrition/categories." in script
    assert "AI Assistant" in template
    assert "Regenerate Recipe" in template
    assert "onclick=\"return rerunRecipePredictionFromMenu(this)\"" in template
    assert 'restoreText: "Re-run Recipe Prediction..."' in script
    assert "function rerunRecipePredictionFromMenu(button)" in script
    assert "previewOnly: true" in script
    assert "overwriteAiFields: true" in script
    assert "applyPreviewToEditor: true" in script
    assert "forceRecipeNotes: true" in script
    assert 'forceFields: ["recipe_notes"]' in script
    assert "recipe: payload.recipe" in script
    assert "force_recipe_notes: Boolean(optionObject.forceRecipeNotes)" in script
    assert "Preview loaded in the editor. Save Recipe to keep it." in script


def test_recipe_editor_estimate_per_serving_prompts_before_overwrite():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "let forceEstimate = Boolean(options.forceEstimate || options.force);" in script
    assert "function recipeHasNutritionData(recipe = {})" in script
    assert "recipeHasNutritionData(payload.recipe)" in script
    assert "const hasPerServingEstimate = recipeHasPerServingEstimate(payload.recipe);" in script
    assert "window.confirm(\"Nutrition data already exists. Overwrite it with a new per-serving estimate?\")" in script
    assert "forceEstimate = true;" in script
    assert "Existing nutrition data was kept." in script
    assert "canceled: shouldPromptOverwrite" in script
    assert "force_estimate: forceEstimate" in script


def test_recipe_nutrition_estimate_force_bypasses_existing_nutrition(monkeypatch, tmp_path):
    calls = []

    def fake_estimate(recipe):
        calls.append(recipe)
        return {
            "ok": True,
            "nutrition": [
                {"key": "serving_basis", "value": "per serving"},
                {"key": "calories", "value": "210 kcal"},
            ],
        }

    monkeypatch.setattr(recipe_routes, "estimate_recipe_nutrition", fake_estimate)
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [{
            "user_id": "nutrition-user",
            "email": "nutrition@example.com",
            "username": "nutrition",
            "account_status": "active",
        }],
    })

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "nutrition-user"

        response = client.post(
            "/api/recipe_nutrition_estimate",
            json={
                "force_estimate": True,
                "recipe": {
                    "recipe_title": "Spring Roll",
                    "ingredients": [{"ingredient": "rice paper"}],
                    "nutrition": [
                        {"key": "serving_basis", "value": "per serving"},
                        {"key": "calories", "value": "165 kcal"},
                    ],
                },
            },
        )

    data = response.get_json()

    assert response.status_code == 200
    assert calls
    assert data["nutrition"][1] == {"key": "calories", "value": "210 kcal"}


def test_recipe_editor_category_metadata_preserves_saved_values_without_live_inference():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        choices = cookbook_service.cookbook_category_choices()
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/enchiladas"],
            [{"name": "Enchiladas Verde", "url": "https://example.com/enchiladas"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/enchiladas",
            {
                "meal_type": choices["meal_type"][1],
                "cuisine": choices["cuisine"][1],
                "custom_categories": "Sophia's Favorites, Weeknight Dinners",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor(
            "https://example.com/enchiladas",
            {
                "recipe_title": "Enchiladas Verde with Jackfruit and White Beans",
                "prep_time": "20 min",
                "ingredients": [
                    {"ingredient": "young green jackfruit"},
                    {"ingredient": "white beans"},
                    {"ingredient": "green enchilada sauce"},
                ],
                "instructions": [
                    {"instruction": "Bake the filled tortillas until hot."},
                ],
            },
            {"name": "Enchiladas Verde"},
        )

        assert metadata["meal_type"] == choices["meal_type"][1]
        assert metadata["cuisine"] == choices["cuisine"][1]
        assert metadata["main_ingredient"] == ""
        assert metadata["cooking_method"] == ""
        assert metadata["prep_time_group"] == ""
        assert metadata["custom_categories"] == ["Sophia's Favorites", "Weeknight Dinners"]
        assert metadata["category_metadata_source"] == "Saved"
        assert metadata["category_metadata_sources"]["meal_type"] == "user_selected"
        assert metadata["category_metadata_sources"]["main_ingredient"] == "blank"


def test_recipe_category_metadata_preserves_ai_inferred_sources():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        choices = cookbook_service.cookbook_category_choices()
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/beans"],
            [{"name": "Bean Enchiladas", "url": "https://example.com/beans"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/beans",
            {
                "meal_type": choices["meal_type"][2],
                "main_ingredient": next(item for item in choices["main_ingredient"] if "Beans" in item),
            },
            category_sources={
                "meal_type": "user_selected",
                "main_ingredient": "ai_inferred",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor("https://example.com/beans")

        assert metadata["category_metadata_sources"]["meal_type"] == "user_selected"
        assert metadata["category_metadata_sources"]["main_ingredient"] == "ai_inferred"
        assert metadata["category_metadata_sources"]["cuisine"] == "blank"


def test_recipe_menu_section_saves_as_cookbook_specific_metadata():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/spring-roll"],
            [{"name": "Spring Roll", "url": "https://example.com/spring-roll"}],
        )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/spring-roll",
            {
                "menu_section": "Kitchen Appetizers",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor(
            "https://example.com/spring-roll",
            {"recipe_title": "Spring Roll", "menu_section": "Imported Section"},
        )

        assert metadata["menu_section"] == "Kitchen Appetizers"
        assert metadata["category_metadata_user_set"] is True
        assert metadata["category_metadata_source"] == "Saved"

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/spring-roll",
            {
                "meal_type": cookbook_service.cookbook_category_choices()["meal_type"][1],
            },
            confirm_overwrite=True,
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor("https://example.com/spring-roll")

        assert metadata["menu_section"] == "Kitchen Appetizers"
        view = cookbook_service.cookbook_view([])
        assert "Kitchen Appetizers" in view["cookbooks"][0]["menu_section_choices"]


def test_cookbook_view_hydrates_blank_menu_sections_from_menu_store():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ), patch.object(
        menu_store_service,
        "MENU_STORE_FILE",
        Path(temp_dir) / "restaurant_menus.json",
    ):
        recipe_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-98-Chow_Mein"
        cookbook = cookbook_service.create_cookbook("Vel Asian Cuisine")
        cookbook_service.move_recipes_to_cookbook(
            cookbook["id"],
            [recipe_url],
            [{"name": "Chow Mein", "url": recipe_url}],
        )
        menu_store_service.save_menu_store({
            "restaurants": [],
            "menus": [],
            "sections": [{
                "id": "section-fried-rice",
                "section_name": "Fried Rice & Noodles",
            }, {
                "id": "section-other",
                "section_name": "Other Recipes",
            }],
            "items": [{
                "id": "item-ai-chow-mein",
                "cookbook_id": cookbook["id"],
                "menu_section_id": "section-other",
                "recipe_url": "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-98-AI-Inferred_Chow_Mein",
                "item_name": "Chow Mein",
                "menu_price": "$18.49",
            }, {
                "id": "item-chow-mein",
                "cookbook_id": "vel-asian-cusine",
                "menu_id": "menu-velasian",
                "restaurant_id": "restaurant-velasian",
                "menu_section_id": "section-fried-rice",
                "recipe_url": recipe_url,
                "item_name": "Chow Mein",
                "menu_price": "$13.99",
                "menu_description": "Egg, carrot, napa, bok choy, onion, scallion serve with sweet chili sauce.",
            }],
            "pdf_logs": [],
        })

        view = cookbook_service.cookbook_view([])
        recipe = view["cookbooks"][0]["recipes"][0]

        assert recipe["menu_section"] == "Fried Rice & Noodles"
        assert recipe["section_name"] == "Fried Rice & Noodles"
        assert recipe["menu_item_name"] == "Chow Mein"
        assert recipe["menu_price"] == "$13.99"
        assert "Fried Rice & Noodles" in view["cookbooks"][0]["menu_section_choices"]


def test_lightweight_recipe_edit_views_keep_all_hydrated_menu_section_choices():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ), patch.object(
        menu_store_service,
        "MENU_STORE_FILE",
        Path(temp_dir) / "restaurant_menus.json",
    ):
        spring_roll_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-1-Spring_Roll"
        chow_mein_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-98-Chow_Mein"
        cookbook = cookbook_service.create_cookbook("Vel Asian Cuisine")
        cookbook_service.move_recipes_to_cookbook(
            cookbook["id"],
            [spring_roll_url, chow_mein_url],
            [
                {"name": "Spring Roll", "url": spring_roll_url},
                {"name": "Chow Mein", "url": chow_mein_url},
            ],
        )
        menu_store_service.save_menu_store({
            "restaurants": [],
            "menus": [],
            "sections": [
                {"id": "section-appetizers", "section_name": "Kitchen Appetizers"},
                {"id": "section-noodles", "section_name": "Fried Rice & Noodles"},
            ],
            "items": [
                {
                    "id": "item-spring-roll",
                    "cookbook_id": cookbook["id"],
                    "menu_section_id": "section-appetizers",
                    "recipe_url": spring_roll_url,
                    "item_name": "Spring Roll",
                },
                {
                    "id": "item-chow-mein",
                    "cookbook_id": cookbook["id"],
                    "menu_section_id": "section-noodles",
                    "recipe_url": chow_mein_url,
                    "item_name": "Chow Mein",
                },
            ],
            "pdf_logs": [],
        })

        for view in (recipe_routes.recipe_edit_cookbook_view(), main_routes.lightweight_cookbook_view()):
            cookbook_view = view["cookbooks"][0]
            assert cookbook_view["recipes"] == []
            assert cookbook_view["menu_sections"] == {}
            assert cookbook_view["menu_section_choices"] == ["Kitchen Appetizers", "Fried Rice & Noodles"]


def test_lightweight_recipe_edit_views_keep_menu_snapshot_section_choices():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ), patch.object(
        menu_store_service,
        "MENU_STORE_FILE",
        Path(temp_dir) / "restaurant_menus.json",
    ), patch.object(
        menu_mega_json_service,
        "workspace_data_root",
        lambda: Path(temp_dir) / "workspace",
    ):
        source_url = "https://piscomarindy.com/Menu.html"
        recipe_url = f"{source_url}?menu_item=menu-item-20-Tallarin_Saltado"
        cookbook = cookbook_service.create_cookbook("piscomarindy")
        cookbook_service.move_recipes_to_cookbook(
            cookbook["id"],
            [recipe_url],
            [{
                "name": "Tallarin Saltado",
                "url": recipe_url,
                "menu_section": "PESCADOS Y MARISCOS",
            }],
        )
        mega_json = menu_mega_json_service.build_mega_menu_json(
            source_url,
            [
                {
                    "section_name": "APPETIZERS",
                    "items": [],
                },
                {
                    "section_name": "CEVICHE",
                    "items": [],
                },
                {
                    "section_name": "PESCADOS Y MARISCOS",
                    "items": [{"item_name": "Jalea Real", "menu_section": "PESCADOS Y MARISCOS"}],
                },
                {
                    "section_name": "CHAUFAS",
                    "items": [{"item_name": "Chaufa Amazonico", "menu_section": "CHAUFAS"}],
                },
                {
                    "section_name": "CLASICOS",
                    "items": [],
                },
                {
                    "section_name": "SALTADOS",
                    "items": [{"item_name": "Tallarin Saltado", "menu_section": "SALTADOS"}],
                },
                {
                    "section_name": "FETTUCCINE PASTAS",
                    "items": [{"item_name": "Fettuccine Pisco Mar", "menu_section": "FETTUCCINE PASTAS"}],
                },
                {
                    "section_name": "SOPA",
                    "items": [],
                },
                {
                    "section_name": "GRILL",
                    "items": [],
                },
                {
                    "section_name": "GARDEN SALAD",
                    "items": [],
                },
                {
                    "section_name": "KIDS",
                    "items": [],
                },
                {
                    "section_name": "SIDES",
                    "items": [],
                },
                {
                    "section_name": "JUGOS",
                    "items": [],
                },
                {
                    "section_name": "DESERTS",
                    "items": [],
                },
            ],
            diagnostics={"restaurant": {"restaurant_name": "Piscomar"}},
        )
        menu_mega_json_service.save_menu_mega_json_snapshot(
            mega_json,
            job_id="job-piscomar",
            cookbook_id=cookbook["id"],
            cookbook_name=cookbook["name"],
        )

        view = recipe_routes.recipe_edit_cookbook_view()
        cookbook_view = view["cookbooks"][0]

        assert cookbook_view["recipes"] == []
        assert cookbook_view["menu_sections"] == {}
        assert cookbook_view["menu_section_choices"] == [
            "APPETIZERS",
            "CEVICHE",
            "PESCADOS Y MARISCOS",
            "CHAUFAS",
            "CLASICOS",
            "SALTADOS",
            "FETTUCCINE PASTAS",
            "SOPA",
            "GRILL",
            "GARDEN SALAD",
            "KIDS",
            "SIDES",
            "JUGOS",
            "DESERTS",
        ]


def test_chatgpt_category_decision_normalizes_to_dropdown_choices():
    choices = cookbook_service.cookbook_category_choices()
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "meal_type": "Dinner",
                        "cuisine": "Italian",
                        "main_ingredient": "Pasta",
                        "cooking_method": "Oven Baked",
                        "occasion": "Family Dinner",
                        "dietary_preference": "High Protein",
                        "prep_time_group": "15-30 Minutes",
                        "custom_categories": ["Weeknight Dinners", "Comfort Food"],
                    })
                )
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: response
            )
        )
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch.object(
        recipe_edit_service,
        "get_openai_client",
        return_value=client,
    ), patch.object(recipe_edit_service, "record_openai_usage"):
        result = recipe_edit_service.decide_recipe_categories_with_chatgpt({
            "recipe_title": "Baked Stuffed Pasta",
            "prep_time": "20 min",
            "cook_time": "35 min",
            "ingredients": [
                {"ingredient": "pasta shells"},
                {"ingredient": "ricotta cheese"},
                {"ingredient": "tomato sauce"},
            ],
            "instructions": [
                {"instruction": "Stuff the pasta and bake until bubbling."},
            ],
        })

    assert result["ok"] is True
    categories = result["categories"]
    assert categories["meal_type"] == next(item for item in choices["meal_type"] if "Dinner" in item)
    assert categories["cuisine"] == next(item for item in choices["cuisine"] if "Italian" in item)
    assert categories["main_ingredient"] == next(item for item in choices["main_ingredient"] if "Pasta" in item)
    assert categories["cooking_method"] == next(item for item in choices["cooking_method"] if "Oven Baked" in item)
    assert categories["occasion"] == next(item for item in choices["occasion"] if "Family Dinner" in item)
    assert categories["dietary_preference"] == next(item for item in choices["dietary_preference"] if "High Protein" in item)
    assert categories["prep_time_group"] == next(item for item in choices["prep_time_group"] if "15" in item and "30" in item)
    assert categories["custom_categories"] == ["Weeknight Dinners", "Comfort Food"]


def test_recipe_category_inference_uses_total_time_and_keeps_vegan_out_of_main_ingredient():
    categories = cookbook_service.infer_recipe_categories({
        "name": "Vegan Enchiladas Verde with Jackfruit and White Beans",
        "prep_time": "20 min",
        "total_time": "45 min",
        "sections": {
            "INGREDIENTS": [
                {"name": "young green jackfruit"},
                {"name": "white beans"},
                {"name": "green enchilada sauce"},
            ],
        },
        "instruction_items": ["Bake the filled tortillas until hot."],
    })

    assert "Vegan" not in categories["main_ingredient"]
    assert categories["main_ingredient"] == next(
        item for item in cookbook_service.cookbook_category_choices()["main_ingredient"] if "Beans" in item
    )
    assert categories["dietary_preference"] == next(
        item for item in cookbook_service.cookbook_category_choices()["dietary_preference"] if "Vegan" in item
    )
    assert categories["prep_time_group"] == next(
        item for item in cookbook_service.cookbook_category_choices()["prep_time_group"] if "30" in item and "60" in item
    )


def test_huancaina_inference_uses_source_evidence_and_rejects_false_dietary_labels():
    payload = {
        "recipe_title": "Papas a la Huancaína",
        "description": (
            "A classic Peruvian appetizer of tender potatoes served with a creamy, "
            "mildly spicy huancaína cheese sauce."
        ),
        "menu_section": "APPETIZERS",
        "ingredients": [
            {"ingredient": "Yukon gold potatoes"},
            {"ingredient": "queso fresco"},
            {"ingredient": "evaporated milk"},
            {"ingredient": "ají amarillo paste"},
            {"ingredient": "chicken broth"},
        ],
        "instructions": [
            {"instruction": "Boil the potatoes until tender."},
            {"instruction": "Simmer the sauce in a saucepan."},
        ],
    }
    fallback = cookbook_service.infer_recipe_categories(
        recipe_edit_service.recipe_category_inference_record(payload)
    )

    assert "Appetizer" in fallback["meal_type"]
    assert "Peruvian" in fallback["cuisine"]
    assert "Potatoes" in fallback["main_ingredient"]
    assert "Stovetop / Boiled" in fallback["cooking_method"]
    assert "Flexible" in fallback["dietary_preference"]

    normalized = recipe_edit_service.normalize_chatgpt_category_decision(
        {
            "meal_type": "Dinner",
            "cuisine": "Mexican",
            "main_ingredient": "Chicken",
            "cooking_method": "One Pot",
            "occasion": "Family Dinner",
            "dietary_preference": "Low Carb",
            "prep_time_group": "15-30 Minutes",
            "custom_categories": ["Creamy", "Spicy", "Potato Dish"],
        },
        fallback,
        payload,
    )

    assert "Appetizer" in normalized["meal_type"]
    assert "Peruvian" in normalized["cuisine"]
    assert "Potatoes" in normalized["main_ingredient"]
    assert "Stovetop / Boiled" in normalized["cooking_method"]
    assert "Flexible" in normalized["dietary_preference"]
    assert normalized["custom_categories"] == ["Creamy", "Spicy", "Potato Dish"]
    assert "Low Carb" not in normalized["dietary_preference"]
    assert "Vegetarian" not in normalized["dietary_preference"]

    prompt = recipe_edit_service.build_recipe_category_decision_prompt(payload)
    assert "menu section" in prompt
    assert "meat-based broth" in prompt
    assert "Spicy as custom categories" in prompt


def test_chatgpt_category_decision_logs_and_sanitizes_vegan_and_total_time(capsys):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "meal_type": "Dinner",
                        "cuisine": "Mexican",
                        "main_ingredient": "Vegan",
                        "cooking_method": "Oven Baked",
                        "occasion": "Family Dinner",
                        "dietary_preference": "Vegan",
                        "prep_time_group": "15-30 Minutes",
                        "custom_categories": ["Comfort Food"],
                    })
                )
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: response
            )
        )
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch.object(
        recipe_edit_service,
        "get_openai_client",
        return_value=client,
    ), patch.object(recipe_edit_service, "record_openai_usage"):
        result = recipe_edit_service.decide_recipe_categories_with_chatgpt(
            {
                "source_url": "manual://recipe/test-vegan-enchiladas",
                "recipe_title": "Vegan Enchiladas Verde with White Beans",
                "prep_time": "20 min",
                "total_time": "45 min",
                "ingredients": [
                    {"ingredient": "white beans"},
                    {"ingredient": "green enchilada sauce"},
                ],
                "instructions": [
                    {"instruction": "Bake until hot."},
                ],
            },
            mode="missing",
            trigger_source="recipe_editor:missing",
            current_categories={"meal_type": "🍽️ Dinner"},
        )

    assert result["ok"] is True
    assert "Vegan" not in result["categories"]["main_ingredient"]
    assert result["categories"]["prep_time_group"] == next(
        item for item in cookbook_service.cookbook_category_choices()["prep_time_group"] if "30" in item and "60" in item
    )

    log_output = capsys.readouterr().out
    assert "[recipe_category_inference]" in log_output
    assert "manual://recipe/test-vegan-enchiladas" in log_output
    assert "recipe_editor:missing" in log_output
    assert '"meal_type"' not in log_output.split('"fields_changed":', 1)[1]
