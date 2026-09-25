/* Preview shares the mounted editor's draft. Changes persist through Save Recipe. */
let integratedRecipePreview = null;

const RECIPE_PREVIEW_SAVED_OPTIONS = ['show_image', 'show_nutrition', 'print_bundle_info', 'print_notes'];

function recipePreviewPreferencesKey() {
    return `recipe-preview-options:${document.body.dataset.viewerUserId || 'local'}`;
}

function loadRecipePreviewPreferences() {
    let saved;
    try {
        saved = JSON.parse(localStorage.getItem(recipePreviewPreferencesKey()));
    } catch (_) { /* Keep defaults when browser storage is unavailable or invalid. */ }
    return Object.fromEntries(RECIPE_PREVIEW_SAVED_OPTIONS.map(key =>
        [key, typeof saved?.[key] === 'boolean' ? saved[key] : key !== 'print_notes']));
}

function saveRecipePreviewPreferences(options) {
    try {
        localStorage.setItem(recipePreviewPreferencesKey(), JSON.stringify(
            Object.fromEntries(RECIPE_PREVIEW_SAVED_OPTIONS.map(key => [key, options[key]]))));
    } catch (_) { /* The controls still work when browser storage is unavailable. */ }
}

function recipePreviewRequest(state = integratedRecipePreview) {
    return {url: state.url, recipe: state.draft, options: {...state.options},
        ...(state.selections ? {ingredient_option_selections: state.selections} : {})};
}

function recipePreviewStatus(message, error = false) {
    const target = document.getElementById('recipePreviewStatus');
    if (!target) return;
    target.textContent = message;
    target.classList.toggle('is-error', error);
    target.setAttribute('role', error ? 'alert' : 'status');
}

