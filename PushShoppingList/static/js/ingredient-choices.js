/* Ingredient Choices is a projection of the editor's canonical ingredient rows.
 * Bundles use the existing substitution IDs/order fields, so every editor view,
 * save path, and shopping resolver consumes the same data. */
let recipeChoicesRendering = false;

function recipeChoiceGroups(row) {
    const container = recipeIngredientSubstitutionContainer(row);
    const groups = recipeIngredientSubstitutionDomGroups(
        [...(container?.querySelectorAll('[data-substitution-option-row]') || [])],
    ).map(group => ({
        id: group.alternativeId,
        rows: group.rows,
        values: group.rows.map(fieldValuesFromRow),
    }));
    if (groups.length && !groups.some(group => group.values.some(value => value.option_type === 'original'))) {
        groups.unshift({
            id: row.querySelector('[data-original-option-id]')?.value || nextRecipeIngredientAlternativeId(),
            rows: [row],
            values: [{...fieldValuesFromRow(row), option_type: 'original', alternative_label: ''}],
        });
    }
    return groups;
}

function recipeChoiceLabel(row) {
    const value = fieldValuesFromRow(row);
    return value.requirement_label || value.source_text || value.original_text
        || [recipeIngredientRecipeViewAmount(value), value.ingredient, value.preparation].filter(Boolean).join(' ');
}

function recipeChoiceDefault(row, groups) {
    const id = recipeIngredientDirectField(row, 'default_option_id')?.value;
    return groups.find(group => group.id === id)?.id
        || groups.find(group => group.values.some(value => recipeIngredientMatchFlag(value.is_default) || recipeIngredientMatchFlag(value.preferred)))?.id
        || '';
}

function recipeChoiceSetField(row, field, value) {
    let input = recipeIngredientDirectField(row, field);
    if (!input) {
        input = document.createElement('input');
        input.type = 'hidden';
        input.dataset.field = field;
        row.appendChild(input);
    }
    if (input.type === 'checkbox') input.checked = recipeIngredientMatchFlag(value);
    else input.value = String(value ?? '');
}

function writeRecipeChoiceGroups(row, groups, defaultId) {
    const container = recipeIngredientSubstitutionContainer(row);
    const list = container?.querySelector('[data-ingredient-substitution-list]');
    if (!list) return;
    defaultId = groups.some(group => group.id === defaultId) ? defaultId : groups[0]?.id;
    const source = recipeIngredientDirectField(row, 'source_text');
    if (source && !source.value) source.value = recipeChoiceLabel(row);
    recipeChoiceSetField(row, 'default_option_id', defaultId);
    recipeChoiceSetField(row, 'selection_required', false);
    recipeChoiceSetField(row, 'original_is_default', false);
    list.innerHTML = groups.map((group, groupIndex) => group.values.map((value, componentIndex) => {
        // Never inherit the source requirement's amount into bundle components.
        const component = {...value,
            alternative_id: group.id,
            alternative_order: groupIndex,
            alternative_component_order: componentIndex,
            option_type: groupIndex === 0 ? 'original' : 'recipe_choice',
            recipe_authored: true,
            is_default: group.id === defaultId,
            preferred: group.id === defaultId,
        };
        delete component.substitutions;
        return recipeIngredientSubstitutionOptionRowHtml(component, componentIndex, {index: groupIndex, componentIndex});
    }).join('')).join('');
    bindRecipeIngredientSubstitutionRows(row);
    updateRecipeIngredientSubstitutionState(row);
    updateRecipeIngredientSummary(row);
    updateRecipeIngredientRowIndexes();
    updateRecipeEditorDirtyState();
}

function recipeChoiceButton(action, label, content, disabled = false) {
    return `<button type="button" data-choice-action="${action}" aria-label="${escapeAttribute(label)}" title="${escapeAttribute(label)}" ${disabled ? 'disabled' : ''}>${content || escapeHtml(label)}</button>`;
}

