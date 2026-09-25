/* Three views of the same saved plan: meals, preparation, and shopping trips. */
(function (global) {
    'use strict';
    const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const views = {
        meals:['Meal Planner','Plan meals for the week using recipes already saved in AI Pantry.'],
        prep:['Meal Prep Planner','Prepare your batches before the meals they will serve.'],
        shopping:['Shopping Planner','Schedule grocery trips and open the shopping lists they cover.'],
    };
    let page = null, active = 'meals', loadController = null, tripState = null;
    const query = (root, selector) => root?.querySelector(selector);
    const canonical = url => typeof global.withCanonicalViewerUserId === 'function' ? global.withCanonicalViewerUserId(url) : url;
    const localDate = () => {
        const today = new Date();
        return `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    };
    function setStatus(root, selector, message = '', error = false) {
        const target = query(root, selector);
        if (!target) return;
        target.textContent = message; target.hidden = !message;
        target.classList.toggle('error', error);
    }
    async function request(path, body, method = 'GET', signal) {
        const response = await fetch(canonical(path), {method,cache:'no-store',signal,
            ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
        if (response.redirected) throw new Error('Sign in again, then reopen the planner.');
        let data;
        try {data = await response.json();} catch (_) {throw new Error('Unable to load your plan. Please try again.');}
        if (!response.ok || !data || data.ok === false) throw new Error(data?.error || 'Unable to save your plan. Please try again.');
        return data;
    }
    function syncNavigation(updateUrl) {
        if (!page) return;
        const [title,description] = views[active];
        query(page,'[data-planner-title]').textContent = title;
        query(page,'[data-planner-description]').textContent = description;
        page.querySelectorAll('[data-planner-view]').forEach(button => {
            const selected = button.dataset.plannerView === active;
            button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
        });
        page.querySelectorAll('[data-planner-panel]').forEach(panel => {panel.hidden = panel.dataset.plannerPanel !== active;});
        query(page,'[data-planner-add-meal]').hidden = active === 'shopping';
        query(page,'[data-planner-add-trip]').hidden = active !== 'shopping';
        page.querySelectorAll('[data-planner-week-link]').forEach(link => {
            const url = new URL(link.getAttribute('href'), global.location.href);
            url.searchParams.set('planner_view', active);
            link.setAttribute('href', canonical(url.pathname + url.search + url.hash));
        });
        if (updateUrl) {
            const url = new URL(global.location.href);
            url.searchParams.set('planner_view',active);
            url.searchParams.set('meal_week',page.dataset.mealWeek);
            global.history.replaceState(global.history.state,'',url);
        }
    }
    function init(root = document.getElementById('mealPlannerPage')) {
        if (!root || !query(root,'[data-planner-view]')) return;
        page = root;
        const requested = new URL(global.location.href).searchParams.get('planner_view');
        active = Object.hasOwn(views,requested) ? requested : 'meals';
        page.querySelectorAll('[data-planner-view]').forEach(button => {
            button.onclick = () => select(button.dataset.plannerView);
            button.onkeydown = event => {
                const keys = Object.keys(views), index = keys.indexOf(active);
                const next = {ArrowRight:keys[(index+1)%3],ArrowLeft:keys[(index+2)%3],Home:keys[0],End:keys[2]}[event.key];
                if (!next) return;
                event.preventDefault(); select(next);
                query(page,`[data-planner-view="${next}"]`)?.focus();
            };
        });
        page.querySelectorAll('[data-planner-panel]').forEach(panel => {panel.onclick = handlePanelClick;});
        syncNavigation(false);
        void refresh();
    }
    function select(view) {
        if (!Object.hasOwn(views,view)) return;
        active = view; syncNavigation(true);
        if (view === 'meals' && page?.dataset.mealPlannerStale && typeof global.refreshMealPlannerWorkspace === 'function') {
            loadController?.abort();
            void global.refreshMealPlannerWorkspace();
        } else void refresh();
    }
    function panelRoot() {return query(page,`[data-planner-panel="${active}"]`);}
    async function refresh() {
        loadController?.abort();
        if (!page || active === 'meals') return;
        const root = panelRoot(), currentPage = page, view = active;
        const controller = loadController = new AbortController();
        root.innerHTML = '<p class="planner-empty" role="status">Loading your plan…</p>';
        root.setAttribute('aria-busy','true');
        try {
            const data = await request('/api/planning/week?week_start='+encodeURIComponent(page.dataset.mealWeek),undefined,'GET',controller.signal);
            if (controller.signal.aborted || page !== currentPage || view !== active) return;
            renderWeek(root,data,view);
        } catch (error) {
            if (!controller.signal.aborted && page === currentPage && active === view) {
                root.innerHTML = `<p class="planner-empty error" role="alert">${escape(error.message)}</p><button type="button" data-planner-action="retry">Retry</button>`;
            }
        } finally {if (!controller.signal.aborted) root.removeAttribute('aria-busy');}
    }
    function editPrepButton(batchId, mealId, name) {
        return mealId ? `<button type="button" data-planner-action="edit-prep" data-batch-id="${escape(batchId)}" data-meal-id="${escape(mealId)}" data-meal-name="${escape(name)}">Edit prep plan</button>` : '';
    }
    function prepCard(step,data) {
        const mealId = step.meal_id || data.meals?.find(meal => meal.batch_id === step.batch_id)?.id;
        return `<article class="planner-prep-card${step.completed ? ' is-complete' : ''}" data-meal-prep-step>
            <strong class="planner-card-title">${escape(step.recipe_name)}</strong>
            <label><input type="checkbox" data-batch-id="${escape(step.batch_id)}" data-step-id="${escape(step.id)}" ${step.completed ? 'checked' : ''}> <span>${escape(step.instruction)}</span></label>
            <p data-meal-prep-status role="status" hidden></p>
            <div class="planner-card-actions">${editPrepButton(step.batch_id,mealId,step.recipe_name)}</div></article>`;
    }
    function tripCard(trip) {
        const names = [...new Set((trip.sources || []).map(source => source.recipe_name))];
        const status = ({planned:'Planned',in_progress:'In progress',completed:'Completed'})[trip.status] || 'Planned';
        return `<article class="planner-trip-card">
            <strong class="planner-card-title">${escape(trip.store_label || 'Shopping trip')}</strong>
            <p class="planner-card-meta">${escape(trip.list_name)}</p>
            ${names.length ? `<p class="planner-card-meta">${names.slice(0,2).map(escape).join(' · ')}${names.length > 2 ? ` · +${names.length-2} more` : ''}</p>` : ''}
            <span class="planner-trip-status is-${escape(trip.status)}">${status}</span>
            <details class="planner-card-menu"><summary aria-label="Actions for ${escape(trip.list_name)}">⋯</summary><div>
                <button type="button" data-planner-action="edit-trip" data-trip-id="${escape(trip.id)}">Edit trip</button>
                <button type="button" data-planner-action="delete-trip" data-trip-id="${escape(trip.id)}">Remove trip</button>
            </div></details>
            <div class="planner-card-actions"><button type="button" data-planner-action="open-list" data-list-id="${escape(trip.list_id)}" ${trip.list_available === false ? 'disabled' : ''}>Open list</button></div>${trip.list_available === false ? '<small>Linked list is unavailable.</small>' : ''}</article>`;
    }
    function renderWeek(root,data,view) {
        const prep = view === 'prep';
        const groups = (prep ? data.prep_steps_by_day : data.shopping_trips_by_day) || {};
        const count = Object.values(groups).reduce((total,rows) => total + rows.length,0);
        root.innerHTML = `<p class="planner-view-summary">${count} ${prep ? 'prep tasks' : 'shopping trips'} this week${prep ? '' : ' · Trips link to your saved lists; checking off groceries stays in Shopping Lists.'}</p>
            <div class="planner-week-grid">${data.days.map(day => `<section class="planner-day${day.is_today ? ' is-today' : ''}"><h3>${escape(day.weekday)} <span>${escape(day.day_label)}</span></h3><div class="planner-day-cards">
                ${(groups[day.date] || []).map(item => prep ? prepCard(item,data) : tripCard(item)).join('') || `<p class="planner-empty">${prep ? 'No prep tasks' : 'No trips'}</p>`}
                ${prep ? '' : `<button type="button" class="planner-add-trip" data-planner-action="add-trip" data-date="${escape(day.date)}">+ Trip</button>`}</div></section>`).join('')}</div>
            ${prep && data.unscheduled_prep_batches?.length ? `<section class="planner-unscheduled"><h3>Needs a prep date</h3><p>These batches serve meals this week. Open a prep plan to add dated prep tasks.</p><div class="planner-unscheduled-cards">${data.unscheduled_prep_batches.map(batch => `<article class="planner-prep-card"><strong class="planner-card-title">${escape(batch.recipe_name)}</strong><p class="planner-card-meta">${escape(batch.batch_servings)} prepared servings</p><div class="planner-card-actions">${editPrepButton(batch.id,batch.meal_id || batch.allocations?.[0]?.id,batch.recipe_name)}<button type="button" data-planner-action="shop-batch" data-batch-id="${escape(batch.id)}">Shop batch</button></div></article>`).join('')}</div></section>` : ''}`;
        root.querySelectorAll('[data-step-id]').forEach(input => {
            input.onchange = async () => {
                await global.toggleMealPlannerPrepStep(input);
                // Refresh the Meals view too, so its existing prep row stays current.
                if (page) page.dataset.mealPlannerStale = '1';
            };
        });
        root.querySelectorAll('.planner-card-menu').forEach(menu => {
            menu.ontoggle = () => {if (menu.open) closeCardMenus(menu);};
        });
    }
    function handlePanelClick(event) {
        const control = event.target.closest('[data-planner-action]');
        if (!control || control.disabled) return;
        const action = control.dataset.plannerAction;
        if (action === 'retry') void refresh();
        if (action === 'add-trip') void openTrip({date:control.dataset.date},control);
        if (action === 'edit-trip' || action === 'delete-trip') void openTrip({id:control.dataset.tripId,remove:action === 'delete-trip'},control);
        if (action === 'open-list') global.MealPlanShopping.openList(control.dataset.listId,control);
        if (action === 'edit-prep') global.openMealPlannerEditDialog(control,'batch');
        if (action === 'shop-batch') global.openMealPlanShopping(control.dataset.batchId,control);
        const menu = control.closest('details'); if (menu) menu.open = false;
    }
    function closeCardMenus(except = null,restoreFocus = false) {
        page?.querySelectorAll('.planner-card-menu[open]').forEach(menu => {
            if (menu === except) return;
            menu.open = false;
            if (restoreFocus) query(menu,'summary')?.focus();
        });
    }
    function tripContent(s,html) {query(s.dialog,'[data-trip-content]').innerHTML = html;}
    function tripBusy(s,busy) {
        s.busy = busy; s.dialog.setAttribute('aria-busy',String(busy));
        s.dialog.querySelectorAll('input,select,button').forEach(control => {control.disabled = busy;});
        const close = query(s.dialog,'[data-trip-close]');
        if (close) close.disabled = s.saving;
    }
    function selectedList(s) {
        const id = query(s.dialog,'[name="list_id"]')?.value;
        return (s.options?.lists || []).find(list => list.id === id) || (s.trip?.list_id === id ? {id,sources:s.trip.sources} : null);
    }
    function sourceOptions(s,list) {
        const combined = [...(list?.sources || []),...(s.trip?.list_id === list?.id ? s.trip.sources || [] : [])];
        return [...new Map(combined.map(source => [source.id,source])).values()];
    }
    function renderSources(s,selection) {
        const list = selectedList(s), sources = sourceOptions(s,list);
        const selected = new Set(selection ?? sources.map(source => source.id));
        query(s.dialog,'[data-trip-sources]').innerHTML = `<p class="meal-shopping-help">${list?.is_current || list?.id === 'current' ? 'This trip opens your live Current shopping list, including later changes.' : 'This trip opens the selected saved list, including later changes.'}</p>
            ${sources.length ? `<fieldset><legend>Meals and prep batches covered</legend>${sources.map(source => `<label class="planner-trip-source"><input type="checkbox" data-trip-source value="${escape(source.id)}" ${selected.has(source.id) ? 'checked' : ''}><span>${escape(source.recipe_name)} · ${escape(source.servings)} servings</span></label>`).join('')}</fieldset>` : '<p class="meal-shopping-help">No linked meals or prep batches on this list.</p>'}`;
    }
    function renderTrip(s) {
        s.mode = 'edit';
        const trip = {...(s.trip || s.initial),...s.draft};
        query(s.dialog,'#shoppingTripDialogTitle').textContent = s.trip ? 'Edit shopping trip' : 'Schedule shopping trip';
        const lists = s.options.lists || [], stores = s.options.stores || [];
        const listId = trip.list_id || lists[0]?.id || 'current';
        const listMissing = !lists.some(list => list.id === listId);
        const storeMissing = trip.store_key && !stores.some(store => store.key === trip.store_key);
        tripContent(s, `<form class="planner-trip-form" data-trip-form><div class="planner-trip-fields">
            <label>Date<input name="date" type="date" required value="${escape(trip.date || localDate())}"></label>
            <label>Store<select name="store_key"><option value="">Choose later</option>${stores.map(store => `<option value="${escape(store.key)}" ${store.key === trip.store_key ? 'selected' : ''}>${escape(store.label)}</option>`).join('')}${storeMissing ? `<option value="${escape(trip.store_key)}" selected>${escape(trip.store_label || trip.store_key)} (unavailable)</option>` : ''}</select></label>
            <label>Shopping list<select name="list_id" required>${listMissing ? (s.trip?.list_id === listId ? `<option value="${escape(listId)}" selected>${escape(s.trip.list_name)} (unavailable)</option>` : '<option value="" selected>Choose an available list</option>') : ''}${lists.map(list => `<option value="${escape(list.id)}" ${list.id === listId ? 'selected' : ''}>${escape(list.name)}</option>`).join('')}</select></label>
            <label>Status<select name="status">${(s.options.statuses || []).map(status => `<option value="${escape(status.value)}" ${status.value === (trip.status || 'planned') ? 'selected' : ''}>${escape(status.label)}</option>`).join('')}</select></label>
            </div>
            <div data-trip-sources class="planner-trip-sources"></div>
            <div class="planner-trip-actions">${s.trip ? '<button type="button" data-trip-action="delete">Remove trip</button>' : ''}<button type="button" data-trip-action="cancel">Cancel</button><button type="submit" class="app-page-primary-action" data-trip-action="save">${s.trip ? 'Save changes' : 'Schedule trip'}</button></div></form>`);
        renderSources(s,trip.source_ids);
        query(s.dialog,'[data-trip-form]').onsubmit = event => {event.preventDefault(); void saveTrip(s);};
    }
    async function loadTrip(s) {
        s.controller?.abort(); const controller = s.controller = new AbortController();
        tripBusy(s,true); setStatus(s.dialog,'[data-trip-status]','Loading shopping details…');
        try {
            const [options,detail] = await Promise.all([
                s.initial.remove ? Promise.resolve(null) : request('/api/shopping-trips/options',undefined,'GET',controller.signal),
                s.initial.id ? request('/api/shopping-trips/'+encodeURIComponent(s.initial.id),undefined,'GET',controller.signal) : Promise.resolve(null),
            ]);
            if (controller.signal.aborted || tripState !== s) return;
            s.options = options; s.trip = detail?.trip || null;
            setStatus(s.dialog,'[data-trip-status]');
            if (s.initial.remove) confirmRemove(s); else renderTrip(s);
        } catch (error) {
            if (!controller.signal.aborted && tripState === s) {
                setStatus(s.dialog,'[data-trip-status]',error.message,true);
                tripContent(s,'<div class="planner-trip-actions"><button type="button" data-trip-action="cancel">Close</button><button type="button" data-trip-action="retry">Retry</button></div>');
            }
        } finally {
            if (!controller.signal.aborted && tripState === s) {
                tripBusy(s,false); query(s.dialog,'[data-trip-content]')?.querySelector('input,select,button')?.focus();
            }
        }
    }
    async function openTrip(initial = {},opener = document.activeElement) {
        const dialog = document.getElementById('shoppingTripDialog');
        if (!dialog || tripState?.saving) return false;
        tripState?.controller?.abort();
        const s = tripState = {dialog,initial,opener,busy:false,saving:false};
        query(dialog,'#shoppingTripDialogTitle').textContent = initial.remove ? 'Remove shopping trip' : initial.id ? 'Edit shopping trip' : 'Schedule shopping trip';
        tripContent(s,'');
        dialog.onclick = event => {
            const action = event.target.closest('[data-trip-action]')?.dataset.tripAction;
            if (!action || s.busy) return;
            if (action === 'cancel') closeTrip();
            if (action === 'retry') void loadTrip(s);
            if (action === 'save') {event.preventDefault(); void saveTrip(s);}
            if (action === 'delete') {s.draft = tripPayload(s); confirmRemove(s);}
            if (action === 'confirm-delete') void removeTrip(s);
            if (action === 'back') {
                if (s.initial.remove) closeTrip();
                else renderTrip(s);
            }
        };
        dialog.onchange = event => {
            if (event.target.matches('[name="list_id"]')) renderSources(s);
        };
        dialog.oncancel = event => {event.preventDefault(); closeTrip();};
        if (!dialog.open) dialog.showModal();
        await loadTrip(s);
        return false;
    }
    function confirmRemove(s) {
        s.mode = 'delete';
        setStatus(s.dialog,'[data-trip-status]');
        query(s.dialog,'#shoppingTripDialogTitle').textContent = 'Remove shopping trip';
        tripContent(s,`<p>Remove the trip for ${escape(s.trip.list_name)} on ${escape(s.trip.date)}?</p><p class="meal-shopping-help">The shopping list, meals, and prep batches will be kept.</p><div class="planner-trip-actions"><button type="button" data-trip-action="back">Cancel</button><button type="button" data-trip-action="confirm-delete">Remove trip</button></div>`);
    }
    function tripPayload(s) {
        const field = name => query(s.dialog,`[name="${name}"]`).value;
        return {date:field('date'),store_key:field('store_key'),list_id:field('list_id'),status:field('status'),
            source_ids:[...s.dialog.querySelectorAll('[data-trip-source]')].filter(input => input.checked).map(input => input.value)};
    }
    async function saveTrip(s) {
        if (s.busy || s.mode !== 'edit') return;
        const form = query(s.dialog,'[data-trip-form]');
        if (!form.reportValidity()) return;
        const payload = tripPayload(s);
        s.saving = true; tripBusy(s,true); setStatus(s.dialog,'[data-trip-status]','Saving shopping trip…');
        try {
            const data = await request('/api/shopping-trips'+(s.trip ? '/'+encodeURIComponent(s.trip.id) : ''),payload,s.trip ? 'PATCH' : 'POST');
            if (tripState !== s) return;
            s.saving = false; closeTrip();
            await showSavedTrip(data.trip.date);
        } catch (error) {if (tripState === s) setStatus(s.dialog,'[data-trip-status]',error.message,true);}
        finally {if (tripState === s) {s.saving = false; tripBusy(s,false);}}
    }
    async function showSavedTrip(date) {
        if (typeof global.openAppPage === 'function') await global.openAppPage('mealPlannerPage',{targetId:'mealPlannerPage'});
        page = document.getElementById('mealPlannerPage');
        if (!page) return;
        active = 'shopping'; syncNavigation(true);
        // The shared workspace refresh supplies the correct range and meal calendar.
        if (typeof global.refreshMealPlannerWorkspace === 'function') {
            const refreshed = await global.refreshMealPlannerWorkspace({date});
            setStatus(page,'[data-meal-planner-refresh-status]',refreshed ? `Shopping trip saved for ${date}.` : `Shopping trip saved for ${date}. Reopen the planner to refresh the calendar.`,!refreshed);
        } else {void refresh(); setStatus(page,'[data-meal-planner-refresh-status]',`Shopping trip saved for ${date}.`);}
    }
    async function removeTrip(s) {
        if (s.busy || s.mode !== 'delete') return;
        s.saving = true; tripBusy(s,true); setStatus(s.dialog,'[data-trip-status]','Removing shopping trip…');
        try {
            await request('/api/shopping-trips/'+encodeURIComponent(s.trip.id),undefined,'DELETE');
            if (tripState !== s) return;
            s.saving = false; closeTrip(); void refresh();
            setStatus(page,'[data-meal-planner-refresh-status]','Shopping trip removed.');
        } catch (error) {if (tripState === s) setStatus(s.dialog,'[data-trip-status]',error.message,true);}
        finally {if (tripState === s) {s.saving = false; tripBusy(s,false);}}
    }
    function closeTrip() {
        if (!tripState || tripState.saving) return false;
        const s = tripState; tripState = null; s.controller?.abort(); s.dialog.close(); s.opener?.focus({preventScroll:true});
        return false;
    }
    global.PlannerViews = {init,select,refresh,openTrip,closeTrip};
    document.addEventListener('pointerdown',event => closeCardMenus(event.target.closest('.planner-card-menu')));
    document.addEventListener('keydown',event => {if (event.key === 'Escape') closeCardMenus(null,true);});
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',() => init());
    else init();
})(window);