async function openIntegratedRecipePreview({history = true} = {}) {
    if (integratedRecipePreview) return;
    const form = document.getElementById('recipeEditForm');
    if (!form || form.dataset.saving === 'true') {
        setRecipeEditStatus('Please wait for the recipe save to finish.', true);
        return;
    }
    const collected = collectRecipeEditorPayload();
    if (!collected.original_url) return setRecipeEditStatus('Unable to preview recipe: missing recipe URL.', true);
    const page = document.createElement('section');
    page.id = 'recipePreviewPage';
    page.className = 'recipe-preview-page';
    page.setAttribute('aria-label', 'Recipe Preview');
    const content = document.getElementById('appContent');
    const hidden = [...content.children, document.getElementById('recipeEditModal')]
        .filter((node, index, nodes) => node && nodes.indexOf(node) === index)
        .map(node => ({node, hidden: node.hidden, inert: node.inert}));
    const state = integratedRecipePreview = {
        url: collected.original_url,
        draft: {...(recipeEditOriginalSnapshot || {}), ...collected.recipe,
            ...collectRecipeEditorCategoryValues(),
            cookbook_name: document.getElementById('recipeEditCookbookField')?.dataset.currentCookbookName || ''},
        options: {scale: currentRecipeEditScaleMultiplier(), ...loadRecipePreviewPreferences(), text_size: 'normal', nutrition_mode: 'per_serving'},
        hidden, page, trigger: document.activeElement, title: document.title,
        contentLabel: content.getAttribute('aria-label'), scroll: content.scrollTop,
        shellScroll: document.querySelector('[data-app-main-shell]')?.scrollTop || 0,
        requestId: 0, model: null,
    };
    hidden.forEach(({node}) => { node.hidden = true; node.inert = true; });
    content.appendChild(page);
    content.setAttribute('aria-label', 'Recipe preview');
    document.body.classList.add('recipe-preview-active');
    document.title = 'Recipe Preview · AI Pantry';
    if (history) window.history.pushState({recipePreview: true}, '', '#recipe-preview');
    page.innerHTML = `<div class="recipe-preview-heading">
        <nav aria-label="Breadcrumb"><a href="/#currentRecipeUrlLogCard">Recipes</a><span>/</span><span data-preview-breadcrumb></span><span>/</span><strong>Recipe Preview</strong></nav>
        <div class="recipe-preview-actions"><button type="button" data-preview-action="back">${recipePreviewIcon('back')}Back to Editor</button><button type="button" data-preview-action="pdf" disabled>${recipePreviewIcon('pdf')}Download PDF</button><button type="button" data-preview-action="print" class="is-primary" disabled>${recipePreviewIcon('print')}Print</button></div>
        </div>
        <div class="recipe-preview-options" aria-label="Preview options">
            <div class="recipe-preview-visibility"><label><input type="checkbox" data-preview-option="show_image" checked>Recipe image</label><label><input type="checkbox" data-preview-option="show_nutrition" checked>Nutrition</label><label><input type="checkbox" data-preview-option="print_bundle_info" checked>Print Bundle Info</label><label><input type="checkbox" data-preview-option="print_notes">Print Notes</label></div>
            <div class="recipe-preview-control"><label for="recipePreviewServings">Servings</label><div class="recipe-preview-segment"><button type="button" data-preview-action="less" aria-label="Decrease servings">${recipePreviewIcon('minus')}</button><input id="recipePreviewServings" type="number" min="0.01" step="any" aria-label="Servings" disabled><button type="button" data-preview-action="more" aria-label="Increase servings">${recipePreviewIcon('plus')}</button></div></div>
            <div class="recipe-preview-control"><span>Scale</span><div class="recipe-preview-segment" role="group" aria-label="Recipe scale">${[1,2,3].map(scale => `<button type="button" data-preview-scale="${scale}" aria-pressed="false">${scale}x</button>`).join('')}</div></div>
            <div class="recipe-preview-control"><span>Text size</span><div class="recipe-preview-segment" role="group" aria-label="Recipe text size">${['smaller','normal','larger'].map((size,index) => `<button type="button" data-preview-size="${size}" aria-label="${size[0].toUpperCase()+size.slice(1)} text" aria-pressed="${size === 'normal'}">${['A−','A','A+'][index]}</button>`).join('')}</div></div>
        </div>
        <form id="recipePreviewMealPanel" class="recipe-preview-meal-panel" aria-label="Add to Meal Plan" hidden></form>
        <p id="recipePreviewStatus" class="recipe-preview-status" role="status" aria-live="polite">Loading recipe preview…</p>
        <article class="recipe-preview-card" aria-label="Recipe" aria-busy="true"></article>
        <section class="recipe-preview-meal-planning" aria-labelledby="recipePreviewMealHeading">
            <div class="recipe-preview-section-heading"><h2 id="recipePreviewMealHeading">Meal Planning</h2>
                <button type="button" data-preview-action="meal-plan" aria-controls="recipePreviewMealPanel">Add to Meal Plan</button>
                <button type="button" data-preview-action="refresh-meals">Refresh</button>
                <a href="/#mealPlannerPage">View Meal Planner</a></div>
            <p class="recipe-preview-status" data-preview-plans-status role="status" aria-live="polite"></p>
            <div data-preview-planned-meals></div>
        </section>`;
    syncRecipePreviewOptions();
    page.querySelector('[data-preview-breadcrumb]').textContent = state.draft.display_name || state.draft.recipe_title || 'Recipe';
    page.addEventListener('click', handleRecipePreviewClick);
    page.addEventListener('change', handleRecipePreviewChange);
    page.addEventListener('input', event => {
        if (event.target.matches('[data-preview-note-field]')) syncRecipePreviewNotesDraft();
    });
    page.addEventListener('keydown', event => {
        const rating = event.target.closest('[data-preview-rating]');
        if (rating && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
            event.preventDefault();
            const next = event.key === 'Home' ? 1 : event.key === 'End' ? 5
                : Math.max(1, Math.min(5, Number(rating.dataset.previewRating) + (event.key === 'ArrowRight' ? 1 : -1)));
            page.querySelector(`[data-preview-rating="${next}"]`).click();
            page.querySelector(`[data-preview-rating="${next}"]`).focus();
        }
    });
    content.scrollTop = 0;
    document.querySelector('[data-app-main-shell]')?.scrollTo(0, 0);
    page.querySelector('[data-preview-action="back"]').focus({preventScroll: true});
    await Promise.all([refreshIntegratedRecipePreview(), refreshRecipePreviewMeals(state)]);
}

