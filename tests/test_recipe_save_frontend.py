from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def save_handler(script):
    start = script.index("async function saveRecipeEditor(event)")
    end = script.index("function recipeInferOverwriteEnabled()", start)
    return script[start:end]


def test_recipe_editor_has_one_authoritative_accessible_save_control():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    form_start = template.index('<form id="recipeEditForm"')
    form_end = template.index("</form>", form_start)
    form = template[form_start:form_end]

    assert '<form id="recipeEditForm" novalidate onsubmit="return saveRecipeEditor(event)">' in form
    assert form.count('data-recipe-edit-save\n') == 1
    assert 'id="recipeEditSaveButton"' in form
    assert 'type="submit"' in form
    assert 'data-recipe-edit-save-label>Save Recipe</span>' in form
    assert "data-recipe-edit-save-spinner" in form
    assert 'aria-busy="false"' in form
    assert 'id="recipeEditId"' in form
    assert 'id="recipeEditValidationSummary"' in form
    assert 'role="alert"' in form
    assert 'aria-live="polite"' in form

    # The restaurant dialog retains its own required-field contract; novalidate
    # prevents that hidden nested workflow from silently blocking recipe submit.
    assert 'data-restaurant-edit-field="restaurant_name" required' in form


def test_save_handler_guards_validates_and_parses_failures_safely():
    script = read_text("PushShoppingList/static/js/app.js")
    handler = save_handler(script)

    guard = handler.index('if (form.dataset.saving === "true")')
    set_saving = handler.index('form.dataset.saving = "true"')
    collect = handler.index("payload = collectRecipeEditorPayload()")
    validate = handler.index("const validation = validateRecipeEditor(form, payload)")
    pdf_prompt = handler.index("await recipePdfSaveChoiceForPayload(payload.recipe)")
    request = handler.index('fetch("/api/recipe"')

    assert guard < set_saving < collect < validate < pdf_prompt < request
    assert "setRecipeEditorSavingState(form, true)" in handler
    assert 'method: "POST"' in handler
    assert '"Content-Type": "application/json"' in handler
    assert 'credentials: "same-origin"' in handler
    assert "body: JSON.stringify(payload)" in handler
    assert "await recipeEditorJsonResponse(response)" in handler
    assert "data.ok || data.success" in handler
    assert "applyRecipeEditorServerFieldErrors(fieldErrors)" in handler
    assert "Recipe could not be saved. Your changes are still on this page." in handler
    assert "Recipe saved successfully." in handler
    assert 'recipeEditorSaveDebug("validation"' in handler
    assert 'recipeEditorSaveDebug("request"' in handler
    assert 'recipeEditorSaveDebug("response"' in handler
    assert "delete form.dataset.saving" in handler
    assert "setRecipeEditorSavingState(currentForm, false)" in handler


def test_save_validation_and_dirty_state_cover_nested_editors():
    script = read_text("PushShoppingList/static/js/app.js")

    validation = script[
        script.index("function validateRecipeEditor(form, payload)"):
        script.index("function applyRecipeEditorServerFieldErrors", script.index("function validateRecipeEditor(form, payload)"))
    ]
    assert "Enter a recipe title." in validation
    assert "Add at least one ingredient." in validation
    assert "Ingredient ${index + 1} has an invalid amount." in validation
    assert "Alternative ${optionIndex + 1}" in validation
    assert "const scope = recipeIngredientSubstitutionContainer(row) || row;" in validation
    assert "recipeIngredientOptionsMenuForRow(row)" not in validation
    assert "Add at least one instruction step." in validation
    assert "Instruction ${index + 1} needs instruction text." in validation
    assert '"step_image_url"' in validation
    assert '"step_image_prompt"' in validation
    assert "stepNumber <= 0" in validation
    assert "Equipment row ${index + 1} needs an equipment name." in validation
    assert '"equipment_image_url"' in validation
    assert '"equipment_image_prompt"' in validation
    assert "Nutrition row ${index + 1} needs a value." in validation
    assert "recipeEditorNumericExpressionIsMalformed(valueText, { allowUnitSuffix: true })" in validation
    assert '/(?:\\.\\.|,,|\\/\\/|--+)/' in script

    assert 'window.addEventListener("beforeunload"' in script
    assert 'form.dataset.recipeEditDirty = dirty ? "true" : "false"' in script
    assert 'control.dataset.ratingMode === "recipe"' in script
    assert 'updateRecipeEditorDirtyState(control.closest("#recipeEditForm"))' in script
    assert "rememberRecipeEditorSubmittedState(form, submittedSnapshot, savedIdentity)" in script
    assert "recipeEditorCurrentSaveSnapshot(form) !== savedBaselineSnapshot" in script
    assert "{ updateSourceField: false }" in script


