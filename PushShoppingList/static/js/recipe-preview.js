/* Preview shares the mounted editor's draft. Changes persist through Save Recipe. */
let integratedRecipePreview = null;

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
        options: {scale: currentRecipeEditScaleMultiplier(), show_image: true, show_nutrition: true, text_size: 'normal', nutrition_mode: 'per_serving'},
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
            <div class="recipe-preview-visibility"><label><input type="checkbox" data-preview-option="show_image" checked>Recipe image</label><label><input type="checkbox" data-preview-option="show_nutrition" checked>Nutrition</label></div>
            <div class="recipe-preview-control"><label for="recipePreviewServings">Servings</label><div class="recipe-preview-segment"><button type="button" data-preview-action="less" aria-label="Decrease servings">${recipePreviewIcon('minus')}</button><input id="recipePreviewServings" type="number" min="0.01" step="any" aria-label="Servings" disabled><button type="button" data-preview-action="more" aria-label="Increase servings">${recipePreviewIcon('plus')}</button></div></div>
            <div class="recipe-preview-control"><span>Scale</span><div class="recipe-preview-segment" role="group" aria-label="Recipe scale">${[1,2,3].map(scale => `<button type="button" data-preview-scale="${scale}" aria-pressed="false">${scale}x</button>`).join('')}</div></div>
            <div class="recipe-preview-control"><span>Text size</span><div class="recipe-preview-segment" role="group" aria-label="Recipe text size">${['smaller','normal','larger'].map((size,index) => `<button type="button" data-preview-size="${size}" aria-label="${size[0].toUpperCase()+size.slice(1)} text" aria-pressed="${size === 'normal'}">${['A−','A','A+'][index]}</button>`).join('')}</div></div>
        </div>
        <p id="recipePreviewStatus" class="recipe-preview-status" role="status" aria-live="polite">Loading recipe preview…</p>
        <article class="recipe-preview-card" aria-label="Recipe" aria-busy="true"></article>`;
    page.querySelector('[data-preview-breadcrumb]').textContent = state.draft.display_name || state.draft.recipe_title || 'Recipe';
    page.addEventListener('click', handleRecipePreviewClick);
    page.addEventListener('change', handleRecipePreviewChange);
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
    await refreshIntegratedRecipePreview();
}

function closeIntegratedRecipePreview({history = true} = {}) {
    const state = integratedRecipePreview;
    if (!state) return;
    integratedRecipePreview = null;
    state.abort?.abort();
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
    const r = state.model, esc = escapeHtml;
    const expandedChoices = new Set([...state.page.querySelectorAll('details[data-preview-choice][open]')].map(node => node.dataset.previewChoice));
    const favorite = document.getElementById('recipeEditFavoriteButton')?.getAttribute('aria-pressed') === 'true';
    const author = r.author && typeof r.author === 'object' ? r.author.name : r.author;
    const source = isLegitimateWebUrl(r.source_url || '') ? r.source_url : '';
    const sourceLabel = source ? new URL(source).hostname.replace(/^www\./, '') : '';
    const metrics = [['prep_time','Prep Time','clock'],['cook_time','Cook Time','cook'],['total_time','Total Time','clock'],['servings','Servings','servings']];
    state.page.querySelector('.recipe-preview-card').innerHTML = `
        <header class="recipe-preview-summary">
            <div class="recipe-preview-photo" data-preview-image>${r.image_url ? `<img src="${escapeAttribute(r.image_url)}" alt="${escapeAttribute(r.title)}">` : `<span class="recipe-preview-no-image">${recipePreviewIcon('image')}No recipe image</span>`}
                <button type="button" class="recipe-favorite-button recipe-preview-favorite" data-recipe-favorite data-recipe-url="${escapeAttribute(state.url)}" data-recipe-name="${escapeAttribute(r.title)}" aria-label="${favorite ? 'Remove from' : 'Add to'} favorites" aria-pressed="${favorite}" data-preview-action="favorite">${recipePreviewIcon('heart')}</button></div>
            <div class="recipe-preview-summary-text"><h1>${esc(r.title)}</h1>
                <div class="recipe-preview-rating" data-shared-rating-control data-rating-mode="recipe" role="radiogroup" aria-label="Recipe rating: ${currentRecipeRating()} out of 5">${[1,2,3,4,5].map(value => `<button type="button" class="recipe-edit-rating-star" data-rating-value="${value}" data-preview-rating="${value}" role="radio" aria-label="${value} star${value === 1 ? '' : 's'}" aria-checked="${currentRecipeRating() === value}">${value <= currentRecipeRating() ? '★' : '☆'}</button>`).join('')}<button type="button" class="recipe-preview-clear-rating" data-preview-rating="0" aria-label="Clear rating" ${currentRecipeRating() ? '' : 'hidden'}>Clear</button></div>
                <div class="recipe-preview-tags">${(r.tags || []).map(tag => `<span>${esc(tag)}</span>`).join('')}</div>
                <dl class="recipe-preview-assignment">${[['Cookbook',r.cookbook_name || 'Unassigned'],['Section',r.menu_section || 'Not specified'],['Menu Price (optional)',r.menu_price || 'Not set']].map(([label,value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>
                ${author || source ? `<p class="recipe-preview-source">${author ? `By ${esc(author)}` : ''}${author && source ? ' · ' : ''}${source ? `<a href="${escapeAttribute(source)}" target="_blank" rel="noopener noreferrer">${esc(sourceLabel)}</a>` : ''}</p>` : ''}
                ${r.description ? `<p class="recipe-preview-description">${esc(r.description)}</p>` : ''}</div>
        </header>
        <div class="recipe-preview-metrics">${metrics.map(([key,label,icon]) => `<div>${recipePreviewIcon(icon)}<span><span>${label}</span><strong>${esc(String(r[key] || 'Not specified'))}</strong></span></div>`).join('')}</div>
        <div class="recipe-preview-columns">
            <section class="recipe-preview-ingredients"><div class="recipe-preview-section-heading"><h2>Ingredients</h2><button type="button" data-preview-action="shopping">${recipePreviewIcon('plus')}Shopping List</button></div>
                <ul>${recipePreviewIngredientsHtml(r, state.url, expandedChoices)}</ul>
            </section>
            <section class="recipe-preview-instructions"><h2>Instructions</h2><ol>${(r.instructions || []).map((step,index) => `<li><span class="recipe-preview-step-number" aria-hidden="true">${index+1}</span><div>${step.section ? `<strong class="recipe-preview-step-section">${esc(step.section)}</strong>` : ''}${esc(step.instruction || step.text || '')}${recipePreviewInstructionMetadata(step)}</div></li>`).join('') || '<li>No instructions specified.</li>'}</ol></section>
        </div>
        <section class="recipe-preview-nutrition" data-preview-nutrition><div class="recipe-preview-section-heading"><h2>Nutrition</h2>
            <div class="recipe-preview-segment recipe-preview-nutrition-toggle" role="group" aria-label="Nutrition display">${[['per_serving','Per serving'],['whole_recipe','Whole recipe']].map(([mode,label]) => `<button type="button" data-preview-nutrition-mode="${mode}" aria-pressed="${r.nutrition_mode === mode}" ${r.nutrition_modes.includes(mode) ? '' : 'disabled'}>${label}</button>`).join('')}</div>
            <span class="recipe-preview-nutrition-yield" aria-live="polite">${esc(r.nutrition_context)}</span></div>
            ${r.nutrition_notice ? `<p class="recipe-preview-nutrition-note">${esc(r.nutrition_basis)}. ${esc(r.nutrition_notice)}</p>` : ''}${recipePreviewNutritionHtml(r)}</section>`;
    const input = state.page.querySelector('#recipePreviewServings');
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

function recipePreviewIngredientsHtml(recipe, url, expandedChoices = new Set()) {
    const ingredientRow = (item, index, active = true) => {
        const key = `ingredient|${url}|${item.requirement_id || index}|${item.option_id || ''}|${item.component_index ?? index}`;
        const notes = [...new Set([item.preparation,item.notes].filter(Boolean))].join(' · ');
        const type = recipeIngredientTypeKey(recipeIngredientTypeValue(item)) === 'main' ? '' : recipeIngredientTypeLabel(item);
        const typeBadge = type ? `<span class="recipe-preview-ingredient-type" aria-label="Type: ${escapeAttribute(type)}">${escapeHtml(type)}</span>` : '';
        return `<li class="${active ? 'recipe-task-row' : 'recipe-preview-option-item'}">${active ? `<input type="checkbox" class="recipe-task-check" aria-label="Mark ${escapeAttribute(item.ingredient)} as prepared" data-task-key="${escapeAttribute(key)}">` : ''}<div class="${active ? 'recipe-task-text' : 'recipe-preview-option-text'}"><span class="recipe-preview-amount">${escapeHtml([item.quantity,item.unit].filter(value => value != null && String(value).trim() !== '').join(' '))}</span><span>${escapeHtml(item.ingredient)}${typeBadge}${notes ? `<small>${escapeHtml(notes)}</small>` : ''}</span></div></li>`;
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
    return `<div class="recipe-preview-nutrient-grid">${summary.primary.map(row => `<div>${recipePreviewIcon(row.icon)}<span><strong>${esc(row.value || 'Not provided')}</strong><span>${esc(row.label)}</span></span></div>`).join('')}</div>
        <div class="recipe-preview-nutrient-details">${summary.groups.map(group => `<section class="recipe-preview-nutrient-group"><h3>${esc(group.label)}</h3><dl>${group.rows.map(row => `<div><dt>${esc(row.label)}</dt><dd>${esc(row.value)}</dd></div>`).join('')}</dl></section>`).join('')}</div>
        <p class="recipe-preview-nutrition-note">${esc(summary.note)}</p>`;
}

function syncRecipePreviewOptions() {
    const state = integratedRecipePreview;
    if (!state) return;
    state.page.querySelector('[data-preview-image]')?.toggleAttribute('hidden', !state.options.show_image);
    state.page.querySelector('[data-preview-nutrition]')?.toggleAttribute('hidden', !state.options.show_nutrition);
    state.page.querySelector('.recipe-preview-summary')?.classList.toggle('without-image', !state.options.show_image);
    state.page.querySelector('.recipe-preview-card').dataset.textSize = state.options.text_size;
    state.page.querySelectorAll('[data-preview-scale]').forEach(button => button.setAttribute('aria-pressed', Number(button.dataset.previewScale) === state.options.scale ? 'true' : 'false'));
    state.page.querySelectorAll('[data-preview-size]').forEach(button => button.setAttribute('aria-pressed', button.dataset.previewSize === state.options.text_size ? 'true' : 'false'));
}

async function handleRecipePreviewChange(event) {
    const state = integratedRecipePreview;
    if (!state) return;
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
            anchor.download = `${state.model.title.replace(/[<>:"/\\|?*]/g, '') || 'Recipe'}.pdf`;
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