function recipeChoiceMoveButtons(kind, label, index, length) {
    return recipeChoiceButton(`${kind}-up`, `Move ${label} up`, '&#8593;', index === 0)
        + recipeChoiceButton(`${kind}-down`, `Move ${label} down`, '&#8595;', index === length - 1);
}

function recipeChoiceImage(value) {
    const url = recipeIngredientImageUrl(value);
    return `<span class="recipe-choice-image">${url
        ? `<img src="${escapeAttribute(recipeImageVariantUrl(url, 'thumb'))}" alt="" loading="lazy" onerror="this.hidden=true">`
        : recipeEditSvgIcon('ingredients')}</span>`;
}

function recipeChoiceIngredient(value, editing, index, length) {
    const amount = recipeIngredientViewAmount(value);
    const notes = [value.preparation, value.notes].filter(Boolean).join(' · ');
    if (!editing) return `<div class="recipe-choice-ingredient">${recipeChoiceImage(value)}<div><strong>${escapeHtml(value.ingredient || 'Unnamed ingredient')}</strong>${amount ? `<span>${escapeHtml(amount)}</span>` : ''}${notes ? `<small>${escapeHtml(notes)}</small>` : ''}</div></div>`;
    const fields = [
        ['ingredient', 'Ingredient', value.ingredient, 'Ingredient name'],
        ['quantity', 'Quantity', value.base_quantity ?? value.quantity, 'Unspecified'],
        ['unit', 'Unit', value.base_unit ?? value.unit, 'Unspecified'],
        ['preparation', 'Preparation', value.preparation, 'Optional'],
        ['notes', 'Notes', value.notes, 'Optional'],
    ];
    return `<div class="recipe-choice-component-editor" data-choice-component="${index}"><div class="recipe-choice-fields">${fields.map(([field, label, val, placeholder]) => `<label class="choice-field-${field}"><span>${label}</span><input data-choice-field="${field}" aria-label="${label}" value="${escapeAttribute(val ?? '')}" placeholder="${placeholder}"></label>`).join('')}</div><div class="recipe-choice-tools">${recipeChoiceMoveButtons('component', 'ingredient', index, length)}${recipeChoiceButton('component-remove', 'Remove ingredient', recipeEditSvgIcon('trash'), length <= 1)}</div></div>`;
}