def test_validation_reveals_invalid_nested_editor_without_restoring_other_live_edits():
    script = read_text("PushShoppingList/static/js/app.js")
    reveal = script[
        script.index("function showRecipeEditorValidationErrors"):
        script.index("function validateRecipeEditor", script.index("function showRecipeEditorValidationErrors"))
    ]
    main_edit = script[
        script.index("function setRecipeIngredientEditMode"):
        script.index("function saveRecipeIngredientInlineEdit")
    ]
    disclosure = script[
        script.index("function setRecipeIngredientSubstitutionsExpanded"):
        script.index("function toggleRecipeIngredientSubstitutions")
    ]
    alternative_edit = script[
        script.index("function setRecipeIngredientAlternativeEditMode"):
        script.index("function replaceRecipeIngredientWithAlternativeCard")
    ]

    assert reveal.count("{ restoreOtherEdits: false }") == 4
    assert "setRecipeIngredientEditMode(ingredientRow, true, { restoreOtherEdits: false });" in reveal
    assert "setRecipeInstructionEditMode(instructionRow, true, { restoreOtherEdits: false });" in reveal
    assert "const restoreOtherEdits = options.restoreOtherEdits !== false;" in main_edit
    assert "restore: restoreOtherEdits" in main_edit
    assert '!row.classList.contains("is-editing") || !panel.dataset.editSnapshot' in main_edit
    assert "const restoreOtherEdits = options.restoreOtherEdits !== false;" in disclosure
    assert disclosure.count("restore: restoreOtherEdits") >= 3
    assert "const restoreOtherEdits = options.restoreOtherEdits !== false;" in alternative_edit
    assert alternative_edit.count("restore: restoreOtherEdits") >= 2


def test_ingredient_modal_validation_is_inline_and_preserves_entered_values_on_failure():
    script = read_text("PushShoppingList/static/js/app.js")
    validation = script[
        script.index("function recipeIngredientModalFieldError"):
        script.index("function updateRecipeIngredientModalNavigation")
    ]

    assert 'error.setAttribute("role", "alert");' in validation
    assert 'input.toggleAttribute("aria-invalid", Boolean(text));' in validation
    assert "clearRecipeIngredientModalErrors(panel);" in validation
    assert 'setRecipeIngredientModalFieldError(ingredient, "Ingredient Name is required.");' in validation
    assert "canonicalizeRecipeIngredientUnitControl(unit, { allowCustom: true })" in validation
    assert "Choose a unit from the list, add a custom unit, or leave it blank." in validation
    assert 'setRecipeIngredientModalError(panel, "Review the highlighted field before saving.");' in validation
    assert 'firstInvalid.focus({ preventScroll: true });' in validation
    assert 'firstInvalid.scrollIntoView({ block: "center", behavior: "smooth" });' in validation
    assert ".value = \"\"" not in validation

    snapshots = script[
        script.index("const RECIPE_INGREDIENT_MODAL_IMMEDIATE_FIELDS"):
        script.index("function captureRecipeIngredientModalScrollState")
    ]
    assert "recipeIngredientEditableFieldSnapshot(scope)" in snapshots
    for image_field in (
        "ingredient_image_url",
        "ingredient_image_generated_at",
        "ingredient_image_prompt",
    ):
        assert f'"{image_field}"' in snapshots
    assert "RECIPE_INGREDIENT_MODAL_IMMEDIATE_FIELDS.forEach(field => delete values[field]);" in snapshots
    assert "JSON.stringify(recipeIngredientModalEditableFieldSnapshot(row)) !== panel.dataset.editSnapshot" in snapshots