function closeIntegratedRecipePreview({history = true} = {}) {
    const state = integratedRecipePreview;
    if (!state) return;
    integratedRecipePreview = null;
    state.abort?.abort();
    state.mealsAbort?.abort();
    state.hidden.forEach(({node, hidden, inert}) => { node.hidden = hidden; node.inert = inert; });
    state.page.remove();
    document.body.classList.remove('recipe-preview-active');
    document.title = state.title;
    document.getElementById('appContent').scrollTop = state.scroll;
    if (state.contentLabel === null) document.getElementById('appContent').removeAttribute('aria-label');
    else document.getElementById('appContent').setAttribute('aria-label', state.contentLabel);
    document.querySelector('[data-app-main-shell]')?.scrollTo(0, state.shellScroll);
    state.trigger?.focus({preventScroll: true});
    if (history && window.history.state?.recipePreview) window.history.back();
}

async function refreshIntegratedRecipePreview() {
    const state = integratedRecipePreview;
    if (!state) return;
    state.abort?.abort();
    state.abort = new AbortController();
    const requestId = ++state.requestId;
    state.projectionReady = false;
    state.page.querySelector('.recipe-preview-card').setAttribute('aria-busy', 'true');
    state.page.querySelectorAll('[data-preview-action="pdf"], [data-preview-action="print"], [data-preview-action="shopping"]').forEach(button => { button.disabled = true; });
    try {
        const response = await fetch('/api/recipe_preview', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(recipePreviewRequest(state)), signal: state.abort.signal});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to load recipe preview.');
        if (integratedRecipePreview !== state || requestId !== state.requestId) return;
        state.model = data.recipe;
        state.selections = data.ingredient_option_selections;
        state.projectionReady = true;
        const nutritionFocus = document.activeElement?.dataset.previewNutritionMode;
        const choiceFocus = document.activeElement?.matches('[data-preview-choice-option]') ? {requirement: document.activeElement.dataset.previewRequirement, option: document.activeElement.value} : null;
        renderIntegratedRecipePreview(state);
        if (nutritionFocus) state.page.querySelector(`[data-preview-nutrition-mode="${nutritionFocus}"]`)?.focus({preventScroll: true});
        if (choiceFocus) [...state.page.querySelectorAll('[data-preview-choice-option]')].find(node => node.dataset.previewRequirement === choiceFocus.requirement && node.value === choiceFocus.option)?.focus({preventScroll: true});
        recipePreviewStatus('');
        state.page.querySelector('[data-preview-action="pdf"]').disabled = Boolean(state.pdfBusy);
        state.page.querySelector('[data-preview-action="print"]').disabled = false;
        state.page.querySelector('[data-preview-action="shopping"]').disabled = Boolean(state.shoppingBusy);
    } catch (error) {
        if (error.name !== 'AbortError' && integratedRecipePreview === state) recipePreviewStatus(error.message, true);
    } finally {
        if (integratedRecipePreview === state && requestId === state.requestId) state.page.querySelector('.recipe-preview-card').setAttribute('aria-busy', 'false');
    }
}

function renderIntegratedRecipePreview(state) {
    const r = state.model;
    const notesOpen = state.page.querySelector('[data-preview-notes]')?.open;
    // Browser Save as PDF uses the document title as its suggested filename.
    document.title = `${r.title.replace(/[<>:"/\\|?*]/g, '') || 'Recipe'} - AI Pantry`;
    const expandedChoices = new Set([...state.page.querySelectorAll('details[data-preview-choice][open]')].map(node => node.dataset.previewChoice));
    const favorite = document.getElementById('recipeEditFavoriteButton')?.getAttribute('aria-pressed') === 'true';
    state.page.querySelector('.recipe-preview-card').innerHTML = recipePreviewCardHtml(r, {
        url: state.url, notesOpen, expandedChoices, favorite, rating: currentRecipeRating(),
        recipeNotes: state.draft.recipe_notes, notesBusy: state.notesBusy,
    });
    const input = state.page.querySelector('#recipePreviewServings');
    const title = state.page.querySelector('.recipe-preview-summary h1');
    title.insertAdjacentHTML('afterend', '<button type="button" class="recipe-preview-plan-button" data-preview-action="meal-plan" aria-controls="recipePreviewMealPanel">Add to Meal Plan</button>');
    const servings = recipeEditServingsParts(r.servings).number;
    input.value = Number.isFinite(servings) ? servings : '';
    input.disabled = !(recipeEditServingsParts(r.base_servings).number > 0);
    input.title = input.disabled ? 'Set the base servings in Recipe Information to adjust servings.' : '';
    state.page.querySelectorAll('[data-preview-action="less"], [data-preview-action="more"]').forEach(button => { button.disabled = input.disabled; });
    const image = state.page.querySelector('[data-preview-image] img');
    if (image) image.addEventListener('error', () => { image.hidden = true; });
    updateSharedRatingControl(state.page.querySelector('[data-shared-rating-control]'), currentRecipeRating());
    setRecipeFavoriteButtonState(state.page.querySelector('[data-recipe-favorite]'), favorite);
    syncRecipePreviewOptions();
    bindRecipeTaskChecks();
    syncRecipePreviewChoiceChecks(state.page);
}