function renderRecipeIngredientChoicesView() {
    const panel = document.getElementById('recipeEditIngredientViewChoices');
    if (!panel || panel.hidden || recipeChoicesRendering) return;
    // Preserve caret and in-progress edits when another editor refresh runs.
    if (panel.contains(document.activeElement) && document.activeElement.matches('input')) return;
    recipeChoicesRendering = true;
    try {
        const rows = recipeEditIngredientRows();
        const choices = rows.filter(row => recipeChoiceGroups(row).length);
        const standard = rows.filter(row => !recipeChoiceGroups(row).length
            && recipeIngredientRecipeViewHasContent(fieldValuesFromRow(row), []));
        panel.innerHTML = `<div class="recipe-choices-intro"><div><h3>Ingredient Choices</h3><p>Keep everyday ingredients together. Choose one bundle for each recipe requirement.</p></div>${recipeChoiceButton('group-add', 'Add choice group', '+ Add choice group')}</div>
            <section class="recipe-choices-section"><header><span class="recipe-choices-symbol">&#10003;</span><div><h4>Standard Ingredients <span>(${standard.length})</span></h4><p>Always included in this recipe.</p></div></header><div class="recipe-choices-standard">${standard.map(row => `<div class="recipe-choices-standard-item" data-choice-row="${rows.indexOf(row)}">${recipeChoiceIngredient(fieldValuesFromRow(row), false)}<div class="recipe-choice-tools">${recipeChoiceButton('standard-edit', 'Edit ingredient', recipeEditSvgIcon('edit'))}${recipeChoiceButton('standard-convert', 'Make ingredient a choice group', recipeEditSvgIcon('plus'))}</div></div>`).join('') || '<p class="recipe-choices-empty">No standard ingredients. Add an ingredient or create a choice group.</p>'}</div></section>
            <section class="recipe-choices-section"><header><span class="recipe-choices-symbol">&#8644;</span><div><h4>Ingredient Choices <span>(${choices.length})</span></h4><p>Choose one option per group. Only the selected bundle goes to your shopping list.</p></div></header><div class="recipe-choices-groups">${choices.map((row, groupIndex) => {
                const groups = recipeChoiceGroups(row);
                const selected = recipeChoiceDefault(row, groups);
                const editing = Boolean(row.recipeChoicesEditing);
                const label = recipeChoiceLabel(row);
                return `<article class="recipe-choice-group${editing ? ' is-editing' : ''}" data-choice-row="${rows.indexOf(row)}"><div class="recipe-choice-group-heading"><span class="recipe-choice-number">${groupIndex + 1}</span><div class="recipe-choice-group-title">${editing ? `<label>Source requirement or label<input data-choice-label aria-label="Source requirement or label" value="${escapeAttribute(label)}" placeholder="e.g. 1/2 cup butter (melted)"></label>` : `<h5>${escapeHtml(label || 'Untitled choice group')}</h5>`}<span>Choose 1${editing ? ' · Quantities below are for the original recipe (1×).' : ''}</span></div><div class="recipe-choice-tools">${recipeChoiceMoveButtons('group', 'choice group', groupIndex, choices.length)}${recipeChoiceButton('group-edit', editing ? 'Done editing group' : 'Edit choice group', editing ? 'Done' : 'Edit')}${recipeChoiceButton('group-remove', 'Remove choice group', recipeEditSvgIcon('trash'))}</div></div>
                    <div class="recipe-choice-options" role="radiogroup" aria-label="${escapeAttribute(label || 'Ingredient choice')}">${groups.map((group, optionIndex) => {
                        const isDefault = selected === group.id;
                        const name = group.values[0]?.alternative_label || `Option ${optionIndex + 1}`;
                        return `<div class="recipe-choice-option${isDefault ? ' is-default' : ''}" data-choice-option="${optionIndex}"><div class="recipe-choice-option-heading"><label class="recipe-choice-select"><input type="radio" name="choice-default-${rows.indexOf(row)}" data-choice-default aria-label="Use ${escapeAttribute(name)} as default" ${isDefault ? 'checked' : ''}><span>${escapeHtml(name)}</span>${isDefault ? '<span class="recipe-choice-default-badge">Default</span>' : ''}</label>${editing ? `<div class="recipe-choice-tools">${recipeChoiceMoveButtons('option', 'option', optionIndex, groups.length)}${recipeChoiceButton('option-remove', 'Remove option', recipeEditSvgIcon('trash'), groups.length <= 2)}</div>` : ''}</div>
                        ${editing ? `<label class="recipe-choice-option-name">Option label<input data-choice-option-label aria-label="Option label" placeholder="Option ${optionIndex + 1}" value="${escapeAttribute(group.values[0]?.alternative_label || '')}"></label>` : ''}
                        <div class="recipe-choice-components">${group.values.map((value, index) => recipeChoiceIngredient(value, editing, index, group.values.length)).join('')}</div>${editing ? recipeChoiceButton('component-add', 'Add ingredient to option', '+ Add ingredient') : ''}</div>`;
                    }).join('')}</div>${editing ? `<div class="recipe-choice-group-footer"><span>Each option is a bundle. Leave unknown quantities blank.</span>${recipeChoiceButton('option-add', 'Add option', '+ Add option')}</div>` : ''}</article>`;
            }).join('') || '<p class="recipe-choices-empty">No choices yet. Use “Add choice group” or turn a standard ingredient into a choice.</p>'}</div></section>`;
        panel.onclick = handleRecipeChoiceAction;
        panel.oninput = handleRecipeChoiceInput;
        panel.onchange = handleRecipeChoiceSelection;
    } finally {
        recipeChoicesRendering = false;
    }
}