def test_ingredient_modal_commit_has_single_flight_busy_and_failure_contract():
    script = read_text("PushShoppingList/static/js/app.js")
    commit = script[
        script.index("async function commitRecipeIngredientModal"):
        script.index("function updateRecipeIngredientAlternativeComponentSummary")
    ]

    guard = commit.index('panel.dataset.saving === "true"')
    set_saving = commit.index('panel.dataset.saving = "true";')
    validate = commit.index("validateRecipeIngredientModal(row, panel)")
    persist = commit.index("await persistRecipeIngredientModal(row, panel)")
    saved_guard = commit.index("if (!saved)")
    snapshot = commit.index("panel.dataset.editSnapshot = JSON.stringify(recipeIngredientModalEditableFieldSnapshot(row));")
    assert guard < set_saving < validate < persist < saved_guard < snapshot
    assert "setRecipeIngredientModalSaving(panel, true);" in commit
    assert "panel.dataset.editSnapshot = JSON.stringify(recipeIngredientModalEditableFieldSnapshot(row));" in commit
    assert "switchRecipeIngredientModal(row, nextRow)" in commit
    assert "setRecipeIngredientEditMode(row, false)" in commit
    assert "Unable to save this ingredient. Please try again." in commit
    assert "delete panel.dataset.saving;" in commit
    assert "setRecipeIngredientModalSaving(panel, false);" in commit

    saving_state = script[
        script.index("function setRecipeIngredientModalSaving"):
        script.index("function hideRecipeIngredientDiscardConfirmation")
    ]
    assert 'panel.toggleAttribute("aria-busy", Boolean(saving));' in saving_state
    assert "button.disabled = Boolean(saving)" in saving_state
    assert 'status.textContent = saving ? "Saving ingredient\\u2026" : "";' in saving_state


def test_ingredient_modal_uses_scoped_persistence_without_saving_unrelated_recipe_drafts():
    script = read_text("PushShoppingList/static/js/app.js")
    scoped_save = script[
        script.index("function recipeIngredientModalReference"):
        script.index("function updateRecipeIngredientModalNavigation")
    ]

    assert 'fetch("/api/recipe/ingredient"' in scoped_save
    assert 'credentials: "same-origin"' in scoped_save
    assert "ingredient_ref: recipeIngredientModalReference(row, panel)" in scoped_save
    assert "ingredient: recipeIngredientModalRequestItem(row)" in scoped_save
    assert "collectRecipeEditorPayload" not in scoped_save
    assert 'fetch("/api/recipe"' not in scoped_save
    assert "delete item.substitutions;" in scoped_save
    assert "delete item.substitutions_text;" in scoped_save
    assert "applyRecipeIngredientModalServerErrors(row, panel, fieldErrors);" in scoped_save
    assert "if (!response.ok || !(data.ok || data.success))" in scoped_save
    assert "return null;" in scoped_save
    assert "applySavedRecipeIngredientToModalRow(row, ingredient);" in scoped_save
    assert "rememberRecipeIngredientModalSave(row, ingredient, persistedIndex, created);" in scoped_save
    assert "invalidateRecipeEditorCache(originalUrl);" in scoped_save

    baseline = scoped_save[
        scoped_save.index("function rememberRecipeIngredientModalSave"):
        scoped_save.index("async function persistRecipeIngredientModal")
    ]
    assert "recipeEditSavedFormSnapshots.get(form)" in baseline
    assert "previousIngredient.substitutions" in baseline
    assert "savedIngredients.splice(persistedIndex, 0, baselineIngredient);" in baseline
    assert "savedIngredients[persistedIndex] = baselineIngredient;" in baseline
    assert "updateRecipeEditorDirtyState(form);" in baseline

    creation = scoped_save[
        scoped_save.index("function recipeIngredientModalReference"):
        scoped_save.index("function recipeIngredientModalRequestItem")
    ]
    assert 'row.dataset.recipeIngredientNew === "true"' in creation
    assert "recipeIngredientModalInsertionIndex(row)" in creation
    assert 'recipe_ingredient_id: create ? ""' in creation
    assert 'row.dataset.recipeIngredientNew = isNewIngredient ? "true" : "false";' in script
    assert 'row.dataset.recipeIngredientPersistedIndex = String(persistedIndex);' in script
    assert "addRecipeIngredientRow(item, { persistedIndex: index });" in script
    assert script.count("markRecipeIngredientRowsPersisted();") >= 2