function syncRecipePreviewNotesDraft() {
    const state = integratedRecipePreview;
    if (!state) return;
    const sections = [...state.page.querySelectorAll('[data-preview-note-row]')].map(row => ({
        heading: row.querySelector('[data-preview-note-field="heading"]').value.trim(),
        items: normalizeRecipeNoteItemsForEditor(row.querySelector('[data-preview-note-field="items"]').value),
    }));
    state.draft.recipe_notes = sections;
    replaceRecipeEditorRecipeNotes(sections);
    state.page.querySelector('[data-preview-notes-status]').textContent = 'Unsaved notes. Print uses the last saved notes.';
}

async function saveRecipePreviewNotes() {
    const state = integratedRecipePreview;
    if (!state || state.notesBusy) return;
    syncRecipePreviewNotesDraft();
    state.notesBusy = true;
    state.page.querySelector('[data-preview-notes] fieldset').disabled = true;
    state.page.querySelector('[data-preview-notes-status]').textContent = 'Saving notes…';
    try {
        const response = await fetch('/api/recipe/notes', {method: 'PATCH', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({url: state.url, recipe_notes: state.draft.recipe_notes, expected_notes: state.model.saved_recipe_notes})});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to save recipe notes.');
        // Update the mounted editor even if the reader returned there during the request.
        if (recipeEditorCurrentUrl() === state.url) {
            replaceRecipeEditorRecipeNotes(data.recipe_notes);
            if (recipeEditOriginalSnapshot) recipeEditOriginalSnapshot.recipe_notes = normalizeRecipeNoteSectionsSnapshot(data.recipe_notes);
            rememberRecipeEditorFieldsAsSaved(document.getElementById('recipeEditForm'), ['recipe_notes']);
            updateRecipeEditorDirtyState();
        }
        state.draft.recipe_notes = data.recipe_notes;
        state.model.saved_recipe_notes = data.recipe_notes;
        if (integratedRecipePreview === state) {
            state.notesBusy = false;
            renderIntegratedRecipePreview(state);
            state.page.querySelector('[data-preview-notes-status]').textContent = 'Notes saved.';
        }
    } catch (error) {
        if (integratedRecipePreview === state) state.page.querySelector('[data-preview-notes-status]').textContent = error.message;
    } finally {
        state.notesBusy = false;
        if (integratedRecipePreview === state) state.page.querySelector('[data-preview-notes] fieldset').disabled = false;
    }
}

function recipePreviewPlanDate(value) {
    return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {weekday:'short', year:'numeric', month:'short', day:'numeric'});
}

function recipePreviewToday() {
    const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
}

function recipePreviewPlannedMealHtml(meal) {
    const esc = escapeHtml, mealName = meal.meal_type[0].toUpperCase() + meal.meal_type.slice(1);
    return `<li><div class="recipe-preview-planned-meal-summary"><strong><time datetime="${escapeAttribute(meal.date)}">${esc(recipePreviewPlanDate(meal.date))}</time> · ${esc(mealName)}</strong>
        <span>${meal.planned_servings ? `${esc(String(meal.planned_servings))} servings` : 'Servings not set'}</span>
        <a href="/?meal_week=${encodeURIComponent(meal.date)}#mealPlannerPage">View in Meal Planner</a></div>
        ${recipePreviewFamilyPortionsHtml(meal)}
        ${meal.prep_notes ? `<p class="recipe-preview-prep-notes"><strong>Meal-prep notes</strong>${esc(meal.prep_notes)}</p>` : ''}</li>`;
}