function recipeChoiceContext(control) {
    const article = control.closest('[data-choice-row]');
    const row = recipeEditIngredientRows()[Number(article?.dataset.choiceRow)];
    const groups = row ? recipeChoiceGroups(row) : [];
    const optionIndex = Number(control.closest('[data-choice-option]')?.dataset.choiceOption ?? -1);
    const componentIndex = Number(control.closest('[data-choice-component]')?.dataset.choiceComponent ?? -1);
    return {row, groups, optionIndex, componentIndex};
}

function handleRecipeChoiceInput(event) {
    const input = event.target;
    const {row, groups, optionIndex, componentIndex} = recipeChoiceContext(input);
    if (!row) return;
    if (input.hasAttribute('data-choice-label')) {
        recipeChoiceSetField(row, 'requirement_label', input.value);
        if (row.recipeChoicesNew) recipeChoiceSetField(row, 'ingredient', input.value);
    } else if (input.hasAttribute('data-choice-option-label')) {
        groups[optionIndex].rows.forEach(component => recipeChoiceSetField(component, 'alternative_label', input.value));
    } else if (input.dataset.choiceField) {
        const component = groups[optionIndex].rows[componentIndex];
        const field = input.dataset.choiceField;
        recipeChoiceSetField(component, field, input.value);
        if (field === 'ingredient') {
            // An edited identity must not retain a stale master-data purchase mapping.
            ['purchasable_item', 'parsed_name', 'normalized_name', 'master_normalized_name'].forEach(key => recipeChoiceSetField(component, key, input.value));
            ['ingredient_id', 'canonical_ingredient', 'purchase_group', 'ingredient_image_url', 'ingredient_image_generated_at', 'ingredient_image_prompt'].forEach(key => recipeChoiceSetField(component, key, ''));
        }
        if (field === 'quantity' || field === 'unit') {
            recipeChoiceSetField(component, `base_${field}`, input.value);
            if (field === 'quantity') recipeChoiceSetField(component, 'quantity_text', '');
            else {
                recipeChoiceSetField(component, 'unit_id', '');
                recipeChoiceSetField(component, 'unit_raw', input.value);
            }
            applyRecipeScaleToIngredientRow(component, currentRecipeEditScaleMultiplier());
        }
    }
    updateRecipeEditorDirtyState();
}

function handleRecipeChoiceSelection(event) {
    if (!event.target.hasAttribute('data-choice-default')) return;
    const {row, groups, optionIndex} = recipeChoiceContext(event.target);
    event.target.blur();
    writeRecipeChoiceGroups(row, groups, groups[optionIndex].id);
    renderRecipeIngredientChoicesView();
    const panel = document.getElementById('recipeEditIngredientViewChoices');
    panel.querySelector(`[data-choice-row="${recipeEditIngredientRows().indexOf(row)}"] [data-choice-option="${optionIndex}"] [data-choice-default]`)?.focus();
    setRecipeEditStatus('Default option selected. Save Recipe to keep it.');
}