def test_live_payload_preserves_nested_ids_order_and_metadata():
    script = read_text("PushShoppingList/static/js/app.js")

    for field in (
        "recipe_ingredient_id",
        "ingredient_id",
        "substitution_id",
        "instruction_id",
        "step_id",
        "equipment_id",
        "equipment_row_id",
        "row_id",
        "nutrition_id",
        "note_section_id",
    ):
        assert f'data-field="{field}"' in script

    payload = script[
        script.index("function collectRecipeEditorPayload()"):
        script.index("function recipeEditorSourceUrlForSave()")
    ]
    assert 'recipe_id: recipeId' in payload
    assert 'cover_image_prompt: coverImage.prompt || coverImage.image_prompt || ""' in payload
    assert "ingredients: collectRecipeIngredientRows()" in payload
    assert "equipment: collectRecipeEquipmentRows()" in payload
    assert "instructions: collectRecipeInstructionRows()" in payload
    assert "recipe_notes: collectRecipeNoteSections()" in payload
    assert "nutrition: collectRecipeNutritionRows()" in payload
    assert "reflection_notes: collectRecipeReflectionNotes()" in payload

    assert 'document.querySelectorAll("#recipeEditInstructions .recipe-edit-instruction-row")' in script
    assert 'document.querySelectorAll("#recipeEditEquipment .recipe-edit-equipment-row")' in script
    assert 'document.querySelectorAll("#recipeEditNutrition .recipe-edit-nutrition-row")' in script
    assert "item.substitutions = collectRecipeIngredientSubstitutionRows(row)" in script
    ingredient_collection = script[
        script.index("function collectRecipeIngredientRows"):
        script.index("function collectRecipeNutritionRows")
    ]
    assert "const item = fieldValuesFromRow(row);" in ingredient_collection
    assert "Object.assign(item, recipeIngredientMatchSnapshot(recipeIngredientMatchItemFromRow(row, item)));" in ingredient_collection
    assert "item.substitutions = collectRecipeIngredientSubstitutionRows(row);" in ingredient_collection
    assert ".filter(item => item.ingredient || item.original_text)" in ingredient_collection
    assert 'updateRecipeEditorDirtyState(parentRow ? parentRow.closest("#recipeEditForm") : null)' in script
    assert "step_id: values.step_id || \"\"" in script
    assert "row_id: values.row_id || \"\"" in script
    assert "equipment_row_id: values.equipment_row_id || \"\"" in script
    assert 'const promptText = document.getElementById("recipeEditCoverPromptText")' in script
    assert "coverImage.prompt = prompt" in script
    assert '/^(?:not available|n\\/?a|none|null)$/i' in script


def test_save_loading_validation_and_error_styles_are_visible():
    css = read_text("PushShoppingList/static/css/app.css")

    assert ".recipe-edit-validation-summary" in css
    assert '#recipeEditForm [data-recipe-edit-validation-invalid="true"]' in css
    assert ".recipe-edit-save-spinner" in css
    assert "animation: recipe-edit-save-spin" in css
    assert '.recipe-edit-save[aria-busy="true"] > .app-icon-svg' in css
    assert ".recipe-edit-save:disabled" in css