function recipePreviewFamilyPortionsHtml(meal) {
    if (!meal.member_portions?.length) return '';
    return `<details class="recipe-preview-family-portions"><summary>Family portions (${meal.member_portions.length})</summary><ul>${meal.member_portions.map(member => `<li><span>${escapeHtml(member.name || member.name_snapshot || 'Family member')}</span><span>${escapeHtml(String(member.servings))} ${Number(member.servings) === 1 ? 'serving' : 'servings'}</span></li>`).join('')}</ul></details>`;
}

function recipePreviewMealPlansHtml(result) {
    const esc = escapeHtml, batches = result.batches || [], meals = result.meals || [];
    const grouped = new Set(batches.map(batch => batch.id));
    const singleMeals = meals.filter(meal => !grouped.has(meal.batch_id));
    if (!batches.length && !meals.length) return '<p class="recipe-preview-empty">This recipe has no planned meals yet. Use Add to Meal Plan to choose dates, meals, and portions.</p>';
    const plans = batches.map(batch => {
        const allocations = batch.allocations || meals.filter(meal => meal.batch_id === batch.id);
        const steps = [...(batch.prep_steps || [])].sort((a, b) => a.date.localeCompare(b.date));
        return `<section class="recipe-preview-batch" aria-label="Meal prep batch">
            <div class="recipe-preview-section-heading"><h3>Meal prep · ${esc(String(batch.batch_servings))} servings</h3>
                <button type="button" data-preview-action="remove-batch" data-batch-id="${escapeAttribute(batch.id)}">Remove plan</button></div>
            <p class="recipe-preview-batch-balance">${esc(String(batch.allocated_servings))} servings planned · ${esc(String(batch.remaining_servings))} unassigned</p>
            ${batch.member_totals?.length ? `<p class="recipe-preview-batch-balance">${batch.member_totals.map(member => `${esc(member.name || member.name_snapshot || 'Family member')}: ${esc(String(member.servings))} servings`).join(' · ')}</p>` : ''}
            ${batch.prep_notes ? `<p class="recipe-preview-prep-notes"><strong>Batch prep notes</strong>${esc(batch.prep_notes)}</p>` : ''}
            <div class="recipe-preview-batch-columns"><div><h4>Prep timeline</h4>
                ${steps.length ? `<ul class="recipe-preview-prep-timeline">${steps.map(step => `<li class="${step.completed ? 'is-complete' : ''}">
                    <label><input type="checkbox" data-preview-prep-check data-batch-id="${escapeAttribute(batch.id)}" data-step-id="${escapeAttribute(step.id)}" ${step.completed ? 'checked' : ''}>
                    <span><time datetime="${escapeAttribute(step.date)}">${esc(recipePreviewPlanDate(step.date))}</time><span class="recipe-preview-prep-instruction">${esc(step.instruction)}</span></span></label>
                    <a href="/?meal_week=${encodeURIComponent(step.date)}#mealPlannerPage">View day</a></li>`).join('')}</ul>` : '<p class="recipe-preview-empty">No prep steps scheduled.</p>'}</div>
                <div><h4>Eating dates</h4>${allocations.length ? `<ul class="recipe-preview-planned-meals">${allocations.map(recipePreviewPlannedMealHtml).join('')}</ul>` : '<p class="recipe-preview-empty">No eating dates remain in this plan.</p>'}</div></div></section>`;
    }).join('');
    return plans + (singleMeals.length ? `${batches.length ? '<h3>Other scheduled meals</h3>' : ''}<ul class="recipe-preview-planned-meals">${singleMeals.map(recipePreviewPlannedMealHtml).join('')}</ul>` : '');
}

async function toggleRecipePreviewPrepStep(input) {
    const state = integratedRecipePreview, completed = input.checked;
    if (!state || input.disabled) return;
    input.disabled = true;
    const status = state.page.querySelector('[data-preview-plans-status]');
    try {
        const response = await fetch(`/api/meal-plan/batches/${encodeURIComponent(input.dataset.batchId)}/prep-steps/${encodeURIComponent(input.dataset.stepId)}`, {
            method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({completed})});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to save this prep step.');
        if (integratedRecipePreview !== state) {
            if (typeof refreshMealPlannerWorkspace === 'function') await refreshMealPlannerWorkspace();
            return;
        }
        // A Refresh may have replaced the clicked row while its save was pending.
        // Cancel any older read and update the currently mounted checkbox.
        state.mealsAbort?.abort();
        state.page.querySelectorAll('[data-preview-prep-check]').forEach(current => {
            if (current.dataset.batchId === input.dataset.batchId && current.dataset.stepId === input.dataset.stepId) {
                current.checked = completed;
                current.closest('li').classList.toggle('is-complete', completed);
            }
        });
        status.textContent = completed ? 'Prep step completed.' : 'Prep step reopened.';
        if (typeof refreshMealPlannerWorkspace === 'function') await refreshMealPlannerWorkspace();
    } catch (error) { input.checked = !completed; status.textContent = error.message; }
    finally { input.disabled = false; }
}

