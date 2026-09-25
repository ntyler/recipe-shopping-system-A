/* Meal-plan shopping reviews use saved, server-calculated quantities. */
(function (global) {
    'use strict';
    const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const api = '/api/meal-plan/shopping';
    let state = null, listsState = null;
    const node = (dialog, selector) => dialog.querySelector(selector);
    function status(dialog, selector, message = '', error = false) {
        const target = node(dialog, selector);
        target.textContent = message;
        target.hidden = !message;
        target.classList.toggle('error', error);
    }
    async function request(path, body, signal, method = 'POST') {
        const url = typeof global.withCanonicalViewerUserId === 'function' ? global.withCanonicalViewerUserId(api + path) : api + path;
        const response = await fetch(url, {method, cache:'no-store', signal,
            ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})});
        if (response.redirected) throw new Error('Sign in again, then reopen your shopping plan.');
        let data;
        try { data = await response.json(); }
        catch (error) { throw new Error('Unable to load shopping details. Please try again.'); }
        if (!data || typeof data !== 'object') throw new Error('Unable to load shopping details. Please try again.');
        if (!response.ok || data.ok === false) {
            const error = new Error(data.error || data.message || 'Unable to load shopping details. Please try again.');
            error.status = response.status;
            throw error;
        }
        return data;
    }
    function content(s, html) {
        node(s.dialog, '[data-meal-shopping-content]').innerHTML = html;
    }
    function focusContent(dialog, selector) {
        node(dialog, selector)?.querySelector('input:not(:disabled), button:not(:disabled), select:not(:disabled)')?.focus({preventScroll:true});
    }
    function buttons(s, disabled) {
        s.dialog.setAttribute('aria-busy', String(disabled));
        s.dialog.querySelectorAll('button, input, select').forEach(control => {control.disabled = disabled;});
        if (!disabled && s.step === 'review') syncIncluded(s);
        if (!disabled && s.step === 'choose' && s.initial && !s.initial.sources.length) {
            const reviewButton = node(s.dialog, '[data-shopping-action="review"]');
            if (reviewButton) reviewButton.disabled = true;
        }
    }
    const selectionFor = sources => ({
        batch_ids:sources.filter(source => source.kind === 'batch').map(source => source.record_id || source.id),
        meal_ids:sources.filter(source => source.kind === 'meal').map(source => source.record_id || source.id),
    });
    function sourceLabel(source) {
        return `${source.servings} servings · ${source.kind === 'batch' ? 'Prep batch' : 'Meal'} · ${source.date_from}${source.date_to && source.date_to !== source.date_from ? ' – ' + source.date_to : ''}`;
    }
    function choose(s) {
        s.step = 'choose';
        status(s.dialog, '[data-meal-shopping-status]');
        const selected = s.selectedIds || new Set(s.initial.sources.map(source => `${source.kind}:${source.id}`));
        content(s, `<p class="meal-shopping-steps">1. Choose meals <span>→ 2. Review ingredients</span></p>
            <p class="meal-shopping-help">Each prep batch is included once, for all its prepared servings—even when it spans more than one week.</p>
            <div class="meal-shopping-sources">${s.initial.sources.map((source,index) => `<label class="meal-shopping-source"><input type="checkbox" data-shopping-source="${index}" ${selected.has(`${source.kind}:${source.id}`) ? 'checked' : ''}><span><strong>${escape(source.recipe_name)}</strong><small>${escape(sourceLabel(source))}</small>${source.error ? `<small class="error">${escape(source.error)}</small>` : ''}</span></label>`).join('') || '<p class="meal-shopping-empty">No planned meals in this selection.</p>'}</div>
            <div class="meal-shopping-actions"><button type="button" data-shopping-action="cancel">Cancel</button><button type="button" class="app-page-primary-action" data-shopping-action="review" ${s.initial.sources.length ? '' : 'disabled'}>Review ingredients</button></div>`);
    }
    function review(s) {
        s.step = 'review';
        const data = s.review;
        content(s, `<p class="meal-shopping-steps"><span>1. Choose meals →</span> 2. Review ingredients</p>
            <p class="meal-shopping-summary">${data.sources.length} ${data.sources.length === 1 ? 'meal or prep batch' : 'meals and prep batches'} · ${data.items.length} ingredients</p>
            ${(data.warnings || []).map(message => `<p class="meal-shopping-help">${escape(message)}</p>`).join('')}
            ${(data.blockers || []).map(message => `<p class="meal-shopping-help error">${escape(message)}</p>`).join('')}
            <p class="meal-shopping-help">Uncheck anything you already have. Pantry matches are suggestions; check you have enough before excluding them.</p>
            ${data.items.some(item => item.pantry_matches?.length) ? '<button type="button" data-shopping-action="exclude-pantry">Exclude pantry matches</button>' : ''}
            <div class="meal-shopping-items">${data.items.map((item,index) => `<div class="meal-shopping-item"><label><input type="checkbox" data-shopping-item="${index}" ${item.included !== false ? 'checked' : ''}><span><strong>${escape(item.name)}</strong><small>${escape(item.quantity || 'As needed')}</small></span></label>
                ${item.pantry_matches?.length ? `<p class="meal-shopping-help">In pantry: ${item.pantry_matches.map(match => escape([match.name,match.quantity,match.unit,match.condition ? '(' + match.condition + ')' : ''].filter(value => value !== undefined && value !== '').join(' '))).join('; ')}</p>` : ''}
                ${(item.sources || []).length ? `<details><summary>Used in ${item.sources.length} ${item.sources.length === 1 ? 'meal or batch' : 'meals / batches'}</summary><ul>${item.sources.map(source => `<li>${escape(source.recipe_name)} — ${escape(source.quantity || 'As needed')}</li>`).join('')}</ul></details>` : ''}</div>`).join('') || '<p class="meal-shopping-empty">No ingredients available. Resolve any ingredient choices in Meal Planner, then try again.</p>'}</div>
            <label class="meal-shopping-field">Add to<select data-shopping-destination><option value="current">Current shopping list</option>${(data.lists || []).filter(list => list.id !== 'current').map(list => `<option value="${escape(list.id)}">${escape(list.name)}</option>`).join('')}<option value="__new__">New shopping list…</option></select></label>
            <label class="meal-shopping-field" data-shopping-name-field hidden>List name<input type="text" data-shopping-name maxlength="100" value="${escape(s.initialSelection.week_start ? 'Meal prep – ' + s.initialSelection.week_start : data.sources[0]?.recipe_name + ' – Meal prep')}" autocomplete="off"></label>
            <div class="meal-shopping-actions"><button type="button" data-shopping-action="back">Back</button><button type="button" class="app-page-primary-action" data-shopping-action="save">Add to shopping list</button></div>`);
        syncIncluded(s);
    }
    function syncIncluded(s) {
        const checked = [...s.dialog.querySelectorAll('[data-shopping-item]')].filter(input => input.checked).length;
        const save = node(s.dialog, '[data-shopping-action="save"]');
        if (save) {
            save.disabled = s.busy || !checked || s.review.can_add === false || !!s.review.blockers?.length;
            save.textContent = `Add ${checked} ${checked === 1 ? 'item' : 'items'} to list`;
        }
    }
    async function load(s, selection, initial = false) {
        s.controller?.abort();
        const controller = s.controller = new AbortController();
        s.busy = true;
        buttons(s, true);
        status(s.dialog, '[data-meal-shopping-status]', 'Calculating ingredients…');
        try {
            const data = await request('/review', {selection}, controller.signal);
            if (controller.signal.aborted || state !== s) return;
            s.review = data;
            s.selection = data.selection || selection;
            status(s.dialog, '[data-meal-shopping-status]');
            if (initial) {s.initial = data; choose(s);} else review(s);
        } catch (error) {
            if (!controller.signal.aborted && state === s) {
                status(s.dialog, '[data-meal-shopping-status]', error.message, true);
                if (initial) content(s, '<div class="meal-shopping-actions"><button type="button" data-shopping-action="cancel">Close</button><button type="button" data-shopping-action="retry">Retry</button></div>');
            }
        } finally {
            if (state === s && !controller.signal.aborted) {s.busy = false; buttons(s, false); focusContent(s.dialog, '[data-meal-shopping-content]');}
        }
    }
    async function save(s) {
        if (s.busy || s.step !== 'review' || s.review.can_add === false || s.review.blockers?.length) return;
        const inputs = [...s.dialog.querySelectorAll('[data-shopping-item]')];
        if (!inputs.some(input => input.checked)) return;
        const destination = node(s.dialog, '[data-shopping-destination]').value;
        const name = node(s.dialog, '[data-shopping-name]').value.trim();
        if (destination === '__new__' && !name) {
            status(s.dialog, '[data-meal-shopping-status]', 'Enter a name for the new shopping list.', true);
            node(s.dialog, '[data-shopping-name]').focus(); return;
        }
        const payload = {selection:s.selection, review_token:s.review.review_token,
            excluded_item_ids:inputs.filter(input => !input.checked).map(input => s.review.items[Number(input.dataset.shoppingItem)].id),
            ...(destination === '__new__' ? {new_list_name:name} : {list_id:destination})};
        s.busy = s.saving = true; buttons(s, true);
        status(s.dialog, '[data-meal-shopping-status]', 'Saving shopping list…');
        try {
            const data = await request('/add', payload);
            if (state !== s) return;
            s.step = 'done'; s.savedList = data.list;
            content(s, `<p class="meal-shopping-summary">Added to ${escape(data.list.name)}.</p><p class="meal-shopping-help">Your other shopping items have been kept.</p><div class="meal-shopping-actions"><button type="button" data-shopping-action="cancel">Done</button><button type="button" data-shopping-action="schedule">Schedule shopping trip</button><button type="button" class="app-page-primary-action" data-shopping-action="view">Open shopping list</button></div>`);
            status(s.dialog, '[data-meal-shopping-status]', 'Shopping list saved.');
        } catch (error) {
            if (state !== s) return;
            if (error.status === 409) {
                s.step = 'stale';
                content(s, '<div class="meal-shopping-actions"><button type="button" data-shopping-action="cancel">Close</button><button type="button" data-shopping-action="retry">Review updated plan</button></div>');
                status(s.dialog, '[data-meal-shopping-status]', 'The plan or pantry changed. Reload and review the ingredients before adding them.', true);
            }
            else status(s.dialog, '[data-meal-shopping-status]', error.message, true);
        } finally {
            if (state === s) {s.busy = s.saving = false; buttons(s, false); if (s.step !== 'review') focusContent(s.dialog, '[data-meal-shopping-content]');}
        }
    }
    function bind(s) {
        s.dialog.onclick = event => {
            const action = event.target.closest('[data-shopping-action]')?.dataset.shoppingAction;
            if (!action || s.busy) return;
            if (action === 'cancel') close();
            if (action === 'retry') void load(s, s.initialSelection, true);
            if (action === 'back') {choose(s); focusContent(s.dialog, '[data-meal-shopping-content]');}
            if (action === 'review') {
                const sources = [...s.dialog.querySelectorAll('[data-shopping-source]')].filter(input => input.checked).map(input => s.initial.sources[Number(input.dataset.shoppingSource)]);
                if (!sources.length) {status(s.dialog, '[data-meal-shopping-status]', 'Choose at least one meal or prep batch.', true); return;}
                s.selectedIds = new Set(sources.map(source => `${source.kind}:${source.id}`));
                void load(s, selectionFor(sources));
            }
            if (action === 'exclude-pantry') {s.dialog.querySelectorAll('[data-shopping-item]').forEach(input => {if (s.review.items[Number(input.dataset.shoppingItem)].pantry_matches?.length) input.checked = false;}); syncIncluded(s);}
            if (action === 'save') void save(s);
            if (action === 'view') {
                const id = s.savedList.id; close();
                openList(id, s.opener);
            }
            if (action === 'schedule') {
                const initial = {list_id:s.savedList.id,source_ids:s.review.sources.map(source => source.id)};
                close();
                void global.PlannerViews.openTrip(initial,s.opener);
            }
        };
        s.dialog.onchange = event => {
            if (event.target.matches('[data-shopping-item]')) syncIncluded(s);
            if (event.target.matches('[data-shopping-destination]')) node(s.dialog, '[data-shopping-name-field]').hidden = event.target.value !== '__new__';
        };
        s.dialog.oncancel = event => {event.preventDefault(); close();};
    }
    function open(selection, opener = document.activeElement) {
        const dialog = document.getElementById('mealPlanShoppingDialog');
        if (!dialog || state?.saving) return;
        state?.controller?.abort();
        const s = state = {dialog,opener,initialSelection:selection,busy:false,step:'choose'};
        bind(s); content(s, '');
        if (!dialog.open) dialog.showModal();
        void load(s, selection, true);
    }
    function close() {
        if (!state || state.saving) return false;
        const s = state; state = null; s.controller?.abort(); s.dialog.close(); s.opener?.focus({preventScroll:true});
        return false;
    }
    async function loadLists(s, id = '') {
        s.controller?.abort(); const controller = s.controller = new AbortController();
        s.id = id;
        status(s.dialog, '[data-meal-shopping-lists-status]', 'Loading shopping lists…');
        const root = node(s.dialog, '[data-meal-shopping-lists-content]');
        root.innerHTML = '';
        try {
            const data = await request('/lists' + (id ? '/' + encodeURIComponent(id) : ''), undefined, controller.signal, 'GET');
            if (controller.signal.aborted || listsState !== s) return;
            s.list = data.list || null;
            status(s.dialog, '[data-meal-shopping-lists-status]');
            if (s.list) {
                root.innerHTML = `<button type="button" data-shopping-list-back>← All saved lists</button><h4>${escape(s.list.name)}</h4><div class="meal-shopping-list-editor">${s.list.items.map((item,index) => `<label class="meal-shopping-source"><input type="checkbox" data-shopping-checked="${index}" ${item.checked ? 'checked' : ''}><span><strong>${escape(item.name)}</strong><small>${escape(item.quantity || 'As needed')}</small></span></label>`).join('') || '<p class="meal-shopping-empty">This list has no items.</p>'}</div>`;
            } else {
                root.innerHTML = (data.lists || []).filter(list => list.id !== 'current').map(list => `<button type="button" class="meal-shopping-saved-row" data-shopping-list-id="${escape(list.id)}"><strong>${escape(list.name)}</strong><span>${escape(list.item_count ?? '')} items →</span></button>`).join('') || '<p class="meal-shopping-empty">No saved meal shopping lists yet. Choose “New shopping list” when shopping a meal plan.</p>';
            }
        } catch (error) {
            if (!controller.signal.aborted && listsState === s) {status(s.dialog, '[data-meal-shopping-lists-status]', error.message, true); root.innerHTML = '<button type="button" data-shopping-list-retry>Retry</button>';}
        }
        if (!controller.signal.aborted && listsState === s) focusContent(s.dialog, '[data-meal-shopping-lists-content]');
    }
    async function openLists(id = '', opener = document.activeElement) {
        const dialog = document.getElementById('mealPlanShoppingListsDialog'); if (!dialog || listsState?.saving) return;
        listsState?.controller?.abort();
        const s = listsState = {dialog,opener,id};
        dialog.onclick = event => {
            if (s.saving) return;
            const row = event.target.closest('[data-shopping-list-id]');
            if (row) void loadLists(s, row.dataset.shoppingListId);
            if (event.target.closest('[data-shopping-list-back]')) void loadLists(s);
            if (event.target.closest('[data-shopping-list-retry]')) void loadLists(s, s.id);
        };
        dialog.onchange = async event => {
            const input = event.target;
            if (!input.matches('[data-shopping-checked]') || s.saving) return;
            const item = s.list.items[Number(input.dataset.shoppingChecked)], checked = input.checked;
            s.saving = true;
            dialog.querySelectorAll('button, input').forEach(control => {control.disabled = true;});
            try {
                await request(`/lists/${encodeURIComponent(s.list.id)}/items/${encodeURIComponent(item.id)}`, {checked}, undefined, 'PATCH');
                item.checked = checked; status(dialog, '[data-meal-shopping-lists-status]', 'Saved.');
            } catch (error) {input.checked = !checked; status(dialog, '[data-meal-shopping-lists-status]', error.message, true);}
            finally {s.saving = false; dialog.querySelectorAll('button, input').forEach(control => {control.disabled = false;});}
        };
        dialog.oncancel = event => {event.preventDefault(); closeLists();};
        if (!dialog.open) dialog.showModal();
        await loadLists(s, id);
    }
    function closeLists() {
        if (!listsState || listsState.saving) return false;
        const s = listsState; listsState = null; s.controller?.abort(); s.dialog.close(); s.opener?.focus({preventScroll:true});
        return false;
    }
    function openList(id,opener = document.activeElement) {
        if (id === 'current') {
            // A fresh document also refreshes an already-loaded shopping workspace.
            const destination = `/?shopping_updated=${Date.now()}#shoppingListsPage`;
            global.location.assign(typeof global.withCanonicalViewerUserId === 'function' ? global.withCanonicalViewerUserId(destination) : destination);
        } else void openLists(id,opener);
        return false;
    }
    global.MealPlanShopping = {open,close,openLists,closeLists,openList};
})(window);