def test_inference_preview_preserves_saved_baseline_and_stays_dirty():
    script = read_text("PushShoppingList/static/js/app.js")
    populate = script[
        script.index("function populateRecipeEditor(recipe, originalUrl, options = {})"):
        script.index("function replaceRecipeEditorIngredients")
    ]
    inference = script[
        script.index("async function inferMissingRecipeDetails"):
        script.index("function rerunRecipePredictionFromMenu")
    ]

    assert "const preserveSavedState = options.preserveSavedState === true" in populate
    assert "const previousOriginalSnapshot = recipeEditOriginalSnapshot" in populate
    assert 'const previousRecipeId = document.getElementById("recipeEditId")?.value || ""' in populate
    assert 'const previousOriginalUrl = document.getElementById("recipeEditOriginalUrl")?.value || ""' in populate
    assert "recipeEditOriginalSnapshot = previousOriginalSnapshot" in populate
    assert 'setValue("recipeEditId", previousRecipeId)' in populate
    assert 'setValue("recipeEditOriginalUrl", previousOriginalUrl)' in populate
    assert "form.dataset.originalCategoryValues = previousCategoryValues" in populate
    assert "form.dataset.originalCategorySources = previousCategorySources" in populate
    assert "updateRecipeEditorDirtyState(form)" in populate
    assert "rememberRecipeEditorSavedState(form)" in populate
    assert "{ preserveSavedState: true }" in inference
    assert "Preview loaded in the editor. Save Recipe to keep it." in inference


def test_manual_pdf_creation_uses_recipe_save_lock_and_safe_save_contract():
    script = read_text("PushShoppingList/static/js/app.js")
    pdf = script[
        script.index("async function createRecipeEditorPdf(button)"):
        script.index("async function createRecipePdfForSource", script.index("async function createRecipeEditorPdf(button)"))
    ]

    guard = pdf.index('if (form.dataset.saving === "true")')
    lock = pdf.index('form.dataset.saving = "true"')
    collect = pdf.index("const payload = collectRecipeEditorPayload()")
    validate = pdf.index("const validation = validateRecipeEditor(form, payload)")
    request = pdf.index('fetch("/api/recipe"')
    assert guard < lock < collect < validate < request
    assert "setRecipeEditorSavingState(form, true)" in pdf
    assert 'credentials: "same-origin"' in pdf
    assert "await recipeEditorJsonResponse(saveResponse)" in pdf
    assert "applyRecipeEditorServerFieldErrors(fieldErrors)" in pdf
    assert "rememberRecipeEditorSubmittedState(form, submittedSnapshot, savedIdentity" in pdf
    assert "preserveCategoriesFrom: previousSavedSnapshot" in pdf
    assert "recipeEditorCurrentSaveSnapshot(form) !== savedBaselineSnapshot" in pdf
    assert "if (saveData.recipe && !changedDuringSave)" in pdf
    assert "rememberRecipeEditorFieldsAsSaved" in pdf
    assert "delete form.dataset.saving" in pdf
    assert "setRecipeEditorSavingState(currentForm, false)" in pdf
    assert "window.RECIPE_EDITOR_SAVE_DEBUG === true" in script


def test_persisted_cover_actions_update_only_cover_fields_in_dirty_baseline():
    script = read_text("PushShoppingList/static/js/app.js")
    baseline_helper = script[
        script.index("function rememberRecipeEditorFieldsAsSaved"):
        script.index("function updateRecipeEditorDirtyState", script.index("function rememberRecipeEditorFieldsAsSaved"))
    ]
    upload = script[
        script.index("async function uploadRecipeCoverImage"):
        script.index("function recipeCoverImageGenerationErrorMessage")
    ]
    generate = script[
        script.index("async function generateRecipeCoverImage"):
        script.index("async function removeRecipeCoverImage")
    ]
    remove = script[
        script.index("async function removeRecipeCoverImage"):
        script.index("function populateRecipeScalingControls")
    ]
    card_generate = script[
        script.index("async function generateRecipeTitleImageForCard"):
        script.index("async function generateRecipeImagesFromMenu")
    ]

    assert "function rememberRecipeEditorCoverImageAsSaved" in baseline_helper
    assert '[\n        "cover_image",\n        "cover_image_prompt",\n    ]' in baseline_helper
    assert "savedRecipe[field] = currentRecipe[field]" in baseline_helper
    assert "updateRecipeEditorDirtyState(form)" in baseline_helper

    for action in (upload, generate, remove, card_generate):
        assert action.index("setRecipeEditorCoverImage(") < action.index("rememberRecipeEditorCoverImageAsSaved()")

    assert script.count("rememberRecipeEditorCoverImageAsSaved();") == 4