async function removeRecipePreviewBatch(button) {
    const state = integratedRecipePreview;
    if (!state || button.disabled || !window.confirm('Remove this meal prep plan, its prep steps, and all its scheduled meals?')) return;
    button.disabled = true;
    try {
        const response = await fetch(`/api/meal-plan/batches/${encodeURIComponent(button.dataset.batchId)}`, {method:'DELETE'});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to remove this plan.');
        if (integratedRecipePreview === state) await refreshRecipePreviewMeals(state);
        if (typeof refreshMealPlannerWorkspace === 'function') await refreshMealPlannerWorkspace();
    } catch (error) { state.page.querySelector('[data-preview-plans-status]').textContent = error.message; }
    finally { button.disabled = false; }
}

function openRecipePreviewMealPanel() {
    const state = integratedRecipePreview;
    if (!state?.projectionReady) return;
    if (!state.mealPanel) {
        state.mealPanel = new MealPlanPanel(state.page.querySelector('#recipePreviewMealPanel'), {
            today: recipePreviewToday(),
            servings: recipeEditServingsParts(state.model.servings).number || 1,
            title: state.model.title,
            getContext: () => integratedRecipePreview === state && state.projectionReady
                ? {recipe_url:state.url, ingredient_option_selections:state.selections} : null,
            onCancel: () => state.page.querySelector('[data-preview-action="meal-plan"]')?.focus(),
            onMembersChanged: async () => {
                if (integratedRecipePreview === state) await refreshRecipePreviewMeals(state);
                if (typeof refreshMealPlannerWorkspace === 'function') await refreshMealPlannerWorkspace();
            },
            onSaved: async (_result, date) => {
                if (integratedRecipePreview === state) {
                    await refreshRecipePreviewMeals(state);
                    const section = state.page.querySelector('.recipe-preview-meal-planning');
                    section.scrollIntoView({block:'start'});
                    section.querySelector('[data-preview-action="meal-plan"]').focus({preventScroll:true});
                }
                if (typeof refreshMealPlannerWorkspace === 'function') await refreshMealPlannerWorkspace({date});
            },
        });
    }
    return state.mealPanel.open();
}

async function refreshRecipePreviewMeals(state = integratedRecipePreview) {
    if (!state) return;
    state.mealsAbort?.abort();
    const abort = state.mealsAbort = new AbortController();
    const status = state.page.querySelector('[data-preview-plans-status]');
    status.textContent = 'Loading planned meals…';
    try {
        const response = await fetch(`/api/meal-plan?recipe_url=${encodeURIComponent(state.url)}`, {signal: abort.signal});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to load planned meals. Use Refresh to try again.');
        if (integratedRecipePreview !== state || abort.signal.aborted) return;
        state.page.querySelector('[data-preview-planned-meals]').innerHTML = recipePreviewMealPlansHtml(result);
        status.textContent = '';
    } catch (error) {
        if (integratedRecipePreview === state && !abort.signal.aborted) status.textContent = error.message;
    }
}

function syncRecipePreviewChoiceChecks(scope) {
    if (!scope) return;
    const groups = scope.matches('.recipe-preview-choice-group') ? [scope] : scope.querySelectorAll('.recipe-preview-choice-group');
    groups.forEach(group => {
        const checkbox = group.querySelector('[data-preview-choice-check]');
        const items = [...group.querySelectorAll('.recipe-task-check')];
        const checked = items.filter(item => item.checked).length;
        checkbox.checked = items.length > 0 && checked === items.length;
        checkbox.indeterminate = checked > 0 && checked < items.length;
        checkbox.disabled = items.length === 0;
        group.querySelector('.recipe-preview-choice-title').classList.toggle('checked-item-text', checkbox.checked);
    });
}

