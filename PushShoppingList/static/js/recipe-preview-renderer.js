/* One recipe template for the live preview, browser Print, and Download PDF.
 * Pure markup helpers deliberately have no dependency on the mounted editor.
 * The PDF service executes this trusted asset with its validated preview model.
 */
function recipePreviewEscapeHtml(value) {
    return String(value || '').replace(/[&<>]/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;'}[character]));
}

function recipePreviewEscapeAttribute(value) {
    return recipePreviewEscapeHtml(value).replace(/"/g, '&quot;');
}

function recipePreviewWebUrl(value) {
    try {
        const url = new URL(String(value || '').trim());
        return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname);
    } catch (_) { return false; }
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

function recipePreviewCuisineHtml(item) {
    const icon = item.image_url ? `<img src="${recipePreviewEscapeAttribute(item.image_url)}" alt="" aria-hidden="true">`
        : item.glyph ? `${recipePreviewEscapeHtml(item.glyph)} ` : '';
    return `<span class="recipe-preview-cuisine">${icon}${recipePreviewEscapeHtml(item.label)}</span>`;
}

function recipePreviewNoteEditorHtml(section) {
    return `<div data-preview-note-row><label>Section heading<input data-preview-note-field="heading" value="${recipePreviewEscapeAttribute(section.heading || '')}"></label>
        <label>Notes (one per line)<textarea data-preview-note-field="items" rows="3">${recipePreviewEscapeHtml((section.items || []).join('\n'))}</textarea></label>
        <button type="button" data-preview-action="remove-note">Remove section</button></div>`;
}

function recipePreviewSavedNotesHtml(sections) {
    return sections.map(section => `${section.heading ? `<h3>${recipePreviewEscapeHtml(section.heading)}</h3>` : ''}<ul>${section.items.map(item => `<li>${recipePreviewEscapeHtml(item)}</li>`).join('')}</ul>`).join('');
}

function recipePreviewIngredientsHtml(recipe, url, expandedChoices = new Set()) {
    const ingredientRow = (item, index, active = true) => {
        const key = `ingredient|${url}|${item.requirement_id || index}|${item.option_id || ''}|${item.component_index ?? index}`;
        const notes = [...new Set([item.preparation,item.notes].filter(Boolean))].join(' · ');
        const typeKey = item.ingredient_type_key || String(item.section || item.ingredient_type || (item.optional ? 'optional' : 'main')).trim().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
        const type = typeKey === 'main' ? '' : (item.ingredient_type_label || item.section || item.ingredient_type || typeKey);
        const typeBadge = type ? `<span class="recipe-preview-ingredient-type" aria-label="Type: ${recipePreviewEscapeAttribute(type)}">${recipePreviewEscapeHtml(type)}</span>` : '';
        const buyAs = item.buy_as_label ? `<small class="recipe-preview-buy-as">(Buy as: ${recipePreviewEscapeHtml(item.buy_as_label)})</small>` : '';
        return `<li class="${active ? 'recipe-task-row' : 'recipe-preview-option-item'}" data-preview-ingredient-type="${recipePreviewEscapeAttribute(typeKey)}">${active ? `<input type="checkbox" class="recipe-task-check" aria-label="Mark ${recipePreviewEscapeAttribute(item.ingredient)} as prepared" data-task-key="${recipePreviewEscapeAttribute(key)}">` : ''}<div class="${active ? 'recipe-task-text' : 'recipe-preview-option-text'}"><span class="recipe-preview-amount">${recipePreviewEscapeHtml([item.quantity,item.unit].filter(value => value != null && String(value).trim() !== '').join(' '))}</span><span>${recipePreviewEscapeHtml(item.ingredient)}${buyAs}${typeBadge}${notes ? `<small>${recipePreviewEscapeHtml(notes)}</small>` : ''}</span></div></li>`;
    };
    return (recipe.ingredient_groups || []).map(group => {
        const rows = group.items.map(ingredientRow).join('');
        if (!group.is_choice) return rows;
        const options = group.options.map((option, index) => {
            const selected = option.id === group.selected_option_id;
            return `<div class="recipe-preview-choice-option" data-selected="${selected}"><label class="recipe-preview-option-heading" title="Choose this bundle as the recipe default"><input type="radio" name="preview-choice-${recipePreviewEscapeAttribute(group.requirement_id)}" value="${recipePreviewEscapeAttribute(option.id)}" data-preview-choice-option data-preview-requirement="${recipePreviewEscapeAttribute(group.requirement_id)}" ${selected ? 'checked' : ''}><span>Bundle ${index + 1}</span>${option.is_default ? '<small class="recipe-preview-option-selected">Default</small>' : ''}</label><ul>${option.items.map((item, itemIndex) => ingredientRow(item, itemIndex, selected)).join('')}</ul></div>`;
        }).join('');
        return `<li class="recipe-preview-choice-group"><input type="checkbox" data-preview-choice-check aria-label="Mark all selected ingredients for ${recipePreviewEscapeAttribute(group.source_text)} as prepared"><details data-preview-choice="${recipePreviewEscapeAttribute(group.requirement_id)}" ${expandedChoices.has(group.requirement_id) ? 'open' : ''}>
            <summary title="Expand to compare bundles and choose one bundle."><span class="recipe-preview-choice-title">${recipePreviewEscapeHtml(group.source_text)}</span><span class="recipe-preview-choice-count">${group.options.length} bundles</span><span class="recipe-preview-choice-chevron" aria-hidden="true">›</span></summary>
            <div class="recipe-preview-choice-options" role="radiogroup" aria-label="Choose one bundle for ${recipePreviewEscapeAttribute(group.source_text)}">${options}</div></details></li>`;
    }).join('') || '<li>No ingredients specified.</li>';
}

function recipePreviewEquipmentHtml(recipe, url) {
    if (!recipe.equipment?.length) return '<p class="recipe-preview-empty">No equipment specified.</p>';
    return `<ul>${recipe.equipment.map(item => `<li class="recipe-task-row"><input type="checkbox" class="recipe-task-check" aria-label="Mark ${recipePreviewEscapeAttribute(item.name)} as ready" data-task-key="${recipePreviewEscapeAttribute(`equipment|${url}|${item.id}`)}"><span class="recipe-task-text">${recipePreviewEscapeHtml(item.name)}</span></li>`).join('')}</ul>`;
}

function recipePreviewInstructionMetadata(step) {
    const equipment = Array.isArray(step.equipment_used) ? step.equipment_used.filter(value => typeof value === 'string').join(', ') : '';
    const values = [step.time ? `Time: ${step.time}` : '', step.temperature ? `Temp: ${step.temperature}` : '', equipment ? `Uses: ${equipment}` : ''].filter(Boolean);
    return values.length ? `<small class="recipe-preview-step-meta">${recipePreviewEscapeHtml(values.join(' · '))}</small>` : '';
}

function recipePreviewNutritionHtml(recipe) {
    if (!recipe.nutrition?.length) return '<p class="recipe-preview-empty">Nutrition is not available for this recipe.</p>';
    const summary = recipe.nutrition_summary, esc = recipePreviewEscapeHtml;
    const printRows = [...summary.primary.filter(row => row.value), ...summary.groups.flatMap(group => group.rows)];
    return `<div class="recipe-preview-nutrient-grid">${summary.primary.map(row => `<div>${recipePreviewIcon(row.icon)}<span><strong>${esc(row.value || 'Not provided')}</strong><span>${esc(row.label)}</span></span></div>`).join('')}</div>
        <div class="recipe-preview-nutrient-details">${summary.groups.map(group => `<section class="recipe-preview-nutrient-group"><h3>${esc(group.label)}</h3><dl>${group.rows.map(row => `<div><dt>${esc(row.label)}</dt><dd>${esc(row.value)}</dd></div>`).join('')}</dl></section>`).join('')}</div>
        <p class="recipe-preview-print-nutrition">${printRows.map(row => `<span>${esc(row.label)}: ${esc(row.value)}</span>`).join(' | ')}</p>
        <p class="recipe-preview-nutrition-note">${esc(summary.note)}</p>`;
}

function recipePreviewCardHtml(r, context = {}) {
    const esc = recipePreviewEscapeHtml;
    const url = context.url || r.source_url || '';
    const notesOpen = Boolean(context.notesOpen), favorite = Boolean(context.favorite);
    const rating = context.rating || 0;
    const expandedChoices = context.expandedChoices || new Set();
    const author = r.author && typeof r.author === 'object' ? r.author.name : r.author;
    const source = recipePreviewWebUrl(r.source_url || '') ? r.source_url : '';
    const sourceLabel = source ? new URL(source).hostname.replace(/^www\./, '') : '';
    const metrics = [['prep_time','Prep Time','clock'],['cook_time','Cook Time','cook'],['total_time','Total Time','clock'],['servings','Servings','servings']];
    const printMetadata = [['course','Course'],['cuisine','Cuisine'],['dietary_preferences','Dietary Preferences'],
        ['main_ingredient','Main Ingredient'],['cooking_method','Cooking Method'],['occasion','Occasion'],
        ['custom_tags','Custom Tags'],['prep_time_group','Prep Time Group'],['author','Author']]
        .filter(([key]) => r[key]).map(([key,label]) => `<div class="recipe-preview-metadata-field" data-field="${key}"><span class="recipe-preview-metadata-label">${label}</span><span class="recipe-preview-metadata-value">${key === 'cuisine' && r.cuisine_items?.length ? r.cuisine_items.map(recipePreviewCuisineHtml).join(', ') : esc(r[key])}</span></div>`).join('');
    return `
        <header class="recipe-preview-summary">
            <div class="recipe-preview-photo" data-preview-image>${r.image_url ? `<img src="${recipePreviewEscapeAttribute(r.image_url)}" alt="${recipePreviewEscapeAttribute(r.title)}">` : `<span class="recipe-preview-no-image">${recipePreviewIcon('image')}No recipe image</span>`}
                <button type="button" class="recipe-favorite-button recipe-preview-favorite" data-recipe-favorite data-recipe-url="${recipePreviewEscapeAttribute(url)}" data-recipe-name="${recipePreviewEscapeAttribute(r.title)}" aria-label="${favorite ? 'Remove from' : 'Add to'} favorites" aria-pressed="${favorite}" data-preview-action="favorite">${recipePreviewIcon('heart')}</button></div>
            <div class="recipe-preview-summary-text"><h1>${esc(r.title)}</h1>
                <div class="recipe-preview-rating" data-shared-rating-control data-rating-mode="recipe" role="radiogroup" aria-label="Recipe rating: ${rating} out of 5">${[1,2,3,4,5].map(value => `<button type="button" class="recipe-edit-rating-star" data-rating-value="${value}" data-preview-rating="${value}" role="radio" aria-label="${value} star${value === 1 ? '' : 's'}" aria-checked="${rating === value}">${value <= rating ? '★' : '☆'}</button>`).join('')}<button type="button" class="recipe-preview-clear-rating" data-preview-rating="0" aria-label="Clear rating" ${rating ? '' : 'hidden'}>Clear</button></div>
                <div class="recipe-preview-tags">${(r.tags || []).map(tag => {
                    const cuisine = r.cuisine_items?.find(item => item.source_label === tag || item.label === tag);
                    return `<span>${cuisine ? recipePreviewCuisineHtml(cuisine) : esc(tag)}</span>`;
                }).join('')}</div>
                <dl class="recipe-preview-assignment">${[['Cookbook',r.cookbook_name || 'Unassigned'],['Section',r.menu_section || 'Not specified'],['Menu Price (optional)',r.menu_price || 'Not set']].map(([label,value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>
                ${author || source ? `<p class="recipe-preview-source${source ? '' : ' recipe-preview-author-only'}">${author ? `<span class="recipe-preview-source-author">By ${esc(author)}${source ? ' · ' : ''}</span>` : ''}${source ? `<a href="${recipePreviewEscapeAttribute(source)}" target="_blank" rel="noopener noreferrer">${esc(sourceLabel)}</a>` : ''}</p>` : ''}
                ${r.description ? `<p class="recipe-preview-description">${esc(r.description)}</p>` : ''}</div>
        </header>
        <div class="recipe-preview-metrics">${metrics.map(([key,label,icon]) => `<div>${recipePreviewIcon(icon)}<span><span>${label}</span><strong>${esc(String(r[key] || 'Not specified'))}</strong></span></div>`).join('')}</div>
        ${printMetadata ? `<div class="recipe-preview-print-metadata">${printMetadata}</div>` : ''}
        <div class="recipe-preview-columns">
            <section class="recipe-preview-ingredients"><div class="recipe-preview-section-heading"><h2>Ingredients</h2><button type="button" data-preview-action="shopping">${recipePreviewIcon('plus')}Shopping List</button></div>
                <ul>${recipePreviewIngredientsHtml(r, url, expandedChoices)}</ul>
            </section>
            <section class="recipe-preview-equipment"><div class="recipe-preview-section-heading"><h2>Equipment</h2></div>${recipePreviewEquipmentHtml(r, url)}</section>
        <section class="recipe-preview-instructions"><h2>Instructions</h2><ol>${(r.instructions || []).map((step,index) => `<li><span class="recipe-preview-step-number" aria-hidden="true">${index+1}</span><div>${step.section ? `<strong class="recipe-preview-step-section">${esc(step.section)}</strong>` : ''}${esc(step.instruction || step.text || '')}${recipePreviewInstructionMetadata(step)}</div></li>`).join('') || '<li>No instructions specified.</li>'}</ol></section>
        </div>
        <section class="recipe-preview-nutrition" data-preview-nutrition><div class="recipe-preview-section-heading"><h2>Nutrition</h2>
            <div class="recipe-preview-segment recipe-preview-nutrition-toggle" role="group" aria-label="Nutrition display">${[['per_serving','Per serving'],['whole_recipe','Whole recipe']].map(([mode,label]) => `<button type="button" data-preview-nutrition-mode="${mode}" aria-pressed="${r.nutrition_mode === mode}" ${r.nutrition_modes.includes(mode) ? '' : 'disabled'}>${label}</button>`).join('')}</div>
            <span class="recipe-preview-nutrition-yield" aria-live="polite">${esc(r.nutrition_context)}</span></div>
            ${r.nutrition_notice ? `<p class="recipe-preview-nutrition-note">${esc(r.nutrition_basis)}. ${esc(r.nutrition_notice)}</p>` : ''}${recipePreviewNutritionHtml(r)}</section>
        <details class="recipe-preview-notes" data-preview-notes ${notesOpen ? 'open' : ''}><summary>Recipe Notes</summary>
                <p>Permanent recipe notes shared with the editor. Save Notes before printing.</p>
                <fieldset ${context.notesBusy ? 'disabled' : ''}><div data-preview-note-rows>${(context.recipeNotes || r.recipe_notes || []).map(recipePreviewNoteEditorHtml).join('')}</div>
                <div class="recipe-preview-note-actions"><button type="button" data-preview-action="add-note">Add note section</button><button type="button" data-preview-action="save-notes">Save Notes</button></div></fieldset>
                <p data-preview-notes-status role="status" aria-live="polite"></p>
        </details>
        <section class="recipe-preview-print-notes" data-preview-print-notes><h2>Recipe Notes</h2>${recipePreviewSavedNotesHtml(r.saved_recipe_notes || [])}</section>`;
}

function recipePreviewApplyPrintOptions(page, options, model) {
    page.querySelector('[data-preview-image]')?.toggleAttribute('hidden', !options.show_image);
    page.querySelector('[data-preview-nutrition]')?.toggleAttribute('hidden', !options.show_nutrition);
    page.querySelector('.recipe-preview-summary')?.classList.toggle('without-image', !options.show_image);
    page.querySelector('.recipe-preview-card').dataset.textSize = options.text_size;
    page.querySelector('.recipe-preview-card').dataset.printBundleInfo = options.print_bundle_info !== false;
    page.querySelector('[data-preview-print-notes]')?.toggleAttribute('hidden', !options.print_notes || !model?.saved_recipe_notes?.length);
}