function handleRecipeChoiceAction(event) {
    const button = event.target.closest('[data-choice-action]');
    if (!button || button.disabled) return;
    const action = button.dataset.choiceAction;
    const {row, groups, optionIndex, componentIndex} = recipeChoiceContext(button);
    let defaultId = row ? recipeChoiceDefault(row, groups) : '';
    const newOption = () => ({id: nextRecipeIngredientAlternativeId(), values: [{ingredient: '', quantity: '', unit: '', optional: false}]});
    if (action === 'group-add') {
        const added = addRecipeIngredientRow({}, {deferChoiceInitialization: true});
        added.recipeChoicesEditing = true;
        added.recipeChoicesNew = true;
        const options = [newOption(), newOption()];
        writeRecipeChoiceGroups(added, options, options[0].id);
    } else if (action === 'standard-edit') {
        recipeEditIngredientModalReturnView = 'choices';
        setRecipeEditIngredientView('table', {persist: false});
        setRecipeIngredientEditMode(row, true, {trigger: button});
        return;
    } else if (action === 'standard-convert') {
        row.recipeChoicesEditing = true;
        const original = {...fieldValuesFromRow(row)};
        const options = [{id: nextRecipeIngredientAlternativeId(), values: [original]}, newOption()];
        writeRecipeChoiceGroups(row, options, options[0].id);
    } else if (action === 'group-edit') {
        row.recipeChoicesEditing = !row.recipeChoicesEditing;
        // Materialize legacy implicit originals before editing any component.
        if (row.recipeChoicesEditing) writeRecipeChoiceGroups(row, groups, defaultId);
        else {
            updateRecipeIngredientSummary(row);
            updateRecipeIngredientRowIndexes();
        }
    } else if (action === 'group-remove') {
        if (!window.confirm('Remove this choice group and all of its options?')) return;
        recipeIngredientSubstitutionContainer(row)?.remove();
        row.remove();
        updateRecipeIngredientRowIndexes();
        applyRecipeIngredientColumnView();
    } else if (action.startsWith('group-')) {
        const allRows = recipeEditIngredientRows();
        const choiceRows = allRows.filter(candidate => recipeChoiceGroups(candidate).length);
        const index = choiceRows.indexOf(row);
        const target = choiceRows[index + (action.endsWith('up') ? -1 : 1)];
        if (!target) return;
        const from = allRows.indexOf(row);
        const to = allRows.indexOf(target);
        [allRows[from], allRows[to]] = [allRows[to], allRows[from]];
        allRows.forEach((candidate, order) => {
            candidate.recipeIngredientColumnViewCanonicalOrder = order;
            document.getElementById('recipeEditIngredients').appendChild(candidate);
        });
        updateRecipeIngredientRowIndexes();
        applyRecipeIngredientColumnView();
    } else {
        const option = groups[optionIndex];
        if (action === 'option-add') groups.push(newOption());
        else if (action === 'option-remove' && groups.length > 2) groups.splice(optionIndex, 1);
        else if (action === 'component-add') option.values.push({ingredient: '', quantity: '', unit: '', optional: false});
        else if (action === 'component-remove' && option.values.length > 1) option.values.splice(componentIndex, 1);
        else if (action.endsWith('-up') || action.endsWith('-down')) {
            const items = action.startsWith('option-') ? groups : option.values;
            const index = action.startsWith('option-') ? optionIndex : componentIndex;
            const next = index + (action.endsWith('up') ? -1 : 1);
            if (next >= 0 && next < items.length) [items[index], items[next]] = [items[next], items[index]];
        }
        writeRecipeChoiceGroups(row, groups, defaultId);
    }
    updateRecipeEditorDirtyState();
    renderRecipeIngredientChoicesView();
    const panel = document.getElementById('recipeEditIngredientViewChoices');
    if (action === 'group-add') panel.querySelector('[data-choice-row]:last-child [data-choice-label]')?.focus();
    else if (row?.isConnected) {
        const article = panel.querySelector(`[data-choice-row="${recipeEditIngredientRows().indexOf(row)}"]`);
        (article?.querySelector(`[data-choice-action="${action}"]:not(:disabled)`) || article?.querySelector('[data-choice-action="group-edit"]'))?.focus({preventScroll: true});
    }
}

function validateRecipeIngredientChoices(errors) {
    recipeEditIngredientRows().forEach(row => {
        const groups = recipeChoiceGroups(row);
        if (!groups.length) return;
        if (recipeEditIngredientView === 'choices' && !recipeChoiceDefault(row, groups)) {
            addRecipeEditorValidationError(errors, 'Choose one default option for each ingredient choice group.', recipeIngredientDirectField(row, 'default_option_id'));
        }
        if (!recipeChoiceLabel(row).trim()) {
            addRecipeEditorValidationError(errors, 'Enter a source requirement or label for the choice group.', recipeIngredientDirectField(row, 'requirement_label'));
        }
        if (row.recipeChoicesEditing && groups.length < 2) {
            addRecipeEditorValidationError(errors, 'A choice group needs at least two options.', recipeIngredientDirectField(row, 'ingredient'));
        }
    });
}