function syncRecipePreviewOptions() {
    const state = integratedRecipePreview;
    if (!state) return;
    state.page.querySelectorAll('[data-preview-option]').forEach(input => {
        input.checked = state.options[input.dataset.previewOption];
    });
    recipePreviewApplyPrintOptions(state.page, state.options, state.model);
    state.page.querySelectorAll('[data-preview-scale]').forEach(button => button.setAttribute('aria-pressed', Number(button.dataset.previewScale) === state.options.scale ? 'true' : 'false'));
    state.page.querySelectorAll('[data-preview-size]').forEach(button => button.setAttribute('aria-pressed', button.dataset.previewSize === state.options.text_size ? 'true' : 'false'));
}

async function handleRecipePreviewChange(event) {
    const state = integratedRecipePreview;
    if (!state) return;
    if (event.target.matches('[data-preview-prep-check]')) return toggleRecipePreviewPrepStep(event.target);
    if (event.target.matches('[data-preview-choice-option]') && event.target.checked) {
        const requirementId = event.target.dataset.previewRequirement;
        const optionId = event.target.value;
        const rows = recipeEditIngredientRows().filter(row => {
            const values = fieldValuesFromRow(row);
            return values.ingredient || values.original_text;
        });
        const row = rows.find(row => {
            const values = fieldValuesFromRow(row);
            return String(values.ingredient_requirement_id || values.recipe_ingredient_id || values.row_id || values.id || '') === requirementId;
        }) || rows[state.model.ingredient_groups.findIndex(group => group.requirement_id === requirementId)];
        // Reuse the editor handler so parent/default/preferred flags and all
        // ingredient views agree, including legacy rows without explicit IDs.
        if (!applyRecipeIngredientOptionSelection(row, optionId)) {
            renderIntegratedRecipePreview(state);
            recipePreviewStatus('Unable to change this bundle. Please choose its default in the editor.', true);
            return;
        }
        state.draft.ingredients = collectRecipeIngredientRows();
        state.selections = {...state.selections, [requirementId]: optionId};
        await refreshIntegratedRecipePreview();
        if (integratedRecipePreview === state && state.projectionReady) recipePreviewStatus('Default bundle updated. Use Back to Editor, then Save Recipe to keep this change.');
        return;
    }
    if (event.target.matches('[data-preview-choice-check]')) {
        const group = event.target.closest('.recipe-preview-choice-group');
        const checked = event.target.checked;
        group.querySelectorAll('.recipe-task-check').forEach(item => {
            if (item.checked === checked) return;
            item.checked = checked;
            item.dispatchEvent(new Event('change', {bubbles: true}));
        });
        syncRecipePreviewChoiceChecks(group);
        return;
    }
    if (event.target.matches('.recipe-task-check')) {
        syncRecipePreviewChoiceChecks(event.target.closest('.recipe-preview-choice-group'));
        return;
    }
    if (event.target.dataset.previewOption) {
        state.options[event.target.dataset.previewOption] = event.target.checked;
        saveRecipePreviewPreferences(state.options);
        syncRecipePreviewOptions();
    } else if (event.target.id === 'recipePreviewServings') {
        const servings = Number(event.target.value), base = recipeEditServingsParts(state.model?.base_servings).number;
        if (servings > 0 && base > 0 && servings / base <= 1000) {
            state.options.scale = servings / base;
            refreshIntegratedRecipePreview();
        } else {
            event.target.value = recipeEditServingsParts(state.model?.servings).number || '';
            recipePreviewStatus('Enter a positive serving count within 1000x the original recipe.', true);
        }
    }
}

