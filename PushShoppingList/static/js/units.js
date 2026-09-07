(function () {
    "use strict";

    const LEGACY_CUSTOM_UNITS_KEY = "recipeIngredientCustomUnits";
    const IMPORT_DISMISSED_KEY = "recipeIngredientCustomUnitsImportDismissed";

    function cleanText(value) {
        return String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ");
    }

    function unitKey(value) {
        return cleanText(value)
            .toLowerCase()
            .replace(/\./g, "")
            .replace(/[_-]+/g, " ")
            .replace(/\s+/g, " ");
    }

    function unitDraftSignature(values) {
        return JSON.stringify({
            canonical_name: cleanText(values.canonical_name),
            category: values.category,
            aliases: values.aliases.map(cleanText).sort(),
        });
    }

    function validateUnitDraft(values, registry, unitId = "") {
        const errors = { aliases: {} };
        const name = cleanText(values.canonical_name);
        const nameKey = unitKey(name);
        const owners = new Map();
        registry.units.filter(unit => String(unit.id) !== String(unitId)).forEach(unit => {
            [unit.name, ...(unit.aliases || [])].forEach(value => owners.set(unitKey(value), unit.name));
        });
        if (!name || !nameKey) errors.canonical_name = "Enter a canonical name.";
        else if (name.length > 60) errors.canonical_name = "Canonical names must be 60 characters or fewer.";
        else if (owners.has(nameKey)) errors.canonical_name = `“${name}” is already accepted by ${owners.get(nameKey)}.`;
        if (!registry.categories.some(category => category.key === values.category)) errors.category = "Choose a unit category.";
        const seen = new Set();
        values.aliases.forEach((value, index) => {
            const alias = cleanText(value), key = unitKey(alias);
            if (!alias || !key) errors.aliases[index] = "Enter an alias with letters or numbers.";
            else if (alias.length > 60) errors.aliases[index] = "Aliases must be 60 characters or fewer.";
            else if (key === nameKey) errors.aliases[index] = "The canonical name does not need to be an alias.";
            else if (seen.has(key)) errors.aliases[index] = `“${alias}” is already in this unit.`;
            else if (owners.has(key)) errors.aliases[index] = `“${alias}” is already accepted by ${owners.get(key)}.`;
            seen.add(key);
        });
        return errors;
    }

    function parseRegistry() {
        const source = document.getElementById("ingredientUnitConfig");
        try {
            const payload = JSON.parse(source?.textContent || "{}");
            return {
                units: Array.isArray(payload.units) ? payload.units : [],
                aliases: payload.aliases && typeof payload.aliases === "object" ? payload.aliases : {},
                categories: Array.isArray(payload.categories) ? payload.categories : [],
            };
        } catch (error) {
            console.error("Unable to load the unit registry.", error);
            return { units: [], aliases: {}, categories: [] };
        }
    }

    function legacyUnitNames() {
        try {
            const values = JSON.parse(localStorage.getItem(LEGACY_CUSTOM_UNITS_KEY) || "[]");
            const names = [];
            const seen = new Set();
            (Array.isArray(values) ? values : []).forEach(value => {
                const name = cleanText(value);
                const key = unitKey(name);
                if (name && key && !seen.has(key)) {
                    names.push(name);
                    seen.add(key);
                }
            });
            return names;
        } catch (error) {
            console.warn("Unable to read legacy browser units.", error);
            return [];
        }
    }

    function initUnitMasterPage() {
        const root = document.querySelector("[data-unit-master-page]");
        if (!root) return;

        let registry = parseRegistry();
        const rowDrafts = new Map();
        let inlineUnitId = "";
        let inlineField = "name";
        let editorUnitId = "";
        let editorAliases = [];
        let editorAliasErrors = {};
        let returnFocus = null;
        let saveButtonLabel = "Add Unit";
        let aiSuggestionPending = false;
        let suggestionRequestToken = 0;
        let suggestionController = null;
        let suggestedAliases = [];
        const selectedAliases = new Set();
        let usageRequestToken = 0;
        let usageReturnFocus = null;
        let usageScrollState = [];
        let orderPending = false;
        let mutationPending = false;
        let draggedRow = null;
        let rowDropTarget = null;
        let rowDropAfter = false;
        let originalDraft = null;
        let serverErrors = {};
        let showValidation = false;
        let categoryUI;

        const source = document.getElementById("ingredientUnitConfig");
        const status = root.querySelector("[data-unit-master-status]");
        const search = root.querySelector("[data-unit-master-search]");
        const searchEmpty = root.querySelector("[data-unit-master-search-empty]");
        const categoryList = root.querySelector("[data-unit-master-category-list]");
        const form = root.querySelector("[data-unit-master-form]");
        const editorHome = root.querySelector("[data-unit-master-editor-home]");
        const addButtons = Array.from(root.querySelectorAll("[data-unit-master-add-button]"));
        const countLabel = root.querySelector("[data-unit-master-count-label]");
        const nameInput = root.querySelector("[data-unit-master-name]");
        let categorySelect = root.querySelector("[data-unit-master-category-select]");
        const categoryTemplate = categoryList.querySelector('[data-unit-master-category]').cloneNode(true);
        categoryTemplate.querySelector('[data-unit-master-category-rows]').replaceChildren();
        const firstInvalidControl = () => [nameInput, categorySelect, aliasInput].find(control => control.getAttribute("aria-invalid") === "true");
        const aliasInput = root.querySelector("[data-unit-master-alias-input]");
        const aliasChips = root.querySelector("[data-unit-master-alias-chips]");
        const saveButton = root.querySelector("[data-unit-master-save]");
        const suggestButton = root.querySelector("[data-unit-master-ai-suggest]");
        const suggestButtonLabel = root.querySelector("[data-unit-master-ai-suggest-label]");
        const aliasAddButton = root.querySelector("[data-unit-master-alias-add]");
        // Upgrade a cached server template as well as freshly rendered markup.
        let suggestions = root.querySelector('[data-unit-alias-suggestions]');
        if (!suggestions) {
            suggestions = document.createElement('section');
            suggestions.className = 'unit-master-alias-suggestions';
            suggestions.dataset.unitAliasSuggestions = '';
            suggestions.setAttribute('aria-label', 'Suggested aliases');
            suggestions.hidden = true;
            suggestions.innerHTML = '<p data-unit-alias-suggestion-status role="status" aria-live="polite"></p><div class="unit-master-suggestion-chips" data-unit-alias-suggestion-chips role="group" aria-label="Select suggested aliases"></div><button type="button" data-unit-alias-add-selected disabled>Add selected</button>';
            form.querySelector('footer').before(suggestions);
        }
        const suggestionStatus = root.querySelector('[data-unit-alias-suggestion-status]');
        const suggestionChips = root.querySelector('[data-unit-alias-suggestion-chips]');
        const addSelected = root.querySelector('[data-unit-alias-add-selected]');
        const editorTitle = root.querySelector("[data-unit-master-editor-title]");
        const editorKicker = root.querySelector("[data-unit-master-editor-kicker]");
        const editorFeedback = root.querySelector("[data-unit-master-editor-feedback]");
        const nameError = root.querySelector("[data-unit-master-name-error]");
        const categoryError = root.querySelector("[data-unit-master-category-error]");
        const aliasError = root.querySelector("[data-unit-master-alias-error]");
        const aliasPreview = root.querySelector("[data-unit-master-alias-preview]");
        const dirtyStatus = root.querySelector("[data-unit-master-dirty-status]");
        const editorUsage = root.querySelector("[data-unit-master-editor-usage]");
        const editorImpact = root.querySelector("[data-unit-master-editor-impact]");
        const editorPermissions = root.querySelector("[data-unit-master-editor-permissions]");
        const cancelButton = root.querySelector("[data-unit-master-cancel]");
        const importPanel = root.querySelector("[data-unit-master-import]");
        const importButton = root.querySelector("[data-unit-master-import-button]");
        const usageDialog = root.querySelector("[data-unit-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-unit-master-usage-title]");
        const usageContext = root.querySelector("[data-unit-master-usage-context]");
        const usageSummary = root.querySelector("[data-unit-master-usage-summary]");
        const usageResults = root.querySelector("[data-unit-master-usage-results]");

        const setStatus = (message, type = "success", announceOnly = false) => {
            status.classList.toggle("sr-only", announceOnly);
            status.textContent = String(message || "");
            status.dataset.status = type;
            status.hidden = !status.textContent;
        };

        const setFieldError = (input, output, message) => {
            const text = String(message || "");
            output.textContent = text;
            output.hidden = !text;
            if (text) input.setAttribute("aria-invalid", "true");
            else input.removeAttribute("aria-invalid");
        };

        const setEditorFeedback = (message, type = "error") => {
            editorFeedback.textContent = String(message || "");
            editorFeedback.dataset.status = type;
            editorFeedback.hidden = !editorFeedback.textContent;
        };

        const setAiPending = pending => {
            aiSuggestionPending = Boolean(pending);
            suggestButtonLabel.textContent = aiSuggestionPending ? "Suggesting…" : "Suggest aliases";
            syncEditorState();
        };

        const clearErrors = () => {
            editorAliasErrors = {};
            serverErrors = {};
            setFieldError(nameInput, nameError, "");
            setFieldError(categorySelect, categoryError, "");
            setFieldError(aliasInput, aliasError, "");
            setEditorFeedback("");
            renderAliasChips();
        };

        const unitById = unitId => registry.units.find(unit => String(unit.id) === String(unitId)) || null;

        const rowFor = id => root.querySelector(`[data-unit-master-row][data-unit-id="${CSS.escape(String(id))}"]`);
        const savedValues = unit => ({canonical_name: unit.name, category: unit.category, aliases: [...(unit.aliases || [])]});
        const rowDraft = id => {
            id = String(id);
            if (!rowDrafts.has(id)) {
                const original = savedValues(unitById(id));
                rowDrafts.set(id, {original, values: {...original, aliases: [...original.aliases]}, pendingAlias: "", errors: {}, feedback: "", saving: false});
            }
            return rowDrafts.get(id);
        };
        const rowValues = id => {
            const draft = rowDraft(id);
            return {...draft.values, aliases: [...draft.values.aliases, ...(cleanText(draft.pendingAlias) ? [cleanText(draft.pendingAlias)] : [])]};
        };
        const rowIsDirty = id => unitDraftSignature(rowValues(id)) !== unitDraftSignature(rowDraft(id).original);
        const rowHasEdits = id => {
            const draft = rowDraft(id);
            return JSON.stringify(draft.values) !== JSON.stringify(draft.original) || Boolean(draft.pendingAlias);
        };
        const rowValidation = id => {
            const local = validateUnitDraft(rowValues(id), registry, id);
            const remote = rowDraft(id).errors;
            return {...local, ...remote, aliases: {...local.aliases, ...(remote.aliases || {})}};
        };
        const renderRowFields = row => {
            const id = row.dataset.unitId, unit = unitById(id), draft = rowDraft(id);
            const editing = inlineUnitId === id;
            row.classList.toggle('is-inline-editing', editing);
            for (const field of ['name', 'category']) {
                const cell = row.querySelector(`[data-unit-master-${field}-cell]`);
                const previous = cell.querySelector(`[data-unit-row-${field}], [data-unit-row-activate]`);
                if (previous && previous.matches(`[data-unit-row-${field}]`) === editing) {
                    if (field === 'category') {
                        if (editing) { previous.value = draft.values.category; categoryUI.refresh(previous); }
                        else previous.textContent = registry.categories.find(item => item.key === unit.category)?.label || unit.category;
                    }
                    continue;
                }
                const control = document.createElement(editing && field === 'name' ? 'input' : 'button');
                const label = field === 'name' ? `canonical name for ${unit.name}` : `category for ${unit.name}`;
                if (editing) {
                    control.dataset[field === 'name' ? 'unitRowName' : 'unitRowCategory'] = '';
                    control.setAttribute('aria-label', label);
                    control.setAttribute('aria-describedby', `unitRow${field === 'name' ? 'Name' : 'Category'}Error-${id}`);
                    if (field === 'name') {
                        control.type = 'text'; control.maxLength = 60; control.autocomplete = 'off'; control.required = true;
                        control.value = draft.values.canonical_name;
                    } else {
                        control.value = draft.values.category;
                        categoryUI.enhance(control);
                    }
                } else {
                    control.type = 'button'; control.className = 'unit-master-inline-value';
                    control.dataset.unitRowActivate = field;
                    control.setAttribute('aria-label', `Edit ${label}`);
                    if (field === 'category') control.setAttribute('aria-haspopup', 'menu');
                    control.textContent = field === 'name' ? unit.name : registry.categories.find(item => item.key === unit.category)?.label || unit.category;
                }
                if (previous) previous.replaceWith(control);
                else cell.prepend(control);
            }
            const edit = row.querySelector('[data-unit-master-edit-button]');
            const destination = row.querySelector('.unit-master-action-cell');
            if (edit.parentElement !== destination) destination.prepend(edit);
            edit.className = 'unit-master-edit-button';
            edit.textContent = 'Edit unit';
            edit.setAttribute('aria-label', `Edit unit ${unit.name}`);
            edit.removeAttribute('aria-controls'); edit.removeAttribute('aria-expanded');
            edit.hidden = editing;
            const aliases = row.querySelector('.unit-master-aliases');
            let chipList = aliases.querySelector('.unit-master-alias-chip-list');
            if (!chipList) {
                chipList = document.createElement('span');
                chipList.className = 'unit-master-alias-chip-list';
                aliases.prepend(chipList);
            }
            let actions = aliases.querySelector('.unit-master-alias-actions');
            if (!actions) {
                actions = document.createElement('span');
                actions.className = 'unit-master-alias-actions';
                for (const [mode, label, icon] of [['add', 'Add alias', '+'], ['suggest', 'Suggest aliases', '✨']]) {
                    const button = document.createElement('button');
                    button.type = 'button'; button.dataset.unitRowAlias = mode; button.textContent = icon;
                    button.title = label; button.setAttribute('aria-label', label);
                    button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-controls', form.id);
                    actions.append(button);
                }
                aliases.append(actions);
            }
            const values = editing ? draft.values.aliases : unit.aliases || [];
            const signature = JSON.stringify(values);
            if (aliases.dataset.aliases !== signature) {
                // Upgrade cached markup without removing the separate action group.
                aliases.querySelectorAll(':scope > code, :scope > span:not(.unit-master-alias-actions):not(.unit-master-alias-chip-list)').forEach(chip => chip.remove());
                chipList.replaceChildren(...values.map(alias => {
                    const chip = document.createElement('code'); chip.textContent = alias; return chip;
                }));
                chipList.hidden = !values.length;
                aliases.dataset.aliases = signature;
            }
            actions.querySelectorAll('button').forEach(button => {
                button.disabled = mutationPending || orderPending;
                button.setAttribute('aria-expanded', String(!form.hidden && editorUnitId === id && returnFocus === button));
            });
            row.querySelector('[data-unit-row-save]').hidden = !editing;
            row.querySelector('[data-unit-row-cancel]').hidden = !editing;
        };
        const syncRowState = row => {
            if (!row) return;
            renderRowFields(row);
            const id = row.dataset.unitId, draft = rowDraft(id), errors = rowValidation(id);
            const dirty = rowIsDirty(id);
            const name = row.querySelector('[data-unit-row-name]'), category = row.querySelector('[data-unit-row-category]');
            // Seeded status never gates editing. Only the row being submitted is busy.
            if (name && category) {
                name.disabled = category.disabled = draft.saving;
                category.title = registry.categories.find(item => item.key === draft.values.category)?.label || '';
                setFieldError(name, row.querySelector('[data-unit-row-name-error]'), errors.canonical_name);
                setFieldError(category, row.querySelector('[data-unit-row-category-error]'), errors.category);
            } else {
                row.querySelector('[data-unit-row-name-error]').hidden = true;
                row.querySelector('[data-unit-row-category-error]').hidden = true;
            }
            row.classList.toggle('is-dirty', dirty);
            row.setAttribute('aria-busy', String(draft.saving));
            const save = row.querySelector('[data-unit-row-save]');
            save.disabled = mutationPending || orderPending || (editorUnitId === id && aiSuggestionPending) || !dirty
                || Boolean(errors.canonical_name || errors.category || Object.keys(errors.aliases).length);
            save.textContent = draft.saving ? 'Saving...' : 'Save';
            row.querySelector('[data-unit-row-cancel]').disabled = draft.saving;
            const feedback = row.querySelector('[data-unit-row-status]');
            const aliasErrors = [...new Set(Object.values(errors.aliases))].join(' ');
            feedback.textContent = aliasErrors ? 'Check aliases' : draft.feedback || (dirty ? 'Unsaved changes' : '');
            feedback.title = aliasErrors;
            feedback.classList.toggle('is-alias-error', Boolean(aliasErrors));
            feedback.hidden = !feedback.textContent;
            feedback.classList.toggle('is-error', Boolean(aliasErrors || draft.feedbackType === 'error'));
        };
        const resetRow = id => {
            rowDrafts.delete(String(id));
            const draft = rowDraft(id), row = rowFor(id);
            if (!row) return;
            if (row.querySelector('[data-unit-row-name]')) row.querySelector('[data-unit-row-name]').value = draft.values.canonical_name;
            if (row.querySelector('[data-unit-row-category]')) row.querySelector('[data-unit-row-category]').value = draft.values.category;
            syncRowState(row);
        };

        const releaseInlineRow = () => {
            if (!inlineUnitId) return true;
            const id = inlineUnitId;
            if (rowHasEdits(id)) {
                const draft = rowDraft(id);
                draft.feedback = `Save or cancel changes to ${unitById(id).name} before editing another unit.`;
                syncRowState(rowFor(id));
                rowFor(id).querySelector('[data-unit-row-name]').focus({preventScroll: true});
                return false;
            }
            cancelRow(id, false);
            return true;
        };

        const activateInlineRow = (id, field = 'name', focus = true) => {
            id = String(id);
            if (mutationPending || orderPending) return false;
            if (inlineUnitId && inlineUnitId !== id && !releaseInlineRow()) return false;
            if (!form.hidden && !editorUnitId && !closeEditor({restoreFocus: false})) return false;
            inlineUnitId = id;
            inlineField = field;
            syncOrderControls();
            if (focus) {
                const control = rowFor(id).querySelector(`[data-unit-row-${field}]`);
                control.focus({preventScroll: true});
                if (field === 'name') control.setSelectionRange(control.value.length, control.value.length);
                else {
                    categoryUI.openMenu(control);
                }
            }
            return true;
        };

        const syncEditingContext = unit => {
            form.classList.toggle('is-alias-popover', Boolean(unit));
            if (unit) form.setAttribute('role', 'dialog');
            else form.removeAttribute('role');
            form.querySelector(".unit-master-editor-grid").hidden = Boolean(unit);
            saveButton.hidden = Boolean(unit);
            cancelButton.textContent = unit ? "Close aliases" : "Cancel";
            editorPermissions.textContent = unit
                ? "Use the row’s Save or Cancel for all alias changes."
                : "Choose a canonical name, category, and accepted aliases.";
        };

        const editorValues = (includePending = false) => ({
            canonical_name: editorUnitId ? rowDraft(editorUnitId).values.canonical_name : cleanText(nameInput.value),
            category: editorUnitId ? rowDraft(editorUnitId).values.category : categorySelect.value,
            aliases: [...editorAliases, ...(includePending && cleanText(aliasInput.value) ? [cleanText(aliasInput.value)] : [])],
        });
        const editorIsDirty = () => Boolean(originalDraft && (
            unitDraftSignature(editorValues()) !== unitDraftSignature(originalDraft) || cleanText(aliasInput.value)
        ));
        const editorValidation = () => {
            if (editorUnitId) return rowValidation(editorUnitId);
            const local = validateUnitDraft(editorValues(true), registry, editorUnitId);
            return { ...local, ...serverErrors, aliases: { ...local.aliases, ...(serverErrors.aliases || {}) } };
        };
        const syncEditorState = () => {
            if (editorUnitId && !form.hidden) {
                const draft = rowDraft(editorUnitId);
                if (JSON.stringify(draft.values.aliases) !== JSON.stringify(editorAliases) || draft.pendingAlias !== aliasInput.value) {
                    delete draft.errors.aliases;
                    draft.feedback = '';
                }
                draft.values.aliases = [...editorAliases];
                draft.pendingAlias = aliasInput.value;
            }
            const errors = editorValidation();
            const invalid = Boolean(errors.canonical_name || errors.category || Object.keys(errors.aliases).length);
            const dirty = editorIsDirty();
            const busy = mutationPending || aiSuggestionPending || orderPending;
            form.setAttribute("aria-busy", String(mutationPending || aiSuggestionPending));
            form.classList.toggle("is-dirty", dirty);
            saveButton.disabled = busy || !dirty || invalid;
            suggestButton.disabled = busy || !unitKey(editorValues().canonical_name);
            [nameInput, aliasInput, aliasAddButton].forEach(control => { control.disabled = mutationPending || orderPending; });
            categorySelect.disabled = busy;
            categoryUI.refresh(categorySelect);
            cancelButton.disabled = orderPending || (mutationPending && (!editorUnitId || rowDraft(editorUnitId).saving));
            aliasChips.querySelectorAll("button").forEach(button => { button.disabled = mutationPending || orderPending; });
            setFieldError(nameInput, nameError, showValidation ? errors.canonical_name : "");
            setFieldError(categorySelect, categoryError, showValidation ? errors.category : "");
            setFieldError(aliasInput, aliasError, showValidation ? [...new Set(Object.values(errors.aliases))].join(" ") : "");
            editorAliasErrors = errors.aliases;
            Array.from(aliasChips.children).forEach((chip, index) => {
                const error = errors.aliases[index] || "";
                chip.classList.toggle("has-error", Boolean(error));
                chip.title = error;
            });
            const nextStatus = mutationPending ? "Saving changes…" : dirty ? "Unsaved changes" : "";
            if (dirtyStatus.textContent !== nextStatus) dirtyStatus.textContent = nextStatus;
            const aliases = (cleanText(aliasInput.value) && !localAliasError(cleanText(aliasInput.value))
                ? [cleanText(aliasInput.value)] : editorValues().aliases.filter((_, index) => !errors.aliases[index])).slice(0, 2);
            const name = cleanText(editorValues().canonical_name);
            const preview = name ? aliases.length
                ? `${aliases.map(alias => `“${alias}”`).join(" and ")} will normalize to “${name}”.`
                : `“${name}” is accepted as the canonical unit.` : "";
            if (aliasPreview.textContent !== preview) aliasPreview.textContent = preview;
            if (editorUnitId && !form.hidden) syncRowState(rowFor(editorUnitId));
            refreshSuggestions();
            positionAliasPopover();
        };

        // Keep the expanded editor at the same viewport position when rows are rebuilt.
        const captureEditorScroll = (anchor = form) => {
            const top = anchor.getBoundingClientRect().top;
            const scrollers = [];
            for (let element = anchor.parentElement; element; element = element.parentElement) {
                if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) scrollers.push([element, element.scrollTop]);
            }
            scrollers.push([document.scrollingElement, document.scrollingElement.scrollTop]);
            return () => {
                scrollers.forEach(([element, position]) => { element.scrollTop = position; });
                if (anchor.isConnected && anchor.getClientRects().length) {
                    scrollers[0][0].scrollTop += anchor.getBoundingClientRect().top - top;
                }
            };
        };

        const renderAliasChips = () => {
            aliasChips.replaceChildren();
            editorAliases.forEach((alias, index) => {
                const chip = document.createElement("span");
                chip.className = "unit-master-alias-chip";
                if (editorAliasErrors[String(index)]) chip.classList.add("has-error");

                const text = document.createElement("span");
                text.textContent = alias;
                const remove = document.createElement("button");
                remove.type = "button";
                remove.textContent = "×";
                remove.disabled = aiSuggestionPending;
                remove.setAttribute("aria-label", `Remove alias ${alias}`);
                remove.addEventListener("click", () => {
                    editorAliases.splice(index, 1);
                    serverErrors = {};
                    showValidation = true;
                    renderAliasChips();
                    setEditorFeedback("");
                    syncEditorState();
                    aliasInput.focus({ preventScroll: true });
                });
                chip.append(text, remove);
                aliasChips.appendChild(chip);
            });
        };

        const localAliasError = alias => {
            if (!alias) return "Enter an alias first.";
            return validateUnitDraft({ ...editorValues(), aliases: [...editorAliases, alias] }, registry, editorUnitId).aliases[editorAliases.length] || "";
        };

        const resetSuggestions = () => {
            suggestionRequestToken += 1;
            suggestionController?.abort();
            suggestionController = null;
            aiSuggestionPending = false;
            suggestedAliases = [];
            selectedAliases.clear();
            suggestions.hidden = true;
            suggestionChips.replaceChildren();
            suggestButtonLabel.textContent = 'Suggest aliases';
        };

        const refreshSuggestions = () => {
            const seen = new Set(editorValues(true).aliases.map(unitKey));
            suggestedAliases = suggestedAliases.filter(alias => {
                const key = unitKey(alias);
                if (seen.has(key) || localAliasError(alias)) { selectedAliases.delete(alias); return false; }
                seen.add(key); return true;
            });
            const signature = JSON.stringify(suggestedAliases);
            if (suggestionChips.dataset.aliases !== signature) {
                suggestionChips.replaceChildren(...suggestedAliases.map(alias => {
                    const chip = document.createElement('button');
                    chip.type = 'button'; chip.textContent = alias;
                    chip.setAttribute('aria-label', alias);
                    chip.addEventListener('click', () => {
                        if (selectedAliases.has(alias)) selectedAliases.delete(alias); else selectedAliases.add(alias);
                        refreshSuggestions();
                    });
                    return chip;
                }));
                suggestionChips.dataset.aliases = signature;
            }
            [...suggestionChips.children].forEach((chip, index) => {
                chip.setAttribute('aria-pressed', String(selectedAliases.has(suggestedAliases[index])));
                chip.disabled = mutationPending || orderPending || aiSuggestionPending;
            });
            addSelected.disabled = !selectedAliases.size || mutationPending || orderPending || aiSuggestionPending;
            addSelected.hidden = !suggestedAliases.length;
            if (!suggestions.hidden) suggestionStatus.textContent = aiSuggestionPending
                ? 'Suggesting aliases…' : suggestedAliases.length
                    ? 'Choose aliases to add to this draft.' : 'No new aliases to suggest.';
        };

        // Fixed top-layer placement avoids clipped category containers and scroll jumps.
        const positionAliasPopover = () => {
            if (!editorUnitId || form.hidden) return;
            const cell = rowFor(editorUnitId)?.querySelector('.unit-master-aliases');
            if (!cell) return;
            const rect = cell.getBoundingClientRect(), viewport = window.visualViewport;
            const left = (viewport?.offsetLeft || 0) + 12, top = (viewport?.offsetTop || 0) + 12;
            const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
            const right = left + width - 24, bottom = top + height - 24;
            form.style.width = `${Math.min(360, width - 24)}px`;
            form.style.maxHeight = `${height - 24}px`;
            const panel = form.getBoundingClientRect();
            const below = bottom - rect.bottom - 6, above = rect.top - top - 6;
            let y = rect.bottom + 6;
            if (panel.height > below && above > below) y = rect.top - panel.height - 6;
            form.style.left = `${Math.max(left, Math.min(rect.left, right - panel.width))}px`;
            form.style.top = `${Math.max(top, Math.min(y, bottom - panel.height))}px`;
        };

        const addPendingAlias = () => {
            if (mutationPending || orderPending) return false;
            const alias = cleanText(aliasInput.value);
            if (!alias) { aliasInput.focus({ preventScroll: true }); return false; }
            const error = localAliasError(alias);
            showValidation = true;
            syncEditorState();
            setFieldError(aliasInput, aliasError, error);
            if (error) return false;
            editorAliases.push(alias);
            aliasInput.value = "";
            renderAliasChips();
            setEditorFeedback("");
            syncEditorState();
            aliasInput.focus({ preventScroll: true });
            return true;
        };

        const renderStats = () => {
            root.querySelector("[data-unit-master-total-count]").textContent = String(registry.units.length);
            root.querySelector("[data-unit-master-seeded-count]").textContent = String(
                registry.units.filter(unit => unit.seeded).length,
            );
            root.querySelector("[data-unit-master-custom-count]").textContent = String(
                registry.units.filter(unit => !unit.seeded).length,
            );
            root.querySelector("[data-unit-master-alias-count]").textContent = String(
                registry.units.reduce((total, unit) => total + (Array.isArray(unit.aliases) ? unit.aliases.length : 0), 0),
            );
            root.querySelector("[data-unit-master-category-count]").textContent = String(
                registry.categories.length,
            );
        };

        const createUsageCell = unit => {
            const usage = document.createElement("div");
            usage.className = "unit-master-usage";
            usage.setAttribute("role", "cell");
            usage.dataset.mobileLabel = "Used in";
            const recipeCount = Math.max(0, Number(unit.recipe_count) || 0);
            if (!recipeCount) {
                const empty = document.createElement("span");
                empty.className = "unit-master-usage-empty";
                empty.textContent = "0";
                empty.setAttribute("aria-label", `No recipes use ${unit.name}`);
                empty.title = `No recipes currently use ${unit.name}`;
                usage.appendChild(empty);
                return usage;
            }

            const button = document.createElement("button");
            button.type = "button";
            button.className = "unit-master-usage-button";
            button.dataset.unitMasterUsageButton = "";
            button.dataset.unitId = unit.id;
            button.setAttribute("aria-haspopup", "dialog");
            button.setAttribute("aria-controls", "unitMasterUsageDialog");
            button.setAttribute(
                "aria-label",
                `Show ${recipeCount} recipe${recipeCount === 1 ? "" : "s"} using ${unit.name}`,
            );
            button.title = `Show recipes using ${unit.name}`;
            const count = document.createElement("strong");
            count.textContent = String(recipeCount);
            const label = document.createElement("span");
            label.textContent = recipeCount === 1 ? "recipe" : "recipes";
            button.append(count, label);
            usage.appendChild(button);
            return usage;
        };

        const createOrderCell = (item, position) => {
            const label = item.name;
            const cell = document.createElement("div");
            cell.className = "store-section-master-order-cell unit-master-order-cell";
            cell.setAttribute("role", "cell");
            cell.setAttribute("aria-colindex", "1");
            cell.dataset.mobileLabel = "Order";

            const order = document.createElement("div");
            order.className = "store-section-master-order";

            const handle = document.createElement("button");
            handle.type = "button";
            handle.className = "store-section-master-drag-handle";
            handle.dataset.unitMasterDragHandle = "";
            handle.setAttribute("aria-label", `Drag ${label} to reorder`);
            handle.title = `Drag to reorder ${label}`;
            handle.setAttribute("aria-describedby", "unitMasterOrderHelp");
            handle.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown Home End");
            handle.innerHTML = [
                '<svg viewBox="0 0 16 20" aria-hidden="true">',
                '<circle cx="5" cy="4" r="1.4"></circle>',
                '<circle cx="11" cy="4" r="1.4"></circle>',
                '<circle cx="5" cy="10" r="1.4"></circle>',
                '<circle cx="11" cy="10" r="1.4"></circle>',
                '<circle cx="5" cy="16" r="1.4"></circle>',
                '<circle cx="11" cy="16" r="1.4"></circle>',
                "</svg>",
            ].join("");

            const up = document.createElement("button");
            up.type = "button";
            up.value = "move_up";
            up.dataset.unitMasterOrderAction = "up";
            up.setAttribute("aria-label", `Move ${label} up`);
            up.innerHTML = [
                '<svg viewBox="0 0 24 24" aria-hidden="true">',
                '<path d="M12 19V5"></path>',
                '<path d="m6 11 6-6 6 6"></path>',
                "</svg>",
            ].join("");

            const number = document.createElement("span");
            number.className = "store-section-master-order-step";
            number.dataset.unitMasterOrderNumber = "";
            number.textContent = String(position);
            number.setAttribute("aria-label", `Step ${position}`);

            const down = document.createElement("button");
            down.type = "button";
            down.value = "move_down";
            down.dataset.unitMasterOrderAction = "down";
            down.setAttribute("aria-label", `Move ${label} down`);
            down.innerHTML = [
                '<svg viewBox="0 0 24 24" aria-hidden="true">',
                '<path d="M12 5v14"></path>',
                '<path d="m6 13 6 6 6-6"></path>',
                "</svg>",
            ].join("");

            order.append(handle, up, number, down);
            cell.appendChild(order);
            return cell;
        };


        const createUnitRow = (unit, index) => {
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.unitMasterRow = "";
            row.dataset.unitId = unit.id;
            row.dataset.unitMasterSearchValue = `${unit.name} ${(unit.aliases || []).join(" ")}`;

            const name = document.createElement("div");
            name.className = "unit-master-name-cell";
            name.dataset.unitMasterNameCell = "";
            name.setAttribute("role", "cell");
            name.dataset.mobileLabel = "Canonical name";
            const draft = rowDraft(unit.id);
            const nameControl = document.createElement("input");
            nameControl.type = "text";
            nameControl.value = draft.values.canonical_name;
            nameControl.maxLength = 60;
            nameControl.autocomplete = "off";
            nameControl.required = true;
            nameControl.dataset.unitRowName = "";
            nameControl.setAttribute("aria-label", `Canonical name for ${unit.name}`);
            const nameError = document.createElement("small");
            nameError.id = `unitRowNameError-${unit.id}`;
            nameError.className = "unit-master-field-error";
            nameError.dataset.unitRowNameError = "";
            nameError.setAttribute("aria-live", "polite");
            nameError.hidden = true;
            nameControl.setAttribute("aria-describedby", nameError.id);
            name.append(nameControl, nameError);
            const aliases = document.createElement("div");
            aliases.className = "unit-master-aliases";
            aliases.setAttribute("role", "cell");
            aliases.dataset.mobileLabel = "Accepted aliases";
            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${unit.seeded ? "" : " user-created"}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = unit.seeded ? "Built-in" : "User-created";
            const usage = createUsageCell(unit);
            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.unitMasterEditButton = "";
            edit.dataset.unitId = unit.id;
            edit.textContent = "Edit unit";
            edit.setAttribute("aria-label", `Edit unit ${unit.name}`);
            const action = document.createElement("div");
            action.className = "unit-master-action-cell";
            action.setAttribute("role", "cell");
            action.appendChild(edit);
            for (const [key, label, aria] of [['unitRowSave', 'Save', `Save ${unit.name}`], ['unitRowCancel', 'Cancel', `Cancel changes to ${unit.name}`]]) {
                const button = document.createElement('button');
                button.type = 'button'; button.className = 'unit-master-edit-button';
                button.dataset[key] = ''; button.textContent = label; button.disabled = true;
                button.setAttribute('aria-label', aria); action.appendChild(button);
            }
            const feedback = document.createElement('small');
            feedback.className = 'unit-master-row-status'; feedback.dataset.unitRowStatus = '';
            feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
            feedback.hidden = true; action.appendChild(feedback);
            const category = document.createElement("div");
            category.dataset.unitMasterCategoryCell = "";
            category.className = "unit-master-category-cell";
            category.setAttribute("role", "cell");
            category.dataset.mobileLabel = "Category";
            const categoryControl = document.createElement('button');
            categoryControl.dataset.unitRowCategory = '';
            categoryControl.setAttribute('aria-label', `Category for ${unit.name}`);
            categoryControl.value = draft.values.category;
            categoryUI.enhance(categoryControl);
            const categoryError = document.createElement('small');
            categoryError.id = `unitRowCategoryError-${unit.id}`;
            categoryError.className = 'unit-master-field-error'; categoryError.dataset.unitRowCategoryError = '';
            categoryError.setAttribute('aria-live', 'polite'); categoryError.hidden = true;
            categoryControl.setAttribute('aria-describedby', categoryError.id);
            category.append(categoryControl, categoryError);
            row.append(createOrderCell(unit, index + 1), name, aliases, category, usage, sourceBadge, action);
            return row;
        };

        const applySearch = () => {
            const query = unitKey(search.value);
            let visibleCount = 0;
            root.querySelectorAll("[data-unit-master-category]").forEach(category => {
                let categoryCount = 0;
                category.querySelectorAll("[data-unit-master-row]").forEach(row => {
                    // Keep the active editor and its row together while filtering.
                    const visible = !query || unitKey(row.dataset.unitMasterSearchValue).includes(query)
                        || row.dataset.unitId === inlineUnitId || (!form.hidden && row.dataset.unitId === editorUnitId);
                    row.hidden = !visible;
                    if (visible) categoryCount += 1;
                });
                category.hidden = categoryCount === 0;
                category.querySelector("[data-unit-master-category-count-label]").textContent = `${categoryCount} unit${categoryCount === 1 ? "" : "s"}`;
                visibleCount += categoryCount;
            });
            searchEmpty.hidden = visibleCount > 0;
            countLabel.textContent = `Showing ${visibleCount} of ${registry.units.length} Unit${registry.units.length === 1 ? "" : "s"}.`;
            syncOrderControls();
        };

        const categoryRows = container => Array.from(container.querySelectorAll("[data-unit-master-row]"));
        const reorderIsBlocked = () => orderPending || mutationPending || Boolean(inlineUnitId) || !form.hidden || Boolean(unitKey(search.value));
        const syncOrderControls = () => {
            const blocked = reorderIsBlocked();
            root.querySelectorAll("[data-unit-master-category-rows]").forEach(container => {
                const rows = categoryRows(container);
                rows.forEach((row, index) => {
                    const number = row.querySelector("[data-unit-master-order-number]");
                    number.textContent = String(index + 1);
                    number.setAttribute("aria-label", `Step ${index + 1}`);
                    const handle = row.querySelector("[data-unit-master-drag-handle]");
                    handle.draggable = !blocked;
                    handle.setAttribute("aria-disabled", String(blocked));
                    row.querySelector('[data-unit-master-order-action="up"]').disabled = blocked || index === 0;
                    row.querySelector('[data-unit-master-order-action="down"]').disabled = blocked || index === rows.length - 1;
                    row.querySelector("[data-unit-master-edit-button]").disabled = orderPending || mutationPending;
                    syncRowState(row);
                });
            });
            addButtons.forEach(button => { button.disabled = orderPending || mutationPending; });
            importButton.disabled = orderPending || mutationPending;
            syncEditorState();
        };
        const placeRows = (container, rows) => {
            rows.forEach(row => {
                container.appendChild(row);
            });
        };
        const moveRowTo = async (row, targetIndex, trigger) => {
            if (!row || reorderIsBlocked()) return;
            const container = row.closest("[data-unit-master-category-rows]");
            const previous = categoryRows(container);
            const current = previous.indexOf(row);
            const target = Math.max(0, Math.min(previous.length - 1, targetIndex));
            if (current === target) return;
            const ordered = [...previous];
            ordered.splice(target, 0, ordered.splice(current, 1)[0]);
            orderPending = true;
            placeRows(container, ordered);
            syncOrderControls();
            // Announce without inserting a banner above the table during a drag.
            setStatus("Saving unit order…", "info", true);
            try {
                const response = await fetch(root.dataset.updateUrlTemplate.replace("__UNIT_ID__", encodeURIComponent(row.dataset.unitId)), {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify({ action: "move_to", position: target + 1 }),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) throw new Error(result.error || "The unit order could not be saved.");
                registry = result.registry;
                source.textContent = JSON.stringify(registry);
                const category = container.closest("[data-unit-master-category]").dataset.category;
                const byId = new Map(previous.map(item => [item.dataset.unitId, item]));
                const saved = registry.units.filter(unit => unit.category === category);
                placeRows(container, saved.map((unit, index) => byId.get(String(unit.id)) || createUnitRow(unit, index)));
                setStatus(result.message || "Unit order saved.", "success", true);
            } catch (error) {
                placeRows(container, previous);
                status.classList.remove("sr-only");
                setStatus(error.message || "The unit order could not be saved. Try again.", "error");
            } finally {
                orderPending = false;
                applySearch();
                const focusTarget = trigger?.disabled ? row.querySelector("[data-unit-master-drag-handle]") : trigger;
                focusTarget?.focus({ preventScroll: true });
            }
        };
        const clearRowDropState = () => {
            categoryRows(categoryList).forEach(row => row.classList.remove("is-row-drop-before", "is-row-drop-after", "is-row-dragging"));
            rowDropTarget = null;
        };

        const parkEditor = () => {
            if (form.parentElement !== editorHome.parentElement || form.nextElementSibling !== editorHome) {
                editorHome.before(form);
            }
        };

        const syncCategoryGroups = () => {
            const groups = new Map([...categoryList.querySelectorAll('[data-unit-master-category]')].map(group => [group.dataset.category, group]));
            registry.categories.forEach((category, index) => {
                const group = groups.get(category.key) || categoryTemplate.cloneNode(true);
                group.dataset.category = category.key;
                const heading = group.querySelector('h3');
                heading.id = `unitCategory-${category.key}`; heading.textContent = category.label;
                group.setAttribute('aria-labelledby', heading.id);
                group.querySelector('[role="table"]').setAttribute('aria-label', `${category.label} units`);
                if (categoryList.children[index] !== group) categoryList.insertBefore(group, categoryList.children[index] || null);
            });
            return groups;
        };

        // Category-only mutations retain the existing row, inputs, alias editor and
        // draft objects. Only labels, group placement and deleted category IDs change.
        const updateCategories = (nextRegistry, result) => {
            const anchor = inlineUnitId ? rowFor(inlineUnitId) : !form.hidden ? form : categoryList;
            const restoreScroll = captureEditorScroll(anchor);
            const focused = document.activeElement;
            registry = nextRegistry; source.textContent = JSON.stringify(registry);
            if (typeof recipeIngredientUnitRegistryCache !== 'undefined') recipeIngredientUnitRegistryCache = null;
            for (const [id, draft] of rowDrafts) {
                const saved = unitById(id);
                if (saved) draft.original.category = saved.category;
                if (draft.values.category === result.deleted_category_id) {
                    draft.values.category = result.reassign_to || saved?.category || registry.categories[0].key;
                    delete draft.errors.category;
                }
            }
            if (categorySelect.value === result.deleted_category_id) categorySelect.value = result.reassign_to || registry.categories[0].key;
            const oldGroups = syncCategoryGroups();
            registry.units.forEach(unit => {
                const row = rowFor(unit.id);
                const group = categoryList.querySelector(`[data-category="${CSS.escape(unit.category)}"] [data-unit-master-category-rows]`);
                if (row && group && row.parentElement !== group) {
                    group.append(row);
                }
            });
            for (const [key, group] of oldGroups) {
                if (!registry.categories.some(c => c.key === key)) group.remove();
            }
            categoryUI.refreshAll(); renderStats(); applySearch();
            focused?.focus({preventScroll: true}); restoreScroll();
        };

        const renderRegistry = () => {
            parkEditor();
            syncCategoryGroups();
            root.querySelectorAll("[data-unit-master-category]").forEach(category => {
                const rows = category.querySelector("[data-unit-master-category-rows]");
                const units = registry.units.filter(unit => unit.category === category.dataset.category);
                rows.replaceChildren(...units.map(createUnitRow));
            });
            if (!form.hidden && editorUnitId) {
                const row = rowFor(editorUnitId);
                if (row) {
                    returnFocus = row.querySelector('[data-unit-row-alias="add"]');
                    returnFocus?.setAttribute('aria-expanded', 'true');
                }
            }
            renderStats();
            applySearch();
        };

        const updateRegistry = nextRegistry => {
            registry = {
                units: Array.isArray(nextRegistry?.units) ? nextRegistry.units : [],
                aliases: nextRegistry?.aliases && typeof nextRegistry.aliases === "object" ? nextRegistry.aliases : {},
                categories: Array.isArray(nextRegistry?.categories) ? nextRegistry.categories : registry.categories,
            };
            source.textContent = JSON.stringify(registry);
            if (typeof recipeIngredientUnitRegistryCache !== "undefined") {
                recipeIngredientUnitRegistryCache = null;
            }
            renderRegistry();
        };

        const setUsageState = (message, state = "loading") => {
            usageSummary.textContent = "";
            usageResults.replaceChildren();
            const output = document.createElement("div");
            output.className = `unit-master-usage-state is-${state}`;
            output.textContent = message;
            usageResults.appendChild(output);
        };

        const renderUsageMatch = match => {
            const item = document.createElement("li");
            const line = document.createElement("strong");
            line.textContent = match.ingredient_line || match.ingredient_name || "Ingredient line";
            item.appendChild(line);

            const details = [];
            if (match.kind === "option") {
                details.push(match.context ? `Recipe option: ${match.context}` : "Recipe option");
            } else if (match.context) {
                details.push(match.context);
            }
            if (match.is_alias_match && match.matched_as) {
                details.push(`Matched alias: ${match.matched_as}`);
            }
            if (match.optional) details.push("Optional");
            if (details.length) {
                const meta = document.createElement("span");
                meta.textContent = details.join(" · ");
                item.appendChild(meta);
            }
            if (match.edit_url) {
                const edit = document.createElement("a");
                edit.className = "unit-master-usage-match-edit";
                edit.href = match.edit_url;
                edit.target = "_blank";
                edit.rel = "noopener noreferrer";
                edit.textContent = "Edit ingredient";
                edit.setAttribute("aria-label", `Edit ingredient ${match.ingredient_name || "entry"} in recipe`);
                item.appendChild(edit);
            }
            return item;
        };

        const createUsageRecipeVisual = reference => {
            const editUrl = String(reference.edit_url || "");
            const recipeTitle = reference.recipe_title || reference.recipe_id || "Recipe";
            const visual = document.createElement(editUrl ? "a" : "span");
            visual.className = "unit-master-usage-recipe-visual";
            if (editUrl) {
                visual.href = editUrl;
                visual.target = "_blank";
                visual.rel = "noopener noreferrer";
                visual.setAttribute("aria-label", `Open ${recipeTitle}`);
            }

            const fallback = document.createElement("span");
            fallback.className = "unit-master-usage-recipe-fallback";
            fallback.setAttribute("aria-hidden", "true");
            const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
            svg.setAttribute("viewBox", "0 0 24 24");
            svg.setAttribute("focusable", "false");
            const documentOutline = document.createElementNS("http://www.w3.org/2000/svg", "path");
            documentOutline.setAttribute("d", "M6 3h8l4 4v14H6zM14 3v5h4");
            const recipeLines = document.createElementNS("http://www.w3.org/2000/svg", "path");
            recipeLines.setAttribute("d", "M9 12h6M9 16h6");
            svg.append(documentOutline, recipeLines);
            fallback.appendChild(svg);

            const imageUrl = String(reference.recipe_image_url || "");
            if (!imageUrl) {
                visual.appendChild(fallback);
                return visual;
            }

            visual.classList.add("has-image");
            const image = document.createElement("img");
            image.src = imageUrl;
            image.alt = String(reference.recipe_image_alt || `${recipeTitle} image`);
            image.loading = "lazy";
            image.decoding = "async";
            const srcset = String(reference.recipe_image_srcset || "");
            if (srcset) {
                image.srcset = srcset;
                image.sizes = "52px";
            }
            fallback.hidden = true;
            const revealFallback = () => {
                image.hidden = true;
                image.removeAttribute("srcset");
                visual.classList.remove("has-image");
                fallback.hidden = false;
            };
            image.addEventListener("error", revealFallback, { once: true });
            visual.append(image, fallback);
            if (image.complete && !image.naturalWidth) revealFallback();
            return visual;
        };

        const renderUsageReferences = data => {
            usageResults.replaceChildren();
            const references = Array.isArray(data.references) ? data.references : [];
            const total = Math.max(0, Number(data.total) || references.length);
            const lineCount = Math.max(0, Number(data.total_reference_count) || 0);
            usageSummary.textContent = `${total} distinct recipe${total === 1 ? "" : "s"} · ${lineCount} matching ingredient line${lineCount === 1 ? "" : "s"}`;

            if (!references.length) {
                setUsageState("No connected recipes were found for this unit.", "empty");
                return;
            }

            references.forEach(reference => {
                const card = document.createElement("article");
                card.className = "unit-master-usage-recipe";
                const visual = createUsageRecipeVisual(reference);
                const header = document.createElement("header");
                const heading = document.createElement("h3");
                const recipeTitle = reference.recipe_title || reference.recipe_id || "Recipe";
                if (reference.edit_url) {
                    const titleLink = document.createElement("a");
                    titleLink.href = reference.edit_url;
                    titleLink.target = "_blank";
                    titleLink.rel = "noopener noreferrer";
                    titleLink.textContent = recipeTitle;
                    heading.appendChild(titleLink);
                } else {
                    heading.textContent = recipeTitle;
                }
                header.appendChild(heading);
                if (reference.edit_url) {
                    const link = document.createElement("a");
                    link.href = reference.edit_url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = "Open Recipe";
                    header.appendChild(link);
                }
                card.append(visual, header);

                const matches = document.createElement("ul");
                (Array.isArray(reference.matches) ? reference.matches : []).forEach(match => {
                    matches.appendChild(renderUsageMatch(match || {}));
                });
                card.appendChild(matches);
                usageResults.appendChild(card);
            });

            if (total > references.length) {
                const note = document.createElement("p");
                note.className = "unit-master-usage-limit-note";
                note.textContent = `Showing the first ${references.length} recipes.`;
                usageResults.appendChild(note);
            }
        };

        const restoreUsageContext = () => {
            usageScrollState.forEach(({element, overflow, padding, top, left}) => {
                element.style.overflow = overflow; element.style.paddingRight = padding;
                element.scrollTop = top; element.scrollLeft = left;
            });
            usageScrollState = [];
            if (usageReturnFocus?.isConnected) usageReturnFocus.focus({preventScroll: true});
            usageReturnFocus = null;
        };

        const closeUsage = () => {
            usageRequestToken += 1;
            if (usageDialog.open) usageDialog.close();
            restoreUsageContext();
        };

        const openUsage = async (unit, trigger) => {
            if (!unit || !usageDialog) return;
            if (!usageDialog.open) usageReturnFocus = trigger || document.activeElement;
            usageTitle.textContent = `Recipes using ${unit.name}`;
            usageContext.textContent = "Usage is calculated from saved recipe ingredients. Edit an ingredient in its recipe to change its amount or unit, then save the recipe.";
            setUsageState("Loading connected recipes…");
            if (!usageDialog.open) {
                usageScrollState = [...new Set([document.documentElement, document.body, document.getElementById("appContent")])].filter(Boolean).map(element => {
                    const state = {element, overflow: element.style.overflow, padding: element.style.paddingRight, top: element.scrollTop, left: element.scrollLeft};
                    const width = element.clientWidth;
                    const padding = parseFloat(getComputedStyle(element).paddingRight) || 0;
                    element.style.overflow = "hidden";
                    if (element.clientWidth > width) element.style.paddingRight = `${padding + element.clientWidth - width}px`;
                    return state;
                });
                usageDialog.showModal();
                usageDialog.querySelector('[data-unit-master-usage-close]').focus({preventScroll: true});
                usageScrollState.forEach(({element, top, left}) => { element.scrollTop = top; element.scrollLeft = left; });
            }

            const requestToken = ++usageRequestToken;
            const referenceUrl = root.dataset.usageUrlTemplate.replace(
                "__UNIT_ID__",
                encodeURIComponent(unit.id),
            );
            try {
                const response = await fetch(referenceUrl, {
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "fetch",
                    },
                });
                let data = await response.json().catch(() => ({}));
                if (requestToken !== usageRequestToken || !usageDialog.open) return;
                if (!response.ok || data.ok === false) {
                    setUsageState(data.error || "Connected recipes could not be loaded.", "error");
                    return;
                }
                let offset = 0;
                while (data.next_offset != null) {
                    const next = Number(data.next_offset);
                    if (!Number.isInteger(next) || next <= offset) throw new Error("Invalid usage page.");
                    offset = next;
                    const url = new URL(referenceUrl, window.location.href);
                    url.searchParams.set("offset", String(offset));
                    const nextResponse = await fetch(url, {headers: {Accept: "application/json", "X-Requested-With": "fetch"}});
                    const page = await nextResponse.json();
                    if (requestToken !== usageRequestToken || !usageDialog.open) return;
                    if (!nextResponse.ok || page.ok === false) throw new Error("Unable to load remaining recipes.");
                    data = {...page, references: [...data.references, ...page.references]};
                }
                renderUsageReferences(data);
            } catch (error) {
                if (requestToken !== usageRequestToken) return;
                setUsageState("Connected recipes could not be loaded. Try again.", "error");
                console.error("Unable to load unit recipe usage.", error);
            }
        };

        const focusEditorName = () => {
            const target = editorUnitId ? aliasInput : nameInput;
            const rect = target.getBoundingClientRect();
            try {
                target.focus({ preventScroll: true });
            } catch (_error) {
                target.focus();
            }
            if (!editorUnitId && (rect.top < 0 || rect.bottom > window.innerHeight)) {
                nameInput.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
        };

        const openEditor = (unit = null, trigger = null, mode = 'add') => {
            if (orderPending || mutationPending) return;
            if (unit ? !activateInlineRow(unit.id, 'name', false) : !releaseInlineRow()) return;
            if (!form.hidden) {
                if (editorUnitId === String(unit?.id || "")) {
                    returnFocus?.setAttribute('aria-expanded', 'false');
                    returnFocus = trigger || returnFocus;
                    returnFocus?.setAttribute('aria-expanded', 'true');
                    focusEditorName();
                    if (mode === 'suggest') suggestUnitDetails();
                    return;
                }
                if (!closeEditor({ restoreFocus: false })) { focusEditorName(); return; }
            }
            resetSuggestions();
            returnFocus = trigger || document.activeElement;
            editorUnitId = unit ? String(unit.id) : "";
            editorAliases = unit ? [...rowDraft(unit.id).values.aliases] : [];
            editorTitle.textContent = unit ? `Aliases for ${unit.name}` : "Add Unit";
            editorKicker.textContent = unit?.seeded ? "System-seeded" : unit ? "User-created" : "New workspace unit";
            editorUsage.hidden = !unit;
            const count = Number(unit?.recipe_count || 0);
            editorUsage.textContent = `Used in ${count} recipe${count === 1 ? "" : "s"}`;
            editorImpact.hidden = !unit;
            syncEditingContext(unit);
            saveButtonLabel = unit ? "Save changes" : "Add Unit";
            saveButton.textContent = saveButtonLabel;
            nameInput.value = unit?.name || "";
            categorySelect.value = unit?.category || "count_package";
            aliasInput.value = unit ? rowDraft(unit.id).pendingAlias : "";
            originalDraft = unit ? rowDraft(unit.id).original : editorValues();
            showValidation = false;
            setAiPending(false);
            clearErrors();
            renderAliasChips();
            parkEditor();
            form.hidden = false;
            if (unit) {
                form.setAttribute('popover', 'manual');
                form.showPopover();
            }
            form.classList.toggle("is-editing", Boolean(unit));
            addButtons.forEach(button => button.setAttribute("aria-expanded", String(!unit)));
            if (trigger) trigger.setAttribute("aria-expanded", "true");
            syncOrderControls();
            positionAliasPopover();
            focusEditorName();
            if (mode === 'suggest') suggestUnitDetails();
        };

        const closeEditor = ({ restoreFocus = true, discard = false } = {}) => {
            if (orderPending || (mutationPending && (!editorUnitId || rowDraft(editorUnitId).saving))) return false;
            if (!editorUnitId && !discard && !form.hidden && editorIsDirty() && !window.confirm("Discard unsaved changes to this unit?")) return false;
            const restoreScroll = captureEditorScroll(returnFocus?.isConnected ? returnFocus : form);
            resetSuggestions();
            const closingId = editorUnitId;
            if (closingId && !discard) syncEditorState();
            if (originalDraft) {
                nameInput.value = originalDraft.canonical_name;
                categorySelect.value = originalDraft.category;
                editorAliases = [...originalDraft.aliases];
            }
            aliasInput.value = "";
            if (form.matches(':popover-open')) form.hidePopover();
            form.removeAttribute('popover');
            form.removeAttribute('style');
            form.hidden = true;
            clearErrors();
            syncEditorState();
            form.classList.remove("is-editing");
            form.classList.remove('is-alias-popover');
            parkEditor();
            editorUnitId = "";
            if (closingId && discard) resetRow(closingId);
            addButtons.forEach(button => button.setAttribute("aria-expanded", "false"));
            returnFocus?.setAttribute("aria-expanded", "false");
            applySearch();
            const focusTarget = returnFocus?.isConnected && returnFocus.getClientRects().length ? returnFocus : search;
            if (restoreFocus) {
                try {
                    focusTarget.focus({ preventScroll: true });
                } catch (_error) {
                    focusTarget.focus();
                }
            }
            restoreScroll();
            returnFocus = null;
            return true;
        };

        const applyServerErrors = payload => {
            serverErrors = payload.errors || {};
            showValidation = true;
            syncEditorState();
            setEditorFeedback(payload.error || "Unable to save this unit.");
            const firstInvalid = firstInvalidControl();
            if (firstInvalid) firstInvalid.focus({ preventScroll: true });
        };

        const suggestUnitDetails = async () => {
            if (mutationPending || orderPending || aiSuggestionPending) return;
            const canonicalName = cleanText(editorValues().canonical_name);
            if (!canonicalName) {
                setFieldError(nameInput, nameError, "Enter a canonical name before asking AI for suggestions.");
                nameInput.focus();
                return;
            }

            const pendingAlias = cleanText(aliasInput.value);
            const payload = {
                unit_id: editorUnitId,
                canonical_name: canonicalName,
                category: editorValues().category,
                aliases: [...editorAliases, ...(pendingAlias ? [pendingAlias] : [])],
            };
            resetSuggestions();
            const requestToken = ++suggestionRequestToken;
            suggestionController = new AbortController();
            suggestions.hidden = false;
            setAiPending(true);
            setEditorFeedback('');
            try {
                const response = await fetch(root.dataset.suggestUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify(payload),
                    signal: suggestionController.signal,
                });
                const result = await response.json().catch(() => ({}));
                if (requestToken !== suggestionRequestToken || form.hidden) return;
                if (!response.ok || !result.ok) {
                    suggestions.hidden = true;
                    setAiPending(false);
                    applyServerErrors(result);
                    return;
                }

                const suggestion = result.suggestion || {};
                suggestedAliases = Array.isArray(suggestion.aliases)
                    ? suggestion.aliases.map(cleanText).filter(Boolean)
                    : [];
                showValidation = true;
                const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
                setEditorFeedback(
                    warnings.join(" "),
                    warnings.length ? "warning" : "success",
                );
            } catch (error) {
                if (requestToken !== suggestionRequestToken) return;
                suggestions.hidden = true;
                setEditorFeedback("AI suggestions are unavailable right now. Your entered values were not changed.");
                console.error("Unable to suggest unit details.", error);
            } finally {
                if (requestToken === suggestionRequestToken) setAiPending(false);
            }
        };

        const saveRow = async id => {
            id = String(id);
            if (mutationPending || orderPending || (editorUnitId === id && aiSuggestionPending)) return;
            if (!form.hidden && editorUnitId === id) syncEditorState();
            const row = rowFor(id), draft = rowDraft(id), errors = rowValidation(id);
            syncRowState(row);
            if (!rowIsDirty(id) || errors.canonical_name || errors.category || Object.keys(errors.aliases).length) return;
            const payload = rowValues(id);
            payload.canonical_name = cleanText(payload.canonical_name);
            draft.saving = true;
            draft.feedback = '';
            mutationPending = true;
            syncOrderControls();
            try {
                const response = await fetch(root.dataset.updateUrlTemplate.replace('__UNIT_ID__', encodeURIComponent(id)), {
                    method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
                    body: JSON.stringify(payload),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) {
                    draft.errors = result.errors || {};
                    draft.feedback = result.error || 'Unable to save this unit. Try again.';
                    draft.feedbackType = 'error';
                    return;
                }
                const active = document.activeElement;
                const activeId = active.closest('[data-unit-master-row]')?.dataset.unitId;
                const activeSelector = active.matches('[data-unit-row-name]') ? '[data-unit-row-name]'
                    : active.matches('[data-unit-row-category]') ? '[data-unit-row-category]' : null;
                const selection = activeSelector === '[data-unit-row-name]' ? [active.selectionStart, active.selectionEnd] : null;
                const restoreScroll = captureEditorScroll(active.closest('[data-unit-master-row]') || row);
                if (!form.hidden && editorUnitId === id) {
                    resetSuggestions();
                    if (form.matches(':popover-open')) form.hidePopover();
                    form.removeAttribute('popover');
                    form.removeAttribute('style');
                    form.hidden = true;
                    form.classList.remove('is-editing', 'is-alias-popover');
                    editorUnitId = '';
                    originalDraft = null;
                    aliasInput.value = '';
                    returnFocus = null;
                }
                rowDrafts.delete(id);
                inlineUnitId = '';
                updateRegistry(result.registry);
                const savedDraft = rowDraft(id);
                savedDraft.feedback = 'Saved';
                savedDraft.feedbackType = 'success';
                syncRowState(rowFor(id));
                restoreScroll();
                const focusTarget = activeId && activeId !== id && activeSelector ? rowFor(activeId)?.querySelector(activeSelector)
                    : active.isConnected && !active.disabled && active.getClientRects().length ? active : rowFor(id)?.querySelector(`[data-unit-row-activate="${inlineField}"]`);
                const visibleTarget = focusTarget?.getClientRects().length ? focusTarget : search;
                visibleTarget.focus({preventScroll: true});
                if (selection && activeId !== id) visibleTarget.setSelectionRange(...selection);
            } catch (_error) {
                draft.feedback = 'Unable to save this unit. Check your connection and try again.';
                draft.feedbackType = 'error';
            } finally {
                draft.saving = false;
                mutationPending = false;
                syncOrderControls();
            }
        };

        const cancelRow = (id, restoreFocus = true) => {
            if (rowDraft(id).saving) return;
            const row = rowFor(id), restoreScroll = captureEditorScroll(row);
            if (!form.hidden && editorUnitId === String(id)) closeEditor({discard: true, restoreFocus: false});
            else resetRow(id);
            inlineUnitId = '';
            syncOrderControls();
            if (restoreFocus) row.querySelector(`[data-unit-row-activate="${inlineField}"]`).focus({preventScroll: true});
            applySearch();
            restoreScroll();
        };

        const saveUnit = async event => {
            event.preventDefault();
            if (editorUnitId) return saveRow(editorUnitId);
            if (orderPending || mutationPending || aiSuggestionPending) return;
            const restoreScroll = captureEditorScroll(returnFocus?.isConnected ? returnFocus : form);
            showValidation = true;
            syncEditorState();
            if (saveButton.disabled) return;
            if (cleanText(aliasInput.value) && !addPendingAlias()) return;
            clearErrors();
            const payload = {
                canonical_name: cleanText(nameInput.value),
                category: categorySelect.value,
                aliases: [...editorAliases],
            };
            const url = editorUnitId
                ? root.dataset.updateUrlTemplate.replace("__UNIT_ID__", encodeURIComponent(editorUnitId))
                : root.dataset.createUrl;
            mutationPending = true;
            syncOrderControls();
            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            setEditorFeedback("Saving changes…", "pending");
            let saved = false;
            try {
                const response = await fetch(url, {
                    method: editorUnitId ? "PUT" : "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify(payload),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) {
                    applyServerErrors(result);
                    return;
                }
                const savedId = String(result.unit_id || editorUnitId);
                // Rebuild only after the transaction succeeds; draft category changes
                // never move the row or alter the saved usage data.
                form.hidden = true;
                form.classList.remove("is-editing");
                updateRegistry(result.registry);
                editorUnitId = "";
                originalDraft = null;
                aliasInput.value = "";
                addButtons.forEach(button => button.setAttribute("aria-expanded", "false"));
                const row = root.querySelector(`[data-unit-master-row][data-unit-id="${CSS.escape(savedId)}"]`);
                returnFocus = row?.querySelector("[data-unit-master-edit-button]");
                saved = true;
                setStatus(result.message || "Changes saved.", "success");
            } catch (error) {
                setEditorFeedback("The unit could not be saved. Check your connection and try again.");
                console.error("Unable to save unit.", error);
            } finally {
                mutationPending = false;
                syncOrderControls();
                saveButton.textContent = saveButtonLabel;
                if (saved) {
                    restoreScroll();
                    const focusTarget = returnFocus?.getClientRects().length ? returnFocus : search;
                    focusTarget.focus({ preventScroll: true });
                    returnFocus = null;
                } else {
                    firstInvalidControl()?.focus({ preventScroll: true });
                }
            }
        };

        categoryUI = window.createUnitCategoryUI({root, getRegistry: () => registry,
            applyRegistry: updateCategories, announce: message => setStatus(message, 'success', true)});
        categorySelect = categoryUI.enhance(categorySelect);

        addButtons.forEach(button => {
            button.addEventListener("click", event => openEditor(null, event.currentTarget));
        });
        const changeRowField = event => {
            const name = event.target.matches('[data-unit-row-name]');
            if (!name && !event.target.matches('[data-unit-row-category]')) return;
            const row = event.target.closest('[data-unit-master-row]'), id = row.dataset.unitId, draft = rowDraft(id);
            const key = name ? 'canonical_name' : 'category';
            draft.values[key] = event.target.value;
            if (!form.hidden && editorUnitId === id) { resetSuggestions(); setEditorFeedback(''); }
            delete draft.errors[key];
            draft.feedback = ''; draft.feedbackType = '';
            syncRowState(row);
            if (!form.hidden && editorUnitId === id) syncEditorState();
        };
        categoryList.addEventListener('input', changeRowField);
        categoryList.addEventListener('change', changeRowField);
        categoryList.addEventListener("click", event => {
            const aliasControl = event.target.closest('[data-unit-row-alias]');
            if (aliasControl) {
                openEditor(unitById(aliasControl.closest('[data-unit-master-row]').dataset.unitId), aliasControl, aliasControl.dataset.unitRowAlias);
                return;
            }
            const activate = event.target.closest('[data-unit-row-activate]');
            if (activate) {
                activateInlineRow(activate.closest('[data-unit-master-row]').dataset.unitId, activate.dataset.unitRowActivate);
                return;
            }
            const save = event.target.closest('[data-unit-row-save]');
            if (save) { saveRow(save.closest('[data-unit-master-row]').dataset.unitId); return; }
            const cancel = event.target.closest('[data-unit-row-cancel]');
            if (cancel) { cancelRow(cancel.closest('[data-unit-master-row]').dataset.unitId); return; }
            const action = event.target.closest("[data-unit-master-order-action]");
            if (action) {
                const row = action.closest("[data-unit-master-row]");
                const rows = categoryRows(row.parentElement);
                moveRowTo(row, rows.indexOf(row) + (action.dataset.unitMasterOrderAction === "up" ? -1 : 1), action);
                return;
            }
            const usageButton = event.target.closest("[data-unit-master-usage-button]");
            if (usageButton) {
                openUsage(unitById(usageButton.dataset.unitId), usageButton);
                return;
            }
            const button = event.target.closest("[data-unit-master-edit-button]");
            if (!button) return;
            activateInlineRow(button.dataset.unitId);
        });
        categoryList.addEventListener("keydown", event => {
            if (event.target.closest('.is-inline-editing') && event.key === 'Escape') {
                event.preventDefault(); cancelRow(event.target.closest('[data-unit-master-row]').dataset.unitId); return;
            }
            const handle = event.target.closest("[data-unit-master-drag-handle]");
            if (!handle || !["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const row = handle.closest("[data-unit-master-row]");
            const rows = categoryRows(row.parentElement);
            const target = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1
                : rows.indexOf(row) + (event.key === "ArrowUp" ? -1 : 1);
            moveRowTo(row, target, handle);
        });
        categoryList.addEventListener("dragstart", event => {
            const handle = event.target.closest("[data-unit-master-drag-handle]");
            if (!handle) return; // Do not consume text selection or native input dragging.
            if (reorderIsBlocked()) { event.preventDefault(); return; }
            draggedRow = handle.closest("[data-unit-master-row]");
            draggedRow.classList.add("is-row-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", draggedRow.dataset.unitId);
        });
        categoryList.addEventListener("dragover", event => {
            if (!draggedRow) return;
            event.preventDefault();
            clearRowDropState();
            const target = event.target.closest("[data-unit-master-row]");
            if (reorderIsBlocked() || !target || target === draggedRow || target.parentElement !== draggedRow.parentElement) {
                event.dataTransfer.dropEffect = "none";
                return;
            }
            event.dataTransfer.dropEffect = "move";
            draggedRow.classList.add("is-row-dragging");
            const rect = target.getBoundingClientRect();
            rowDropAfter = event.clientY > rect.top + rect.height / 2;
            rowDropTarget = target;
            target.classList.add(rowDropAfter ? "is-row-drop-after" : "is-row-drop-before");
        });
        categoryList.addEventListener("drop", event => {
            if (!draggedRow) return;
            event.preventDefault();
            if (!rowDropTarget || reorderIsBlocked()) return;
            const moving = draggedRow;
            const rows = categoryRows(moving.parentElement);
            let target = rows.indexOf(rowDropTarget) + (rowDropAfter ? 1 : 0);
            if (rows.indexOf(moving) < target) target -= 1;
            clearRowDropState();
            draggedRow = null;
            moveRowTo(moving, target, moving.querySelector("[data-unit-master-drag-handle]"));
        });
        categoryList.addEventListener("dragend", () => {
            clearRowDropState();
            draggedRow = null;
        });
        aliasAddButton.addEventListener("click", addPendingAlias);
        suggestButton.addEventListener("click", suggestUnitDetails);
        addSelected.addEventListener('click', () => {
            if (addSelected.disabled) return;
            refreshSuggestions();
            const additions = suggestedAliases.filter(alias => selectedAliases.has(alias));
            editorAliases.push(...additions);
            selectedAliases.clear();
            renderAliasChips();
            showValidation = true;
            syncEditorState();
            setEditorFeedback(`${additions.length} alias${additions.length === 1 ? '' : 'es'} added to the draft.`, 'success');
            aliasInput.focus({preventScroll: true});
        });
        aliasInput.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addPendingAlias();
            }
        });
        cancelButton.addEventListener("click", () => closeEditor({ discard: !editorUnitId }));
        form.addEventListener("input", event => {
            if (![nameInput, categorySelect, aliasInput].includes(event.target)) return;
            showValidation = true;
            if (event.target === nameInput) delete serverErrors.canonical_name;
            if (event.target === categorySelect) delete serverErrors.category;
            if (event.target === nameInput || event.target === categorySelect) resetSuggestions();
            setEditorFeedback("");
            syncEditorState();
        });
        categorySelect.addEventListener("change", () => { delete serverErrors.category; resetSuggestions(); showValidation = true; syncEditorState(); });
        window.addEventListener("beforeunload", event => {
            if (mutationPending || [...rowDrafts.keys()].some(rowIsDirty) || (!form.hidden && editorIsDirty())) { event.preventDefault(); event.returnValue = ""; }
        });
        form.addEventListener("keydown", event => {
            if (form.hidden) return;
            if (editorUnitId && event.key === 'Tab') {
                const controls = [...form.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')].filter(control => control.getClientRects().length);
                if (event.shiftKey && event.target === controls[0]) {
                    event.preventDefault(); closeEditor();
                } else if (!event.shiftKey && event.target === controls.at(-1)) {
                    event.preventDefault();
                    const row = rowFor(editorUnitId);
                    closeEditor({restoreFocus: false});
                    row.querySelector('[data-unit-row-category]').focus({preventScroll: true});
                }
            }
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            closeEditor();
        });
        document.addEventListener('pointerdown', event => {
            if (!editorUnitId || form.hidden || form.contains(event.target) || event.target.closest('[data-unit-row-alias]')) return;
            closeEditor({restoreFocus: !event.target.closest('button, input, select, textarea, a[href], [tabindex]')});
        });
        document.addEventListener('focusin', event => {
            if (!editorUnitId || form.hidden || form.contains(event.target) || event.target.closest('[data-unit-row-alias]')) return;
            closeEditor({restoreFocus: false});
        });
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || event.defaultPrevented || !editorUnitId || form.hidden) return;
            event.preventDefault(); event.stopPropagation(); closeEditor();
        }, true);
        window.addEventListener('resize', positionAliasPopover);
        document.addEventListener('scroll', positionAliasPopover, true);
        window.visualViewport?.addEventListener('resize', positionAliasPopover);
        window.visualViewport?.addEventListener('scroll', positionAliasPopover);
        new ResizeObserver(positionAliasPopover).observe(form);
        root.querySelectorAll("[data-unit-master-usage-close]").forEach(button => {
            button.addEventListener("click", closeUsage);
        });
        usageDialog.addEventListener("cancel", event => {
            event.preventDefault();
            closeUsage();
        });
        usageDialog.addEventListener("click", event => {
            if (event.target === usageDialog) closeUsage();
        });
        usageDialog.addEventListener("close", () => {
            if (!usageDialog.open) restoreUsageContext();
        });

        // Returning from a recipe editor refreshes calculated counts without replacing a unit draft.
        const refreshUsageCounts = async () => {
            if (mutationPending || document.visibilityState === "hidden") return;
            try {
                const response = await fetch(root.dataset.createUrl, {headers: {Accept: "application/json"}});
                const data = await response.json();
                if (!response.ok || !data.ok || mutationPending) return;
                (data.registry?.units || []).forEach(saved => {
                    const unit = unitById(saved.id);
                    if (!unit) return;
                    unit.recipe_count = saved.recipe_count;
                    const row = root.querySelector(`[data-unit-master-row][data-unit-id="${CSS.escape(String(unit.id))}"]`);
                    const previous = row?.querySelector('.unit-master-usage');
                    if (!previous) return;
                    const returningHere = previous.contains(usageReturnFocus);
                    const next = createUsageCell(unit);
                    previous.replaceWith(next);
                    if (returningHere) usageReturnFocus = next.querySelector('button') || row.querySelector('[data-unit-master-edit-button]');
                    if (!form.hidden && editorUnitId === String(unit.id)) editorUsage.textContent = `Used in ${unit.recipe_count} recipe${unit.recipe_count === 1 ? "" : "s"}`;
                });
                if (usageDialog.open && usageReturnFocus) {
                    await openUsage(unitById(usageReturnFocus.dataset.unitId), usageReturnFocus);
                }
            } catch (_) { /* The next usage open retries through the normal error state. */ }
        };
        window.addEventListener("focus", refreshUsageCounts);
        form.addEventListener("submit", saveUnit);
        let previousSearch = search.value;
        search.addEventListener("input", () => {
            const current = unitById(editorUnitId);
            const hidesEditor = !current || !unitKey(`${current.name} ${(current.aliases || []).join(" ")}`).includes(unitKey(search.value));
            if (!form.hidden && hidesEditor && !closeEditor()) { search.value = previousSearch; return; }
            previousSearch = search.value;
            applySearch();
        });

        const browserUnits = legacyUnitNames();
        const importDismissed = sessionStorage.getItem(IMPORT_DISMISSED_KEY) === "true";
        importPanel.hidden = !browserUnits.length || importDismissed;
        importButton.addEventListener("click", async () => {
            if (orderPending || mutationPending) return;
            if (!form.hidden && !closeEditor()) return;
            mutationPending = true;
            syncOrderControls();
            importButton.disabled = true;
            importButton.textContent = "Importing…";
            try {
                const response = await fetch(root.dataset.importUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify({ units: browserUnits }),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) throw new Error(result.error || "Import failed");
                updateRegistry(result.registry);
                localStorage.removeItem(LEGACY_CUSTOM_UNITS_KEY);
                importPanel.hidden = true;
                setStatus(result.message || "Browser units imported.");
            } catch (error) {
                setStatus("Browser units could not be imported. Try again.", "error");
                console.error("Unable to import browser units.", error);
            } finally {
                mutationPending = false;
                syncOrderControls();
                importButton.disabled = false;
                importButton.textContent = "Import units";
            }
        });
        root.querySelector("[data-unit-master-import-dismiss]").addEventListener("click", () => {
            sessionStorage.setItem(IMPORT_DISMISSED_KEY, "true");
            importPanel.hidden = true;
        });

        // A long-running local server can retain a cached Jinja template while serving
        // the latest JS. Upgrade old static or always-input rows before binding state.
        // Delegation is on the stable category list, so rebuilt rows remain interactive.
        if (root.dataset.unitRowInteraction !== 'click-to-edit') {
            renderRegistry();
            root.dataset.unitRowInteraction = 'click-to-edit';
        }
        renderStats();
        applySearch();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initUnitMasterPage, { once: true });
    } else {
        initUnitMasterPage();
    }
}());
