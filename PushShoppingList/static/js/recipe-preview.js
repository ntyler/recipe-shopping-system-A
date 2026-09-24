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

function recipePreviewIcon(name) {
    const paths = {
        back: '<path d="m12 5-7 7 7 7M5 12h15"/>',
        print: '<path d="M6 9V3h12v6M6 18H3V9h18v9h-3M6 14h12v7H6z"/><path d="M17 12h1"/>',
        pdf: '<path d="M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h8"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        minus: '<path d="M5 12h14"/>',
        clock: '<circle cx="12" cy="13" r="8"/><path d="M12 9v5l3 2M9 2h6M12 2v3"/>',
        cook: '<path d="M5 10h14v10H5zM3 10h18M8 6h8M12 3v3M2 13h3M19 13h3"/>',
        servings: '<path d="M4 3v6a3 3 0 0 0 6 0V3M7 3v18M19 3v18M19 3c-5 3-5 10 0 10"/>',
        image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1"/><path d="m3 17 5-5 4 4 4-7 5 8"/>',
        heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
        calories: '<path d="M12 2c1 6 6 7 6 13a6 6 0 0 1-12 0c0-3 2-5 3-7 0 4 2 5 3 5 2-3 2-6 0-11Z"/>',
        carbs: '<path d="M20 3C8 2 2 8 6 15s15 3 14-12ZM4 21 15 9"/>',
        protein: '<path d="M6 8h12v8H6M3 5h3v14H3zM18 5h3v14h-3zM1 9v6M23 9v6"/>',
        fat: '<path d="M12 2 6 12a7 7 0 1 0 12 0ZM8 15c0 3 2 4 4 4"/>',
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.clock}</svg>`;
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
        <form id="recipePreviewMealPanel" class="recipe-preview-meal-panel" aria-label="Add to Meal Plan" hidden>
            <h2>Add to Meal Plan</h2><fieldset><div class="recipe-preview-meal-fields">
            <label>Date<input type="date" name="date" required></label>
            <label>Meal<select name="meal_type" aria-label="Meal">${['breakfast','lunch','dinner','snack'].map(meal => `<option value="${meal}" ${meal === 'dinner' ? 'selected' : ''}>${meal[0].toUpperCase()+meal.slice(1)}</option>`).join('')}</select></label>
            <label>Planned servings<input type="number" name="planned_servings" min="1" step="any" required></label></div>
            <label>Meal-prep notes<textarea name="prep_notes" rows="2" placeholder="Notes for this scheduled meal only"></textarea></label>
            <p>Uses the saved recipe and your selected ingredient bundles.</p>
            <div class="recipe-preview-note-actions"><button type="submit">Add Meal</button><button type="button" data-preview-action="cancel-meal">Cancel</button></div>
            </fieldset><p data-preview-meal-status role="status" aria-live="polite"></p>
        </form>
        <p id="recipePreviewStatus" class="recipe-preview-status" role="status" aria-live="polite">Loading recipe preview…</p>
        <article class="recipe-preview-card" aria-label="Recipe" aria-busy="true"></article>
        <section class="recipe-preview-meal-planning" aria-labelledby="recipePreviewMealHeading">
            <div class="recipe-preview-section-heading"><h2 id="recipePreviewMealHeading">Meal Planning</h2>
                <button type="button" data-preview-action="meal-prep" aria-controls="recipePreviewBatchPanel">Plan Meal Prep</button>
                <button type="button" data-preview-action="meal-plan" aria-controls="recipePreviewMealPanel">Add to Meal Plan</button>
                <button type="button" data-preview-action="refresh-meals">Refresh</button>
                <a href="/#mealPlannerPage">View Meal Planner</a></div>
            <form id="recipePreviewBatchPanel" class="recipe-preview-meal-panel" aria-label="Plan Meal Prep" hidden>
                <h3>Plan Meal Prep</h3><p>Divide one batch across eating dates and schedule the preparation steps.</p>
                <fieldset><label>Batch servings<input name="batch_servings" type="number" min="1" step="any" required></label>
                <label>Batch prep notes<textarea name="prep_notes" rows="2" placeholder="Notes shared by this batch"></textarea></label>
                <div class="recipe-preview-section-heading"><h4>Eating dates</h4><button type="button" data-preview-action="add-allocation">Add eating date</button></div>
                <div data-preview-allocations></div><p data-preview-portion-balance aria-live="polite"></p>
                <div class="recipe-preview-section-heading"><h4>Prep timeline</h4><button type="button" data-preview-action="add-prep-step">Add prep step</button></div>
                <p>Schedule tasks such as chopping, marinating, cooking, or portioning. Each task can have its own date.</p>
                <div data-preview-prep-steps></div>
                <div class="recipe-preview-note-actions"><button type="submit">Save Meal Prep Plan</button><button type="button" data-preview-action="cancel-prep">Cancel</button></div></fieldset>
                <p data-preview-batch-status role="status" aria-live="polite"></p>
            </form>
            <p class="recipe-preview-status" data-preview-plans-status role="status" aria-live="polite"></p>
            <div data-preview-planned-meals></div>
        </section>`;
    syncRecipePreviewOptions();
    page.querySelector('[data-preview-breadcrumb]').textContent = state.draft.display_name || state.draft.recipe_title || 'Recipe';
    page.addEventListener('click', handleRecipePreviewClick);
    page.addEventListener('change', handleRecipePreviewChange);
    page.addEventListener('input', event => {
        if (event.target.matches('[data-preview-note-field]')) syncRecipePreviewNotesDraft();
        if (event.target.closest('#recipePreviewBatchPanel')) updateRecipePreviewPortionBalance();
    });
    page.querySelector('#recipePreviewMealPanel').addEventListener('submit', submitRecipePreviewMeal);
    page.querySelector('#recipePreviewBatchPanel').addEventListener('submit', submitRecipePreviewBatch);
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

function recipePreviewCuisineHtml(item) {
    const icon = item.image_url ? `<img src="${escapeAttribute(item.image_url)}" alt="" aria-hidden="true">`
        : item.glyph ? `${escapeHtml(item.glyph)} ` : '';
    return `<span class="recipe-preview-cuisine">${icon}${escapeHtml(item.label)}</span>`;
}

function renderIntegratedRecipePreview(state) {
    const r = state.model, esc = escapeHtml;
    const notesOpen = state.page.querySelector('[data-preview-notes]')?.open;
    // Browser Save as PDF uses the document title as its suggested filename.
    document.title = `${r.title.replace(/[<>:"/\\|?*]/g, '') || 'Recipe'} - AI Pantry`;
    const expandedChoices = new Set([...state.page.querySelectorAll('details[data-preview-choice][open]')].map(node => node.dataset.previewChoice));
    const favorite = document.getElementById('recipeEditFavoriteButton')?.getAttribute('aria-pressed') === 'true';
    const author = r.author && typeof r.author === 'object' ? r.author.name : r.author;
    const source = isLegitimateWebUrl(r.source_url || '') ? r.source_url : '';
    const sourceLabel = source ? new URL(source).hostname.replace(/^www\./, '') : '';
    const metrics = [['prep_time','Prep Time','clock'],['cook_time','Cook Time','cook'],['total_time','Total Time','clock'],['servings','Servings','servings']];
    const printMetadata = [['course','Course'],['cuisine','Cuisine'],['dietary_preferences','Dietary Preferences'],
        ['main_ingredient','Main Ingredient'],['cooking_method','Cooking Method'],['occasion','Occasion'],
        ['custom_tags','Custom Tags'],['prep_time_group','Prep Time Group'],['author','Author']]
        .filter(([key]) => r[key]).map(([key,label]) => `<div class="recipe-preview-metadata-field" data-field="${key}"><span class="recipe-preview-metadata-label">${label}</span><span class="recipe-preview-metadata-value">${key === 'cuisine' && r.cuisine_items?.length ? r.cuisine_items.map(recipePreviewCuisineHtml).join(', ') : esc(r[key])}</span></div>`).join('');
    state.page.querySelector('.recipe-preview-card').innerHTML = `
        <header class="recipe-preview-summary">
            <div class="recipe-preview-photo" data-preview-image>${r.image_url ? `<img src="${escapeAttribute(r.image_url)}" alt="${escapeAttribute(r.title)}">` : `<span class="recipe-preview-no-image">${recipePreviewIcon('image')}No recipe image</span>`}
                <button type="button" class="recipe-favorite-button recipe-preview-favorite" data-recipe-favorite data-recipe-url="${escapeAttribute(state.url)}" data-recipe-name="${escapeAttribute(r.title)}" aria-label="${favorite ? 'Remove from' : 'Add to'} favorites" aria-pressed="${favorite}" data-preview-action="favorite">${recipePreviewIcon('heart')}</button></div>
            <div class="recipe-preview-summary-text"><h1>${esc(r.title)}</h1>
                <div class="recipe-preview-rating" data-shared-rating-control data-rating-mode="recipe" role="radiogroup" aria-label="Recipe rating: ${currentRecipeRating()} out of 5">${[1,2,3,4,5].map(value => `<button type="button" class="recipe-edit-rating-star" data-rating-value="${value}" data-preview-rating="${value}" role="radio" aria-label="${value} star${value === 1 ? '' : 's'}" aria-checked="${currentRecipeRating() === value}">${value <= currentRecipeRating() ? '★' : '☆'}</button>`).join('')}<button type="button" class="recipe-preview-clear-rating" data-preview-rating="0" aria-label="Clear rating" ${currentRecipeRating() ? '' : 'hidden'}>Clear</button></div>
                <div class="recipe-preview-tags">${(r.tags || []).map(tag => {
                    const cuisine = r.cuisine_items?.find(item => item.source_label === tag || item.label === tag);
                    return `<span>${cuisine ? recipePreviewCuisineHtml(cuisine) : esc(tag)}</span>`;
                }).join('')}</div>
                <dl class="recipe-preview-assignment">${[['Cookbook',r.cookbook_name || 'Unassigned'],['Section',r.menu_section || 'Not specified'],['Menu Price (optional)',r.menu_price || 'Not set']].map(([label,value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>
                ${author || source ? `<p class="recipe-preview-source${source ? '' : ' recipe-preview-author-only'}">${author ? `<span class="recipe-preview-source-author">By ${esc(author)}${source ? ' · ' : ''}</span>` : ''}${source ? `<a href="${escapeAttribute(source)}" target="_blank" rel="noopener noreferrer">${esc(sourceLabel)}</a>` : ''}</p>` : ''}
                ${r.description ? `<p class="recipe-preview-description">${esc(r.description)}</p>` : ''}</div>
        </header>
        <div class="recipe-preview-metrics">${metrics.map(([key,label,icon]) => `<div>${recipePreviewIcon(icon)}<span><span>${label}</span><strong>${esc(String(r[key] || 'Not specified'))}</strong></span></div>`).join('')}</div>
        ${printMetadata ? `<div class="recipe-preview-print-metadata">${printMetadata}</div>` : ''}
        <div class="recipe-preview-columns">
            <section class="recipe-preview-ingredients"><div class="recipe-preview-section-heading"><h2>Ingredients</h2><button type="button" data-preview-action="shopping">${recipePreviewIcon('plus')}Shopping List</button></div>
                <ul>${recipePreviewIngredientsHtml(r, state.url, expandedChoices)}</ul>
            </section>
            <section class="recipe-preview-equipment"><div class="recipe-preview-section-heading"><h2>Equipment</h2></div>${recipePreviewEquipmentHtml(r, state.url)}</section>
        <section class="recipe-preview-instructions"><h2>Instructions</h2><ol>${(r.instructions || []).map((step,index) => `<li><span class="recipe-preview-step-number" aria-hidden="true">${index+1}</span><div>${step.section ? `<strong class="recipe-preview-step-section">${esc(step.section)}</strong>` : ''}${esc(step.instruction || step.text || '')}${recipePreviewInstructionMetadata(step)}</div></li>`).join('') || '<li>No instructions specified.</li>'}</ol></section>
        </div>
        <section class="recipe-preview-nutrition" data-preview-nutrition><div class="recipe-preview-section-heading"><h2>Nutrition</h2>
            <div class="recipe-preview-segment recipe-preview-nutrition-toggle" role="group" aria-label="Nutrition display">${[['per_serving','Per serving'],['whole_recipe','Whole recipe']].map(([mode,label]) => `<button type="button" data-preview-nutrition-mode="${mode}" aria-pressed="${r.nutrition_mode === mode}" ${r.nutrition_modes.includes(mode) ? '' : 'disabled'}>${label}</button>`).join('')}</div>
            <span class="recipe-preview-nutrition-yield" aria-live="polite">${esc(r.nutrition_context)}</span></div>
            ${r.nutrition_notice ? `<p class="recipe-preview-nutrition-note">${esc(r.nutrition_basis)}. ${esc(r.nutrition_notice)}</p>` : ''}${recipePreviewNutritionHtml(r)}</section>
        <details class="recipe-preview-notes" data-preview-notes ${notesOpen ? 'open' : ''}><summary>Recipe Notes</summary>
                <p>Permanent recipe notes shared with the editor. Save Notes before printing.</p>
                <fieldset ${state.notesBusy ? 'disabled' : ''}><div data-preview-note-rows>${(state.draft.recipe_notes || r.recipe_notes || []).map(recipePreviewNoteEditorHtml).join('')}</div>
                <div class="recipe-preview-note-actions"><button type="button" data-preview-action="add-note">Add note section</button><button type="button" data-preview-action="save-notes">Save Notes</button></div></fieldset>
                <p data-preview-notes-status role="status" aria-live="polite"></p>
        </details>
        <section class="recipe-preview-print-notes" data-preview-print-notes><h2>Recipe Notes</h2>${recipePreviewSavedNotesHtml(r.saved_recipe_notes || [])}</section>`;
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

function recipePreviewNoteEditorHtml(section) {
    return `<div data-preview-note-row><label>Section heading<input data-preview-note-field="heading" value="${escapeAttribute(section.heading || '')}"></label>
        <label>Notes (one per line)<textarea data-preview-note-field="items" rows="3">${escapeHtml((section.items || []).join('\n'))}</textarea></label>
        <button type="button" data-preview-action="remove-note">Remove section</button></div>`;
}

function recipePreviewSavedNotesHtml(sections) {
    return sections.map(section => `${section.heading ? `<h3>${escapeHtml(section.heading)}</h3>` : ''}<ul>${section.items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`).join('');
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
        ${meal.prep_notes ? `<p class="recipe-preview-prep-notes"><strong>Meal-prep notes</strong>${esc(meal.prep_notes)}</p>` : ''}</li>`;
}

function recipePreviewMealPlansHtml(result) {
    const esc = escapeHtml, batches = result.batches || [], meals = result.meals || [];
    const grouped = new Set(batches.map(batch => batch.id));
    const singleMeals = meals.filter(meal => !grouped.has(meal.batch_id));
    if (!batches.length && !meals.length) return '<p class="recipe-preview-empty">This recipe has no planned meals yet. Plan meal prep across several days or add a single meal.</p>';
    const plans = batches.map(batch => {
        const allocations = batch.allocations || meals.filter(meal => meal.batch_id === batch.id);
        const steps = [...(batch.prep_steps || [])].sort((a, b) => a.date.localeCompare(b.date));
        return `<section class="recipe-preview-batch" aria-label="Meal prep batch">
            <div class="recipe-preview-section-heading"><h3>Meal prep · ${esc(String(batch.batch_servings))} servings</h3>
                <button type="button" data-preview-action="remove-batch" data-batch-id="${escapeAttribute(batch.id)}">Remove plan</button></div>
            <p class="recipe-preview-batch-balance">${esc(String(batch.allocated_servings))} servings planned · ${esc(String(batch.remaining_servings))} unassigned</p>
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

function recipePreviewAllocationRow(date = recipePreviewToday(), servings = '') {
    return `<div class="recipe-preview-allocation" data-preview-allocation>
        <label>Eating date<input data-allocation-field="date" type="date" value="${escapeAttribute(date)}" required></label>
        <label>Meal<select data-allocation-field="meal_type">${['breakfast','lunch','dinner','snack'].map(meal => `<option value="${meal}" ${meal === 'dinner' ? 'selected' : ''}>${meal[0].toUpperCase()+meal.slice(1)}</option>`).join('')}</select></label>
        <label>Servings<input data-allocation-field="planned_servings" type="number" min="1" step="any" value="${escapeAttribute(String(servings))}" required></label>
        <button type="button" data-preview-action="remove-allocation" aria-label="Remove eating date">Remove</button>
        <label class="recipe-preview-allocation-notes">Meal notes (optional)<input data-allocation-field="prep_notes" placeholder="Notes for this eating date"></label></div>`;
}

function recipePreviewPrepRow() {
    return `<div class="recipe-preview-prep-row" data-preview-prep-row>
        <label>Prep date<input data-prep-field="date" type="date" value="${recipePreviewToday()}" required></label>
        <label>Prep task<input data-prep-field="instruction" placeholder="e.g. Chop vegetables" maxlength="2000" required></label>
        <button type="button" data-preview-action="remove-prep-step" aria-label="Remove prep step">Remove</button></div>`;
}

function openRecipePreviewBatchPanel() {
    const state = integratedRecipePreview;
    if (!state?.projectionReady) return;
    const form = state.page.querySelector('#recipePreviewBatchPanel');
    if (!state.batchDraftInitialized) {
        const servings = Math.max(1, recipeEditServingsParts(state.model.servings).number || 1);
        form.elements.batch_servings.value = servings;
        form.querySelector('[data-preview-allocations]').innerHTML = recipePreviewAllocationRow(recipePreviewToday(), servings);
        state.batchDraftInitialized = true;
    }
    form.hidden = false;
    updateRecipePreviewPortionBalance();
    form.scrollIntoView({block: 'start'});
    form.elements.batch_servings.focus({preventScroll: true});
}

function recipePreviewBatchPayload(form, state) {
    return {recipe_url:state.url, batch_servings:Number(form.elements.batch_servings.value), prep_notes:form.elements.prep_notes.value,
        ingredient_option_selections:state.selections,
        allocations:[...form.querySelectorAll('[data-preview-allocation]')].map(row => Object.fromEntries(
            [...row.querySelectorAll('[data-allocation-field]')].map(input => [input.dataset.allocationField, input.dataset.allocationField === 'planned_servings' ? Number(input.value) : input.value]))),
        prep_steps:[...form.querySelectorAll('[data-preview-prep-row]')].map(row => Object.fromEntries(
            [...row.querySelectorAll('[data-prep-field]')].map(input => [input.dataset.prepField, input.value])))};
}

function updateRecipePreviewPortionBalance() {
    const form = integratedRecipePreview?.page.querySelector('#recipePreviewBatchPanel');
    if (!form) return;
    const total = Number(form.elements.batch_servings.value);
    const used = [...form.querySelectorAll('[data-allocation-field="planned_servings"]')].reduce((sum, input) => sum + (Number(input.value) || 0), 0);
    const remaining = Math.round((total - used) * 10000) / 10000;
    form.querySelector('[data-preview-portion-balance]').textContent = remaining < 0
        ? `${used} of ${total || 0} servings planned — reduce the portions or increase the batch by ${-remaining}.`
        : `${used} of ${total || 0} servings planned · ${remaining} unassigned`;
    form.elements.batch_servings.setCustomValidity(remaining < 0 ? 'Planned portions exceed the batch servings.' : '');
}

async function submitRecipePreviewBatch(event) {
    event.preventDefault();
    const state = integratedRecipePreview, form = event.currentTarget;
    if (!state?.projectionReady || state.batchBusy) return;
    updateRecipePreviewPortionBalance();
    if (!form.reportValidity()) return;
    const payload = recipePreviewBatchPayload(form, state), status = form.querySelector('[data-preview-batch-status]');
    if (!payload.allocations.length) { status.textContent = 'Add at least one eating date.'; return; }
    state.batchBusy = true;
    form.querySelector('fieldset').disabled = true;
    status.textContent = 'Saving meal prep plan…';
    try {
        const response = await fetch('/api/meal-plan/batches', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to save this meal prep plan.');
        form.reset();
        state.batchDraftInitialized = false;
        form.querySelector('[data-preview-allocations]').replaceChildren();
        form.querySelector('[data-preview-prep-steps]').replaceChildren();
        status.textContent = '';
        if (integratedRecipePreview === state) {
            form.hidden = true;
            await refreshRecipePreviewMeals(state);
            state.page.querySelector('[data-preview-action="meal-prep"]').focus();
        }
    } catch (error) { status.textContent = error.message; }
    finally { state.batchBusy = false; form.querySelector('fieldset').disabled = false; }
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
        if (integratedRecipePreview !== state) return;
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
    } catch (error) { state.page.querySelector('[data-preview-plans-status]').textContent = error.message; }
    finally { button.disabled = false; }
}

function openRecipePreviewMealPanel() {
    const state = integratedRecipePreview;
    if (!state?.projectionReady) return;
    const form = state.page.querySelector('#recipePreviewMealPanel');
    if (!form.elements.date.value) {
        const today = new Date();
        form.elements.date.value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    }
    form.elements.planned_servings.value = Math.max(1, recipeEditServingsParts(state.model.servings).number || 1);
    form.hidden = false;
    form.scrollIntoView({block:'nearest'});
    form.elements.date.focus();
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

async function submitRecipePreviewMeal(event) {
    event.preventDefault();
    const state = integratedRecipePreview, form = event.currentTarget;
    if (!state?.projectionReady || state.mealBusy || !form.reportValidity()) return;
    const data = new FormData(form), status = form.querySelector('[data-preview-meal-status]');
    state.mealBusy = true;
    form.querySelector('fieldset').disabled = true;
    status.textContent = 'Adding meal…';
    try {
        const response = await fetch('/api/meal-plan', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
            recipe_url:state.url, date:data.get('date'), meal_type:data.get('meal_type'), planned_servings:Number(data.get('planned_servings')),
            prep_notes:data.get('prep_notes'), ingredient_option_selections:state.selections,
        })});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to add this meal.');
        status.textContent = 'Meal added. ';
        const link = document.createElement('a');
        link.href = `/?meal_week=${encodeURIComponent(data.get('date'))}#mealPlannerPage`;
        link.textContent = 'View Meal Planner';
        status.append(link);
        if (integratedRecipePreview === state) {
            await refreshRecipePreviewMeals(state);
            form.hidden = true;
            const section = state.page.querySelector('.recipe-preview-meal-planning');
            section.scrollIntoView({block: 'start'});
            section.querySelector('[data-preview-action="meal-plan"]').focus({preventScroll: true});
        }
    } catch (error) { status.textContent = error.message; }
    finally { state.mealBusy = false; form.querySelector('fieldset').disabled = false; }
}

function recipePreviewIngredientsHtml(recipe, url, expandedChoices = new Set()) {
    const ingredientRow = (item, index, active = true) => {
        const key = `ingredient|${url}|${item.requirement_id || index}|${item.option_id || ''}|${item.component_index ?? index}`;
        const notes = [...new Set([item.preparation,item.notes].filter(Boolean))].join(' · ');
        const typeKey = recipeIngredientTypeKey(recipeIngredientTypeValue(item));
        const type = typeKey === 'main' ? '' : recipeIngredientTypeLabel(item);
        const typeBadge = type ? `<span class="recipe-preview-ingredient-type" aria-label="Type: ${escapeAttribute(type)}">${escapeHtml(type)}</span>` : '';
        const buyAs = item.buy_as_label ? `<small class="recipe-preview-buy-as">(Buy as: ${escapeHtml(item.buy_as_label)})</small>` : '';
        return `<li class="${active ? 'recipe-task-row' : 'recipe-preview-option-item'}" data-preview-ingredient-type="${escapeAttribute(typeKey)}">${active ? `<input type="checkbox" class="recipe-task-check" aria-label="Mark ${escapeAttribute(item.ingredient)} as prepared" data-task-key="${escapeAttribute(key)}">` : ''}<div class="${active ? 'recipe-task-text' : 'recipe-preview-option-text'}"><span class="recipe-preview-amount">${escapeHtml([item.quantity,item.unit].filter(value => value != null && String(value).trim() !== '').join(' '))}</span><span>${escapeHtml(item.ingredient)}${buyAs}${typeBadge}${notes ? `<small>${escapeHtml(notes)}</small>` : ''}</span></div></li>`;
    };
    return (recipe.ingredient_groups || []).map(group => {
        const rows = group.items.map(ingredientRow).join('');
        if (!group.is_choice) return rows;
        const options = group.options.map((option, index) => {
            const selected = option.id === group.selected_option_id;
            return `<div class="recipe-preview-choice-option" data-selected="${selected}"><label class="recipe-preview-option-heading" title="Choose this bundle as the recipe default"><input type="radio" name="preview-choice-${escapeAttribute(group.requirement_id)}" value="${escapeAttribute(option.id)}" data-preview-choice-option data-preview-requirement="${escapeAttribute(group.requirement_id)}" ${selected ? 'checked' : ''}><span>Bundle ${index + 1}</span>${option.is_default ? '<small class="recipe-preview-option-selected">Default</small>' : ''}</label><ul>${option.items.map((item, itemIndex) => ingredientRow(item, itemIndex, selected)).join('')}</ul></div>`;
        }).join('');
        return `<li class="recipe-preview-choice-group"><input type="checkbox" data-preview-choice-check aria-label="Mark all selected ingredients for ${escapeAttribute(group.source_text)} as prepared"><details data-preview-choice="${escapeAttribute(group.requirement_id)}" ${expandedChoices.has(group.requirement_id) ? 'open' : ''}>
            <summary title="Expand to compare bundles and choose one bundle."><span class="recipe-preview-choice-title">${escapeHtml(group.source_text)}</span><span class="recipe-preview-choice-count">${group.options.length} bundles</span><span class="recipe-preview-choice-chevron" aria-hidden="true">›</span></summary>
            <div class="recipe-preview-choice-options" role="radiogroup" aria-label="Choose one bundle for ${escapeAttribute(group.source_text)}">${options}</div></details></li>`;
    }).join('') || '<li>No ingredients specified.</li>';
}

function recipePreviewEquipmentHtml(recipe, url) {
    if (!recipe.equipment?.length) return '<p class="recipe-preview-empty">No equipment specified.</p>';
    return `<ul>${recipe.equipment.map(item => `<li class="recipe-task-row"><input type="checkbox" class="recipe-task-check" aria-label="Mark ${escapeAttribute(item.name)} as ready" data-task-key="${escapeAttribute(`equipment|${url}|${item.id}`)}"><span class="recipe-task-text">${escapeHtml(item.name)}</span></li>`).join('')}</ul>`;
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

function recipePreviewInstructionMetadata(step) {
    const equipment = Array.isArray(step.equipment_used) ? step.equipment_used.filter(value => typeof value === 'string').join(', ') : '';
    const values = [step.time ? `Time: ${step.time}` : '', step.temperature ? `Temp: ${step.temperature}` : '', equipment ? `Uses: ${equipment}` : ''].filter(Boolean);
    return values.length ? `<small class="recipe-preview-step-meta">${escapeHtml(values.join(' · '))}</small>` : '';
}

function recipePreviewNutritionHtml(recipe) {
    if (!recipe.nutrition?.length) return '<p class="recipe-preview-empty">Nutrition is not available for this recipe.</p>';
    const summary = recipe.nutrition_summary, esc = escapeHtml;
    const printRows = [...summary.primary.filter(row => row.value), ...summary.groups.flatMap(group => group.rows)];
    return `<div class="recipe-preview-nutrient-grid">${summary.primary.map(row => `<div>${recipePreviewIcon(row.icon)}<span><strong>${esc(row.value || 'Not provided')}</strong><span>${esc(row.label)}</span></span></div>`).join('')}</div>
        <div class="recipe-preview-nutrient-details">${summary.groups.map(group => `<section class="recipe-preview-nutrient-group"><h3>${esc(group.label)}</h3><dl>${group.rows.map(row => `<div><dt>${esc(row.label)}</dt><dd>${esc(row.value)}</dd></div>`).join('')}</dl></section>`).join('')}</div>
        <p class="recipe-preview-print-nutrition">${printRows.map(row => `<span>${esc(row.label)}: ${esc(row.value)}</span>`).join(' | ')}</p>
        <p class="recipe-preview-nutrition-note">${esc(summary.note)}</p>`;
}

function syncRecipePreviewOptions() {
    const state = integratedRecipePreview;
    if (!state) return;
    state.page.querySelectorAll('[data-preview-option]').forEach(input => {
        input.checked = state.options[input.dataset.previewOption];
    });
    state.page.querySelector('[data-preview-image]')?.toggleAttribute('hidden', !state.options.show_image);
    state.page.querySelector('[data-preview-nutrition]')?.toggleAttribute('hidden', !state.options.show_nutrition);
    state.page.querySelector('.recipe-preview-summary')?.classList.toggle('without-image', !state.options.show_image);
    state.page.querySelector('.recipe-preview-card').dataset.textSize = state.options.text_size;
    state.page.querySelector('.recipe-preview-card').dataset.printBundleInfo = state.options.print_bundle_info !== false;
    state.page.querySelector('[data-preview-print-notes]')?.toggleAttribute('hidden', !state.options.print_notes || !state.model?.saved_recipe_notes?.length);
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
        case 'meal-prep': return openRecipePreviewBatchPanel();
        case 'remove-batch': return removeRecipePreviewBatch(button);
        case 'cancel-prep':
            state.page.querySelector('#recipePreviewBatchPanel').hidden = true;
            state.page.querySelector('[data-preview-action="meal-prep"]').focus();
            break;
        case 'add-allocation': {
            const rows = state.page.querySelector('[data-preview-allocations]');
            rows.insertAdjacentHTML('beforeend', recipePreviewAllocationRow());
            rows.lastElementChild.querySelector('input').focus();
            updateRecipePreviewPortionBalance();
            break;
        }
        case 'remove-allocation':
            button.closest('[data-preview-allocation]').remove();
            updateRecipePreviewPortionBalance();
            state.page.querySelector('[data-preview-action="add-allocation"]').focus();
            break;
        case 'add-prep-step': {
            const rows = state.page.querySelector('[data-preview-prep-steps]');
            rows.insertAdjacentHTML('beforeend', recipePreviewPrepRow());
            rows.lastElementChild.querySelector('input').focus();
            break;
        }
        case 'remove-prep-step':
            button.closest('[data-preview-prep-row]').remove();
            state.page.querySelector('[data-preview-action="add-prep-step"]').focus();
            break;
        case 'refresh-meals': return refreshRecipePreviewMeals();
        case 'cancel-meal':
            state.page.querySelector('#recipePreviewMealPanel').hidden = true;
            state.page.querySelector('[data-preview-action="meal-plan"]').focus();
            break;
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