async function handleRecipePreviewClick(event) {
    const state = integratedRecipePreview;
    const button = event.target.closest('button');
    if (!state || !button) return;
    if (button.hasAttribute('data-preview-scale')) {
        state.options.scale = Number(button.dataset.previewScale);
        return refreshIntegratedRecipePreview();
    }
    if (button.dataset.previewSize) {
        state.options.text_size = button.dataset.previewSize;
        return syncRecipePreviewOptions();
    }
    if (button.dataset.previewNutritionMode) {
        state.options.nutrition_mode = button.dataset.previewNutritionMode;
        return refreshIntegratedRecipePreview();
    }
    if (button.hasAttribute('data-preview-rating')) {
        setRecipeRating(button.dataset.previewRating);
        state.draft.rating = currentRecipeRating();
        updateSharedRatingControl(state.page.querySelector('[data-shared-rating-control]'), currentRecipeRating());
        state.page.querySelector('[data-preview-rating="0"]').hidden = !currentRecipeRating();
        return;
    }
    switch (button.dataset.previewAction) {
        case 'back': return closeIntegratedRecipePreview();
        case 'meal-plan': return openRecipePreviewMealPanel();
        case 'remove-batch': return removeRecipePreviewBatch(button);
        case 'refresh-meals': return refreshRecipePreviewMeals();
        case 'add-note':
            state.page.querySelector('[data-preview-note-rows]').insertAdjacentHTML('beforeend', recipePreviewNoteEditorHtml({heading: '', items: []}));
            state.page.querySelector('[data-preview-note-rows]').lastElementChild.querySelector('input').focus();
            break;
        case 'remove-note':
            button.closest('[data-preview-note-row]').remove();
            syncRecipePreviewNotesDraft();
            break;
        case 'save-notes': return saveRecipePreviewNotes();
        case 'favorite': return toggleRecipeFavorite(button, event);
        case 'less': case 'more': {
            const input = state.page.querySelector('#recipePreviewServings');
            input.value = Math.max(0.01, Number(input.value) + (button.dataset.previewAction === 'more' ? 1 : -1));
            input.dispatchEvent(new Event('change', {bubbles: true}));
            break;
        }
        case 'print': window.print(); break;
        case 'pdf': case 'shopping': await performRecipePreviewAction(button); break;
    }
}

async function performRecipePreviewAction(button) {
    const state = integratedRecipePreview;
    if (!state?.model) return;
    const pdf = button.dataset.previewAction === 'pdf';
    state[pdf ? 'pdfBusy' : 'shoppingBusy'] = true;
    button.disabled = true;
    recipePreviewStatus(pdf ? 'Preparing PDF…' : 'Adding ingredients to your shopping list…');
    try {
        const response = await fetch(pdf ? '/api/recipe_preview/pdf' : '/api/recipe_preview/shopping-list', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(recipePreviewRequest(state))});
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Unable to complete this action.');
        }
        if (pdf) {
            const blobUrl = URL.createObjectURL(await response.blob());
            const anchor = document.createElement('a');
            anchor.href = blobUrl;
            anchor.download = `${state.model.title.replace(/[<>:"/\\|?*]/g, '') || 'Recipe'} - AI Pantry.pdf`;
            anchor.click();
            setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
            if (integratedRecipePreview === state) recipePreviewStatus('PDF downloaded.');
        } else {
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'Unable to add ingredients.');
            if (integratedRecipePreview === state) recipePreviewStatus(data.message || 'Ingredients added to your shopping list.');
        }
    } catch (error) {
        if (integratedRecipePreview === state) recipePreviewStatus(error.message, true);
    } finally {
        state[pdf ? 'pdfBusy' : 'shoppingBusy'] = false;
        if (integratedRecipePreview === state) {
            state.page.querySelector(`[data-preview-action="${pdf ? 'pdf' : 'shopping'}"]`).disabled = !state.projectionReady;
        }
    }
}

window.addEventListener('popstate', () => {
    if (integratedRecipePreview && !window.history.state?.recipePreview) closeIntegratedRecipePreview({history: false});
    else if (!integratedRecipePreview && window.history.state?.recipePreview && document.getElementById('recipeEditForm')) openIntegratedRecipePreview({history: false});
});

// Printed recipes include the actual selected ingredients even when the screen
// uses compact, collapsed groups. Restore the reader's choices after printing.
window.addEventListener('beforeprint', () => {
    const state = integratedRecipePreview;
    if (!state || state.printChoices) return;
    state.printChoices = [...state.page.querySelectorAll('details[data-preview-choice]')].map(node => ({node, open: node.open}));
    state.printChoices.forEach(({node}) => { node.open = true; });
});
window.addEventListener('afterprint', () => {
    const state = integratedRecipePreview;
    state?.printChoices?.forEach(({node, open}) => { node.open = open; });
    if (state) delete state.printChoices;
});
