/* Scheduling controls shared by recipe preview and the Meal Planner dialog. */
(function (root) {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const title = value => value[0].toUpperCase() + value.slice(1);
    const number = value => {
        const n = Number(value);
        if (!Number.isFinite(n)) return '—';
        const whole = Math.floor(n), fraction = Math.round((n - whole) * 10000) / 10000;
        const glyph = {0.25:'¼', 0.5:'½', 0.75:'¾'}[fraction];
        return glyph ? `${whole || ''}${glyph}` : String(Math.round(n * 1000000) / 1000000);
    };
    const dateLabel = date => root.MealPlanSchedule.parseDate(date)?.toLocaleDateString(undefined, {weekday:'short', month:'short', day:'numeric', year:'numeric'}) || date;

    class MealPlanPanel {
        constructor(form, options) {
            this.form = form;
            this.options = options;
            this.edit = null;
            this.generation = 0;
            this.ui = {openDays:new Set(), openSections:new Set(), names:{}, newName:'', groupIds:[], busy:false, memberBusy:false, loading:false, membersLoaded:false, refreshMemberDefaults:false, memberLoadError:false, archivedMembers:[], memberReview:[], message:'', error:false};
            this.draft = root.MealPlanSchedule.create({today:options.today, servings:options.servings, splitRecipeYield:options.splitRecipeYield, members:[]});
            this.form.classList.add('meal-schedule-panel');
            form.addEventListener('submit', event => this.submit(event));
            form.addEventListener('click', event => this.click(event));
            form.addEventListener('change', event => this.change(event));
            form.addEventListener('input', event => this.input(event));
            form.addEventListener('pointerdown', event => this.startCalendarDrag(event));
            form.addEventListener('pointermove', event => this.moveCalendarDrag(event));
            form.addEventListener('pointerup', event => {
                if (event.pointerId !== this.calendarDrag?.pointerId) return;
                this.moveCalendarDrag(event, true);
                this.endCalendarDrag();
            });
            ['pointercancel', 'lostpointercapture'].forEach(type => form.addEventListener(type, event => {
                if (event.pointerId === this.calendarDrag?.pointerId) this.endCalendarDrag();
            }));
            this.render();
        }

        async open() {
            this.ui.saved = false;
            this.form.hidden = false;
            this.form.scrollIntoView({block:'start'});
            this.form.querySelector(this.edit?.scope === 'meal' ? '[data-schedule-field="single-date"]' : '[data-schedule-mode][aria-pressed="true"]')?.focus({preventScroll:true});
            await this.loadMembers();
        }

        clearEdit() {
            this.generation += 1;
            this.edit = null;
            this.draft = root.MealPlanSchedule.create({today:this.options.today,servings:this.options.servings,splitRecipeYield:this.options.splitRecipeYield,members:this.draft.members,groups:this.draft.groups});
            Object.assign(this.ui, {busy:false,loading:false,saved:false,membersLoaded:false,refreshMemberDefaults:true,memberReview:[],groupIds:[],names:{},newName:'',message:'',error:false});
            this.ui.openDays.clear();
            this.ui.openSections.clear();
            this.render();
        }

        loadEdit(data, scope = 'meal') {
            const draft = root.MealPlanSchedule.fromSaved(data, scope, {members:this.draft.members, groups:this.draft.groups});
            const source = scope === 'meal' ? data.meal : data.batch;
            const meals = data.meals || data.batch?.allocations || [];
            this.generation += 1;
            this.edit = {scope, id:source.id, recipe_url:source.recipe_url, title:source.recipe_name,
                spareServings:scope === 'batch' ? Math.max(0, Number(source.batch_servings || 0) - meals.reduce((total,meal) => total + Number(meal.planned_servings || 0),0)) : 0};
            this.draft = draft;
            Object.assign(this.ui, {busy:false,loading:false,saved:false,membersLoaded:true,refreshMemberDefaults:false,memberReview:[],groupIds:[],names:{},newName:'',message:'',error:false});
            this.ui.openDays.clear();
            this.ui.openSections.clear();
            this.render();
            return this;
        }

        async loadMembers() {
            if (this.options.loadMembers) return this.options.loadMembers();
            // List refreshes and member mutations must not overwrite one another.
            if (this.ui.loading || this.ui.busy || this.ui.memberBusy) return;
            const generation = this.generation;
            this.ui.loading = true;
            this.render();
            try {
                const response = await fetch('/api/meal-plan/members');
                const data = await response.json();
                if (generation !== this.generation) return;
                if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to load family members.');
                if (!Array.isArray(data.members)) throw new Error('Unable to load family members.');
                if (data.groups !== undefined && !Array.isArray(data.groups)) throw new Error('Unable to load family groups.');
                if (data.archived_members !== undefined && !Array.isArray(data.archived_members)) throw new Error('Unable to load archived people.');
                // A member added elsewhere becomes an available choice without
                // silently increasing portions in an already configured draft.
                this.syncMembers(data.members, {newMembersEnabled:!this.ui.membersLoaded, refreshDefaults:this.ui.refreshMemberDefaults});
                root.MealPlanSchedule.setGroups(this.draft, data.groups || []);
                this.ui.archivedMembers = (data.archived_members || []).filter(member => member && member.id && typeof member.name === 'string');
                this.ui.groupIds = this.ui.groupIds.filter(id => this.draft.groups.some(group => group.id === id));
                this.ui.membersLoaded = true;
                this.ui.refreshMemberDefaults = false;
                this.ui.memberLoadError = false;
                this.ui.message = '';
                this.ui.error = false;
            } catch (error) { if (generation === this.generation) { this.ui.memberLoadError = true; this.setMessage(`${error.message} You can retry or use household totals.`, true); } }
            finally { if (generation === this.generation) { this.ui.loading = false; this.render(); } }
        }

        setMessage(message, error = false) { this.ui.message = message; this.ui.error = error; }

        schedulingDraft() { return this.options.getDraft?.(this.draft) || this.draft; }

        syncMembers(members, options) {
            const previousMembers = this.draft.members;
            root.MealPlanSchedule.setMembers(this.draft, members, options);
            const removed = previousMembers.filter(member => !this.draft.members.some(active => active.id === member.id));
            if (removed.length) {
                this.ui.memberReview = [...new Set([...this.ui.memberReview, ...removed.map(member => member.name)])];
                this.ui.openSections.add('members');
                removed.forEach(member => { delete this.ui.names[member.id]; });
            }
        }

        captureOpen() {
            this.form.querySelectorAll('details[data-schedule-day]').forEach(item => {
                this.ui.openDays[item.open ? 'add' : 'delete'](item.dataset.scheduleDay);
            });
            this.form.querySelectorAll('details[data-schedule-section]').forEach(item => {
                this.ui.openSections[item.open ? 'add' : 'delete'](item.dataset.scheduleSection);
            });
        }

        render() {
            if (this.calendarDrag && !this.calendarDragIsCurrent()) this.endCalendarDrag();
            this.captureOpen();
            const active = this.form.contains(document.activeElement) ? document.activeElement : null;
            const key = active?.dataset.focusKey;
            const position = active && ['text','search'].includes(active.type) ? active.selectionStart : null;
            this.form.innerHTML = MealPlanPanel.html(this.schedulingDraft(), this.ui, this.edit?.title || this.options.title, this.options);
            const footer = this.form.querySelector('.meal-schedule-footer');
            if (footer) footer.hidden = Boolean(this.options.onSubmit && !this.edit);
            if (key) {
                const replacement = [...this.form.querySelectorAll('[data-focus-key]')].find(node => node.dataset.focusKey === key);
                replacement?.focus({preventScroll:true});
            if (position !== null && replacement?.setSelectionRange) replacement.setSelectionRange(position, position);
            }
            this.options.onRender?.(this);
        }

        static check(meal, enabled, action, extra = '') {
            return `<label class="meal-schedule-check"><input type="checkbox" data-schedule-field="${action}" data-meal="${meal}" ${extra} ${enabled ? 'checked' : ''}><span>${title(meal)}</span></label>`;
        }

        static portion(value, {field, meal, member = '', date = '', enabled = true, checkbox = false, name = '', blocked = false}) {
            const key = [field,date,member,meal].join('|');
            const attrs = `data-meal="${meal}" data-member="${esc(member)}" data-date="${date}"`;
            const label = `${name ? name + ', ' : ''}${title(meal)} servings${date ? ', ' + dateLabel(date) : ''}`;
            enabled = enabled && !blocked;
            return `<div class="meal-schedule-portion">${checkbox ? `<input type="checkbox" data-schedule-field="${field}-enabled" ${attrs} data-focus-key="${esc(key)}-enabled" aria-label="Include ${esc(label)}" ${enabled ? 'checked' : ''} ${blocked ? 'disabled' : ''}>` : ''}
                <div class="meal-schedule-stepper"><button type="button" data-schedule-action="step" data-direction="-1" data-focus-key="${esc(key)}-less" ${enabled ? '' : 'disabled'} aria-label="Decrease ${esc(label)}">−</button>
                <input type="number" min="0" step="any" inputmode="decimal" data-schedule-field="${field}" ${attrs} data-focus-key="${esc(key)}" aria-label="${esc(label)}" value="${esc(value)}" ${enabled ? 'required' : 'disabled'}>
                <button type="button" data-schedule-action="step" data-direction="1" data-focus-key="${esc(key)}-more" ${enabled ? '' : 'disabled'} aria-label="Increase ${esc(label)}">+</button></div></div>`;
        }

        static portionsTable(draft, meals, date) {
            if (!meals.length) return '<p>Select at least one meal.</p>';
            if (draft.portionMode === 'recipe') return '<p>Servings are divided evenly across the scheduled meals. Choose Household total to adjust portions.</p>';
            if (draft.portionMode === 'household') return `<div class="meal-schedule-household">${meals.map(meal => `<label>${title(meal)} servings${MealPlanPanel.portion(date ? draft.days[date].household[meal] : draft.householdDefaults[meal], {field:date ? 'day-household' : 'household', meal, date})}</label>`).join('')}</div>`;
            if (!draft.members.length) return '<p>No active people are available for this meal.</p>';
            const portions = date ? draft.days[date].family : draft.familyDefaults;
            return `<div class="meal-schedule-table-scroll" tabindex="0" role="region" aria-label="${date ? esc(dateLabel(date)) : 'Default'} family portions"><table class="meal-schedule-table"><thead><tr><th scope="col">Family member</th>${meals.map(meal => `<th scope="col">${title(meal)}</th>`).join('')}</tr></thead><tbody>${draft.members.map(member => `<tr><th scope="row">${esc(member.name)}${member.archived ? ' (Archived)' : ''}</th>${meals.map(meal => {
                const cell = portions[member.id]?.[meal] || {enabled:false, servings:1};
                return `<td>${MealPlanPanel.portion(cell.servings, {field:date ? 'day-family' : 'family', meal, member:member.id, date, enabled:cell.enabled, checkbox:true, name:member.name, blocked:!root.MealPlanSchedule.canAssignMember(draft, member, date, meal)})}</td>`;
            }).join('')}</tr>`).join('')}</tbody><tfoot><tr><th scope="row">${date ? 'Meal totals' : 'Per day'}</th>${meals.map(meal => {
                const total = draft.members.reduce((sum, member) => {
                    const cell = portions[member.id]?.[meal], value = Number(cell?.servings);
                    return sum + (cell?.enabled && Number.isFinite(value) && value > 0 ? value : 0);
                }, 0);
                return `<td data-portion-total="${meal}" data-date="${date || ''}">${number(total)} servings</td>`;
            }).join('')}</tr></tfoot></table></div>`;
        }

        static groupChooser(draft, ui, manageMembersUrl) {
            if (draft.portionMode !== 'family' || !draft.groups.length) return '';
            const groupMembers = group => draft.members.filter(member => !member.archived && member.group_ids.includes(group.id));
            const hasPeople = draft.groups.some(group => ui.groupIds.includes(group.id) && groupMembers(group).length);
            return `<details class="meal-schedule-groups" data-schedule-section="groups" ${ui.openSections.has('groups') ? 'open' : ''}><summary>Select a family or group</summary>
                <div class="meal-schedule-group-choices">${draft.groups.map(group => {
                    const people = groupMembers(group);
                    return `<label class="meal-schedule-check"><input type="checkbox" data-schedule-field="group" data-group="${esc(group.id)}" data-focus-key="group-${esc(group.id)}" ${ui.groupIds.includes(group.id) ? 'checked' : ''} ${ui.loading || !people.length ? 'disabled' : ''}><span>${esc(group.name)} (${people.length})${people.length ? '' : ' — no active people assigned'}</span></label>`;
                }).join('')}</div>
                <button type="button" data-schedule-action="select-group-members" data-focus-key="select-group-members" aria-label="Select everyone in selected groups" ${!hasPeople || ui.loading || !ui.membersLoaded ? 'disabled' : ''}>Select everyone</button>
                <p>Selects these groups in the people list above. Each person is counted once.</p>
                ${draft.groups.some(group => !groupMembers(group).length) ? `<p>Assign people to empty groups in <a href="${esc(manageMembersUrl)}" target="_blank" rel="noopener">Family Members</a>.</p>` : ''}
            </details>`;
        }

        static recipeYieldHelp(draft, options) {
            return options.sharedPlan ? 'Repeated entries of the same recipe share one yield across all their meals. Custom portions are taken out first.'
                : `This entry uses ${number(root.MealPlanSchedule.summary(draft).totalServings)} of the recipe’s ${number(draft.recipeYield)} servings. Repeated entries share the same yield.`;
        }

        static peopleSection(draft, ui, manageMembersUrl, options = {}) {
            if (draft.portionMode === 'recipe') return `<h3>Split recipe yield</h3><p data-recipe-yield-help>${MealPlanPanel.recipeYieldHelp(draft, options)}</p><p>Changing dates or meal types recalculates the servings per meal.</p>`;
            if (draft.portionMode !== 'family') return `<h3>Servings per meal</h3>${MealPlanPanel.portionsTable(draft, draft.mealTypes)}`;
            const archivedUrl = typeof root.withCanonicalViewerUserId === 'function'
                ? root.withCanonicalViewerUserId('/settings/family-members?status=archived') : '/settings/family-members?status=archived';
            const archived = ui.archivedMembers || [];
            let body = '';
            if (draft.members.length) {
                body = `${ui.loading ? '<p role="status">Refreshing saved people…</p>' : ''}${ui.memberLoadError ? '<p role="alert">Could not refresh people. The previously loaded people are still shown.</p>' : ''}
                    ${MealPlanPanel.portionsTable(draft, draft.mealTypes)}<p>Set each person’s servings. Uncheck anyone who isn’t eating.</p>`;
            } else if (ui.loading || (!ui.membersLoaded && !ui.memberLoadError)) {
                body = '<p role="status">Loading saved people…</p>';
            } else if (ui.memberLoadError) {
                body = '<p role="alert">Your people could not be loaded. Retry before adding them again.</p>';
            } else {
                body = `<div class="meal-schedule-people-empty"><p>No active people are saved in this workspace.</p>${archived.length
                    ? `<p>Archived: ${esc(archived.map(member => member.name).join(', '))}. <a href="${esc(archivedUrl)}" target="_blank" rel="noopener">View archived people</a> to restore them.</p>`
                    : `<p><a href="${esc(manageMembersUrl)}" target="_blank" rel="noopener">Manage Family Members</a> to add people.</p>`}</div>`;
            }
            return `<section class="meal-schedule-people" aria-label="People and portions"><div class="meal-schedule-people-heading"><h3>People &amp; portions${draft.members.length ? ` (${draft.members.length})` : ''}</h3>
                <button type="button" data-schedule-action="retry-members" data-focus-key="refresh-members" ${ui.loading ? 'disabled' : ''}>${ui.membersLoaded ? 'Refresh members' : 'Retry loading members'}</button></div>${body}
                ${MealPlanPanel.groupChooser(draft, ui, manageMembersUrl)}</section>`;
        }

        static portionModes(draft) {
            const modes = [...(!draft.edit && draft.recipeYield !== undefined ? [['recipe','Split recipe yield']] : []), ['household','Household total'], ['family','By family member']];
            return `<h3>Who is eating?</h3><div class="recipe-preview-segment meal-schedule-modes" role="group" aria-label="Portion allocation">${modes.map(([mode,label]) => `<button type="button" data-schedule-portion-mode="${mode}" data-focus-key="portion-mode-${mode}" aria-pressed="${draft.portionMode === mode}">${label}</button>`).join('')}</div>`;
        }

        static memberReviewHtml(ui) {
            return ui.memberReview.length ? `<p role="alert">No longer active: ${esc(ui.memberReview.join(', '))}. Their portions were removed from this draft. Review the updated family portions and totals before saving.</p><button type="button" data-schedule-action="review-members">Use updated family list</button>` : '';
        }

        static html(draft, ui, recipeTitle = '', options = {}) {
            const model = root.MealPlanSchedule, totals = model.summary(draft);
            const sharedSplit = options.sharedPlan && draft.portionMode === 'recipe';
            const singleEdit = draft.edit?.scope === 'meal';
            const disabled = ui.busy || ui.memberBusy || ui.saved;
            const reviewRequired = draft.portionMode === 'family' && ui.memberReview.length > 0;
            const manageMembersUrl = typeof root.withCanonicalViewerUserId === 'function'
                ? root.withCanonicalViewerUserId('/settings/family-members') : '/settings/family-members';
            if (options.portionsOnly) return `<fieldset ${disabled ? 'disabled' : ''}>
                <p>People and portions for this recipe. Dates, meal types, notes, and prep tasks follow the shared plan.</p>
                ${MealPlanPanel.portionModes(draft)}${MealPlanPanel.peopleSection(draft, ui, manageMembersUrl, options)}
                <div class="meal-schedule-summary" data-schedule-summary aria-live="polite">${MealPlanPanel.summaryHtml(draft, totals, options)}</div>
                ${MealPlanPanel.memberReviewHtml(ui)}
                <p class="meal-schedule-errors" data-schedule-errors role="status">${esc(MealPlanPanel.validationMessage(draft, ui, totals))}</p></fieldset>
                <p class="recipe-preview-status ${ui.error ? 'is-error' : ''}" data-schedule-status role="${ui.error ? 'alert' : 'status'}">${esc(ui.message)}</p>`;
            const dateModes = [['single','One day'],['range','Date range'],['days','Select days']];
            let dates = draft.dateMode === 'single'
                ? `<label>Date<input type="date" data-schedule-field="single-date" data-focus-key="single-date" value="${esc(draft.singleDate)}" required></label>`
                : draft.dateMode === 'range' ? `<div class="meal-schedule-date-range"><label>Start date<input type="date" data-schedule-field="start-date" data-focus-key="start-date" value="${esc(draft.startDate)}" required></label><label>End date<input type="date" data-schedule-field="end-date" data-focus-key="end-date" value="${esc(draft.endDate)}" required></label></div>` : '';
            if (draft.dateMode === 'days') {
                const calendar = model.calendarMonth(draft.calendarMonth);
                dates = `<div class="meal-schedule-calendar"><div class="meal-schedule-calendar-heading"><button type="button" data-schedule-action="month" data-direction="-1" data-focus-key="previous-month" aria-label="Previous month">‹</button><strong>${esc(calendar.label)}</strong><button type="button" data-schedule-action="month" data-direction="1" data-focus-key="next-month" aria-label="Next month">›</button></div>
                    <div class="meal-schedule-calendar-grid">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(day => `<span aria-hidden="true">${day}</span>`).join('')}${calendar.days.map(day => `<button type="button" data-schedule-action="date" data-date="${day.date}" data-focus-key="calendar-${day.date}" aria-label="${esc(dateLabel(day.date))}" aria-pressed="${draft.selectedDates.includes(day.date)}" class="${day.inMonth ? '' : 'is-other-month'}">${day.day}</button>`).join('')}</div>
                    <p>Drag to select a range, or clear it if all its dates are already selected. Click to toggle one date.</p></div>`;
            }
            const dayCards = totals.days.map(day => {
                const data = draft.days[day.date], meals = model.MEAL_TYPES.filter(meal => data.mealEnabled[meal]);
                return `<details class="meal-schedule-day" data-schedule-day="${day.date}" ${ui.openDays.has(day.date) ? 'open' : ''}><summary><span><strong>${esc(dateLabel(day.date))}</strong><small data-day-summary="${day.date}">${day.meals.map(meal => sharedSplit ? title(meal.meal_type) : `${title(meal.meal_type)}: ${number(meal.planned_servings)}`).join(' · ') || 'No meals selected'}</small></span><span data-day-total="${day.date}">${sharedSplit ? 'Split per recipe' : `${number(day.totalServings)} servings`}</span></summary>
                    <div class="meal-schedule-day-body"><div class="meal-schedule-meals">${model.MEAL_TYPES.map(meal => MealPlanPanel.check(meal, data.mealEnabled[meal], 'day-meal', `data-date="${day.date}" data-focus-key="day-meal-${day.date}-${meal}"`)).join('')}</div>
                    ${draft.edit ? meals.map(meal => `${MealPlanPanel.portionsTable({...draft,portionMode:model.mealPortionMode(draft,day.date,meal)}, [meal], day.date)}<label>${title(meal)} notes (optional)<input type="text" data-schedule-field="meal-notes" data-meal="${meal}" data-date="${day.date}" data-focus-key="meal-notes-${day.date}-${meal}" value="${esc(data.mealNotes[meal] ?? data.notes)}"></label>`).join('') : `${MealPlanPanel.portionsTable(draft, meals, day.date)}<label>Notes for this day (optional)<input type="text" data-schedule-field="day-notes" data-date="${day.date}" data-focus-key="day-notes-${day.date}" value="${esc(data.notes)}"></label>`}
                    <p data-day-default-status="${day.date}">${day.customized ? 'Adjusted for this day.' : 'Using default portions.'}</p></div></details>`;
            }).join('');
            return `<div class="meal-schedule-heading"><div><h2>${singleEdit ? 'Edit scheduled meal' : draft.edit ? 'Edit prep plan' : 'Add to Meal Plan'}</h2><p>${esc(recipeTitle)}</p></div><button type="button" data-schedule-action="cancel" aria-label="Close meal planning" ${ui.busy || ui.memberBusy ? 'disabled' : ''}>×</button></div>
                <fieldset ${disabled ? 'disabled' : ''}>${singleEdit ? '<p>Changes apply only to this scheduled meal.</p>' : `<div class="recipe-preview-segment meal-schedule-modes" role="group" aria-label="Date selection">${dateModes.map(([mode,label]) => `<button type="button" data-schedule-mode="${mode}" data-focus-key="mode-${mode}" aria-pressed="${draft.dateMode === mode}">${label}</button>`).join('')}</div>`}
                <div class="meal-schedule-dates">${dates}</div>
                <div class="meal-schedule-meals">${singleEdit ? `<label>Meal<select data-schedule-field="single-meal" data-focus-key="single-meal">${model.MEAL_TYPES.map(meal => `<option value="${meal}" ${draft.mealTypes[0] === meal ? 'selected' : ''}>${title(meal)}</option>`).join('')}</select></label>` : `<strong>Meals on selected days</strong>${model.MEAL_TYPES.map(meal => MealPlanPanel.check(meal, draft.mealTypes.includes(meal), 'meal', `data-focus-key="meal-${meal}"`)).join('')}`}</div>
                <div class="meal-schedule-columns"><section>${MealPlanPanel.portionModes(draft)}
                ${MealPlanPanel.peopleSection(draft, ui, manageMembersUrl, options)}
                <div data-schedule-apply ${totals.days.some(day => day.customized) ? '' : 'hidden'}><p class="meal-schedule-apply-help">Some days have individual changes. Apply these portions to replace those changes.</p><button type="button" data-schedule-action="apply" data-focus-key="apply">Apply to selected days</button></div>
                <details class="meal-schedule-members" data-schedule-section="members" ${ui.openSections.has('members') ? 'open' : ''}><summary>Add or edit people</summary>
                    <p><a href="${esc(manageMembersUrl)}" target="_blank" rel="noopener">Manage Family Members</a> (opens in a new tab). Refresh members here after making changes.</p>
                    ${draft.portionMode !== 'family' ? `<button type="button" data-schedule-action="retry-members" data-focus-key="refresh-members" ${ui.loading ? 'disabled' : ''}>${ui.membersLoaded ? 'Refresh members' : 'Retry loading members'}</button>` : ''}
                    ${draft.members.filter(member => !member.archived).map(member => `<div class="meal-schedule-member-row"><label>Name<input type="text" maxlength="100" data-member-name="${esc(member.id)}" data-focus-key="member-${esc(member.id)}" value="${esc(ui.names[member.id] ?? member.name)}"></label><button type="button" data-schedule-action="save-member" data-member="${esc(member.id)}" ${ui.loading ? 'disabled' : ''}>Save name</button></div>`).join('')}
                    <div class="meal-schedule-member-row"><label>New family member<input type="text" maxlength="100" data-new-member data-focus-key="new-member" value="${esc(ui.newName)}" placeholder="Name"></label><button type="button" data-schedule-action="add-member" ${!ui.membersLoaded || ui.loading ? 'disabled' : ''}>Add member</button></div>
                </details><details class="meal-schedule-notes" data-schedule-section="notes" ${ui.openSections.has('notes') || draft.notes ? 'open' : ''}><summary>${singleEdit ? 'Notes for this meal' : 'Meal-prep notes'} (optional)</summary><label><span class="sr-only">Meal-prep notes</span><textarea rows="2" data-schedule-field="notes" data-focus-key="notes" placeholder="${singleEdit ? 'Notes for this scheduled meal' : 'Notes shared by this meal plan'}">${esc(draft.notes)}</textarea></label></details></section>
                ${singleEdit ? '' : `<section><h3>Scheduled meals</h3><p>Expand a day to adjust meals, people, and portions.</p><div class="meal-schedule-days">${dayCards || '<p>Select dates to build your schedule.</p>'}</div>
                <details class="meal-schedule-prep" data-schedule-section="prep" ${ui.openSections.has('prep') ? 'open' : ''}><summary>Prep tasks (optional)</summary><p>Schedule preparation on its own dates.</p>${draft.prepSteps.map((step,index) => `<div class="meal-schedule-prep-row"><label>Prep date<input type="date" data-schedule-field="prep-date" data-step="${index}" data-focus-key="prep-date-${index}" value="${esc(step.date)}" required></label><label>Task<input type="text" maxlength="2000" data-schedule-field="prep-instruction" data-step="${index}" data-focus-key="prep-instruction-${index}" value="${esc(step.instruction)}" placeholder="e.g. Chop vegetables" required></label><button type="button" data-schedule-action="remove-prep" data-step="${index}" aria-label="Remove prep task ${index+1}">Remove</button></div>`).join('')}<button type="button" data-schedule-action="add-prep">Add prep task</button></details></section>`}</div>
                <div class="meal-schedule-summary" data-schedule-summary aria-live="polite">${MealPlanPanel.summaryHtml(draft, totals, options)}</div>
                ${MealPlanPanel.memberReviewHtml(ui)}
                <p class="meal-schedule-errors" data-schedule-errors role="status">${esc(MealPlanPanel.validationMessage(draft, ui, totals))}</p>
                <div class="meal-schedule-footer"><button type="button" data-schedule-action="cancel">Cancel</button><button type="submit" class="is-primary" data-schedule-submit ${!totals.valid || ui.loading || reviewRequired || ui.saved ? 'disabled' : ''}>${ui.busy ? 'Saving…' : draft.edit ? 'Save changes' : `Add ${totals.mealCount} ${totals.mealCount === 1 ? 'meal' : 'meals'}`}</button></div></fieldset>
                <p class="recipe-preview-status ${ui.error ? 'is-error' : ''}" data-schedule-status role="${ui.error ? 'alert' : 'status'}">${esc(ui.message)}</p>`;
        }

        static summaryHtml(draft, totals, options = {}) {
            const sharedSplit = options.sharedPlan && draft.portionMode === 'recipe';
            const detail = sharedSplit ? 'Each recipe’s yield is shared across its entries.'
                : draft.edit?.scope === 'meal' ? 'Only this meal will change.'
                : options.sharedPlan && !draft.edit ? 'Meal totals are divided between recipes. Custom recipes use their share first.'
                : 'Prepare one batch for these meals.';
            return `<div><strong>${totals.dayCount} ${totals.dayCount === 1 ? 'day' : 'days'} · ${totals.mealCount} ${totals.mealCount === 1 ? 'meal' : 'meals'}${sharedSplit ? ' per entry' : ` · ${number(totals.totalServings)} servings`}</strong><span>${detail}</span></div>${draft.portionMode === 'family' ? `<p>${draft.members.filter(member => totals.memberTotals[member.id]).map(member => `${esc(member.name)}: ${number(totals.memberTotals[member.id])} servings`).join(' · ')}</p>` : ''}`;
        }

        static validationMessage(draft, ui, totals) {
            return totals.errors.map(error => {
                if (error !== 'Add at least one family member.') return error;
                if (ui.loading || (!ui.membersLoaded && !ui.memberLoadError)) return 'Waiting for saved people to load.';
                if (ui.memberLoadError) return 'Retry loading your saved people.';
                return ui.archivedMembers?.length ? 'Restore an archived person or add someone to continue.' : 'Add a person in Family Members to continue.';
            }).join(' ');
        }

        updateTotals(notify = true) {
            const draft = this.schedulingDraft(), totals = root.MealPlanSchedule.summary(draft);
            const sharedSplit = this.options.sharedPlan && draft.portionMode === 'recipe';
            this.form.querySelector('[data-schedule-summary]').innerHTML = MealPlanPanel.summaryHtml(draft, totals, this.options);
            this.form.querySelector('[data-schedule-errors]').textContent = MealPlanPanel.validationMessage(draft, this.ui, totals);
            const yieldHelp = this.form.querySelector('[data-recipe-yield-help]');
            if (yieldHelp && draft.portionMode === 'recipe') yieldHelp.textContent = MealPlanPanel.recipeYieldHelp(draft, this.options);
            const apply = this.form.querySelector('[data-schedule-apply]');
            if (apply) apply.hidden = !totals.days.some(day => day.customized);
            const button = this.form.querySelector('[data-schedule-submit]');
            if (button) {
                button.disabled = !totals.valid || this.ui.busy || this.ui.loading || this.ui.saved || (this.draft.portionMode === 'family' && this.ui.memberReview.length > 0);
                button.textContent = this.edit ? 'Save changes' : `Add ${totals.mealCount} ${totals.mealCount === 1 ? 'meal' : 'meals'}`;
            }
            totals.days.forEach(day => {
                const total = this.form.querySelector(`[data-day-total="${day.date}"]`);
                if (total) total.textContent = sharedSplit ? 'Split per recipe' : `${number(day.totalServings)} servings`;
                const summary = this.form.querySelector(`[data-day-summary="${day.date}"]`);
                if (summary) summary.textContent = day.meals.map(meal => sharedSplit ? title(meal.meal_type) : `${title(meal.meal_type)}: ${number(meal.planned_servings)}`).join(' · ') || 'No meals selected';
                const label = this.form.querySelector(`[data-day-default-status="${day.date}"]`);
                if (label) label.textContent = day.customized ? 'Adjusted for this day.' : 'Using default portions.';
            });
            this.form.querySelectorAll('[data-portion-total]').forEach(cell => {
                const portions = cell.dataset.date ? this.draft.days[cell.dataset.date].family : this.draft.familyDefaults;
                const total = this.draft.members.reduce((sum, member) => {
                    const part = portions[member.id]?.[cell.dataset.portionTotal], value = Number(part?.servings);
                    return sum + (part?.enabled && Number.isFinite(value) && value > 0 ? value : 0);
                }, 0);
                cell.textContent = `${number(total)} servings`;
            });
            if (notify) this.options.onRender?.(this);
        }

        syncPortionControls(active) {
            this.form.querySelectorAll('input[type="number"][data-schedule-field]').forEach(input => {
                if (input === active) return;
                const {scheduleField:field, date, member, meal} = input.dataset;
                let value;
                if (field === 'household') value = this.draft.householdDefaults[meal];
                if (field === 'family') value = this.draft.familyDefaults[member]?.[meal]?.servings;
                if (field === 'day-household') value = this.draft.days[date].household[meal];
                if (field === 'day-family') value = this.draft.days[date].family[member]?.[meal]?.servings;
                if (value !== undefined) input.value = value;
            });
        }

        updateField(input) {
            const model = root.MealPlanSchedule, draft = this.draft;
            const {scheduleField:field, meal, member, date, step} = input.dataset;
            const value = input.value;
            if (field === 'household') model.setHouseholdDefault(draft, meal, value);
            if (field === 'family' || field === 'family-enabled') {
                const current = draft.familyDefaults[member][meal];
                model.setFamilyDefault(draft, member, meal, {...current, ...(field.endsWith('enabled') ? {enabled:input.checked} : {servings:value})});
            }
            if (field === 'day-household') model.setDayHousehold(draft, date, meal, value);
            if (field === 'day-family' || field === 'day-family-enabled') {
                const current = draft.days[date].family[member][meal];
                model.setDayFamily(draft, date, member, meal, {...current, ...(field.endsWith('enabled') ? {enabled:input.checked} : {servings:value})});
            }
            if (field === 'notes') draft.notes = value;
            if (field === 'day-notes') model.setDayNotes(draft, date, value);
            if (field === 'meal-notes') model.setMealNotes(draft, date, meal, value);
            if (field === 'prep-date') draft.prepSteps[step].date = value;
            if (field === 'prep-instruction') draft.prepSteps[step].instruction = value;
        }

        input(event) {
            const input = event.target;
            if (this.ui.busy || this.ui.memberBusy || this.ui.saved) return;
            if (input.hasAttribute('data-member-name')) this.ui.names[input.dataset.memberName] = input.value;
            if (input.hasAttribute('data-new-member')) this.ui.newName = input.value;
            if (input.dataset.scheduleField && !['single-date','single-meal','start-date','end-date','meal','day-meal'].includes(input.dataset.scheduleField) && input.type !== 'checkbox') {
                this.updateField(input);
                this.updateTotals();
                this.syncPortionControls(input);
            }
        }

        change(event) {
            const input = event.target, model = root.MealPlanSchedule, draft = this.draft;
            if (this.ui.busy || this.ui.memberBusy || this.ui.saved || !input.dataset.scheduleField) return;
            const field = input.dataset.scheduleField;
            if (this.edit?.scope === 'meal' && ['start-date','end-date','meal','day-meal','prep-date','prep-instruction'].includes(field)) return;
            if (field === 'single-date') model.setSingleDate(draft, input.value);
            else if (field === 'single-meal' && this.edit?.scope === 'meal') model.setMeals(draft, [input.value]);
            else if (field === 'start-date') model.setRange(draft, input.value, draft.endDate);
            else if (field === 'end-date') model.setRange(draft, draft.startDate, input.value);
            else if (field === 'meal') model.setMeals(draft, [...this.form.querySelectorAll('[data-schedule-field="meal"]:checked')].map(node => node.dataset.meal));
            else if (field === 'day-meal') model.setDayMeal(draft, input.dataset.date, input.dataset.meal, input.checked);
            else if (field === 'group') {
                if (this.ui.loading || !draft.groups.some(group => group.id === input.dataset.group)) return;
                this.ui.groupIds = input.checked ? [...new Set([...this.ui.groupIds, input.dataset.group])] : this.ui.groupIds.filter(id => id !== input.dataset.group);
            }
            else this.updateField(input);
            // Keep typed inputs mounted on blur: replacing them here can swallow
            // a click on the adjacent stepper or submit button.
            if (['household','family','day-household','day-family','notes','day-notes','meal-notes','prep-instruction'].includes(field)) {
                this.updateTotals();
                this.syncPortionControls(input);
                return;
            }
            this.render();
        }

        calendarDragIsCurrent() {
            const drag = this.calendarDrag;
            return drag && drag.draft === this.draft && drag.generation === this.generation
                && this.draft.dateMode === 'days' && this.edit?.scope !== 'meal'
                && !this.form.hidden && !this.ui.busy && !this.ui.memberBusy && !this.ui.saved;
        }

        startCalendarDrag(event) {
            this.calendarClickPointer = null;
            const button = event.target.closest('[data-schedule-action="date"]');
            // Touch retains native scrolling and tap selection; only a primary
            // mouse press starts a range. Capture the form, which survives render().
            if (event.pointerType !== 'mouse' || event.button !== 0 || event.isPrimary === false
                || !button || button.disabled || !this.form.contains(button)
                || this.draft.dateMode !== 'days' || this.edit?.scope === 'meal'
                || this.form.hidden || this.ui.busy || this.ui.memberBusy || this.ui.saved) return;
            this.endCalendarDrag();
            this.calendarDrag = {pointerId:event.pointerId, anchor:button.dataset.date,
                before:[...this.draft.selectedDays],
                draft:this.draft, generation:this.generation};
            this.calendarClickPointer = event.pointerId;
            event.preventDefault();
            button.focus({preventScroll:true});
            this.form.setPointerCapture(event.pointerId);
            // Wait for another date or release before changing the selection.
            // A selected anchor must stay selected when extending a range.
        }

        moveCalendarDrag(event, releasing = false) {
            if (event.pointerId !== this.calendarDrag?.pointerId) return;
            if (!this.calendarDragIsCurrent() || (!releasing && !(event.buttons & 1))) {
                this.endCalendarDrag();
                return;
            }
            // Captured events target the form. Hit-test only this editor's dates
            // so dragging outside it cannot change a neighboring meal's calendar.
            const button = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-schedule-action="date"]');
            if (!button || !this.form.contains(button) || button.disabled) return;
            const date = button.dataset.date, drag = this.calendarDrag;
            if (date !== drag.anchor || drag.lastDate) this.selectCalendarDragDate(date);
            else if (releasing) this.selectCalendarDragDate(date, true);
        }

        selectCalendarDragDate(date, toggle = false) {
            const drag = this.calendarDrag;
            if (!drag || drag.lastDate === date) return;
            drag.lastDate = date;
            const dates = new Set(drag.before);
            const [start, end] = [drag.anchor, date].sort();
            const range = root.MealPlanSchedule.dateRange(start, end);
            // Evaluate against the original selection so previewed changes never
            // flip the operation. Mixed ranges extend; fully selected ranges clear.
            // Returning a drag to its anchor preserves it; only a click toggles it.
            const clearing = (toggle || date !== drag.anchor) && range.every(day => dates.has(day));
            range.forEach(day => {
                if (clearing) dates.delete(day);
                else dates.add(day);
            });
            root.MealPlanSchedule.setDates(this.draft, [...dates]);
            this.render();
            // Notify the containing editor even when capture consumes the click
            // (a changed recipe-less form must no longer count as an empty draft).
            this.form.dispatchEvent(new Event('change', {bubbles:true}));
        }

        endCalendarDrag() {
            const drag = this.calendarDrag;
            this.calendarDrag = null;
            if (drag && this.form.hasPointerCapture(drag.pointerId)) this.form.releasePointerCapture(drag.pointerId);
        }

        async click(event) {
            if (event.detail > 0 && event.pointerId === this.calendarClickPointer) {
                this.calendarClickPointer = null;
                event.preventDefault();
                return; // Pointer selection already handled this click exactly once.
            }
            const button = event.target.closest('button');
            if (!button || button.disabled || this.ui.busy || this.ui.memberBusy) return;
            if (this.ui.saved && button.dataset.scheduleAction !== 'cancel') return;
            const model = root.MealPlanSchedule, draft = this.draft;
            if (this.edit?.scope === 'meal' && (button.dataset.scheduleMode || ['month','date','add-prep','remove-prep','apply'].includes(button.dataset.scheduleAction))) return;
            if (button.dataset.scheduleMode) model.setDateMode(draft, button.dataset.scheduleMode);
            else if (button.dataset.schedulePortionMode) model.setPortionMode(draft, button.dataset.schedulePortionMode, this.schedulingDraft());
            else switch (button.dataset.scheduleAction) {
                case 'cancel': this.form.hidden = true; this.options.onCancel?.(); return;
                case 'month': draft.calendarMonth = model.shiftMonth(draft.calendarMonth, Number(button.dataset.direction)); break;
                case 'date': model.toggleDate(draft, button.dataset.date); break;
                case 'apply': model.applyDefaults(draft); this.setMessage('Defaults applied to selected days.'); break;
                case 'select-group-members': {
                    if (this.ui.loading || !this.ui.membersLoaded || draft.portionMode !== 'family') return;
                    try {
                        model.selectGroupMembers(draft, this.ui.groupIds);
                        this.setMessage('Group selection applied to the people above. Individually adjusted days stay unchanged.');
                    } catch (error) { this.setMessage(error.message, true); }
                    break;
                }
                case 'step': {
                    const input = button.parentElement.querySelector('input');
                    input.value = Math.max(0.01, Math.round(((Number(input.value) || 0) + Number(button.dataset.direction) * 0.5) * 100) / 100);
                    this.updateField(input); break;
                }
                case 'add-prep':
                    draft.prepSteps.push({date:draft.selectedDates[0] || this.options.today, instruction:''});
                    this.form.querySelector('[data-schedule-section="prep"]').open = true;
                    break;
                case 'remove-prep': draft.prepSteps.splice(Number(button.dataset.step), 1); break;
                case 'retry-members': await this.loadMembers(); return;
                case 'review-members': this.ui.memberReview = []; this.setMessage('Updated family list accepted.'); break;
                case 'add-member': await this.saveMember(); return;
                case 'save-member': await this.saveMember(button.dataset.member); return;
                default: return;
            }
            this.render();
        }

        async saveMember(id) {
            if (this.ui.loading || this.ui.busy || this.ui.memberBusy) return;
            const name = String(id ? this.ui.names[id] ?? this.draft.members.find(member => member.id === id)?.name : this.ui.newName).trim();
            if (!name) { this.setMessage('Enter a family member’s name.', true); this.render(); return; }
            this.ui.memberBusy = true;
            this.setMessage('Saving family member…');
            this.render();
            try {
                const response = await fetch(`/api/meal-plan/members${id ? '/' + encodeURIComponent(id) : ''}`, {method:id ? 'PATCH' : 'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
                const data = await response.json();
                if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to save this family member.');
                const members = id ? this.draft.members.map(member => member.id === id ? {...member, ...data.member} : member) : [...this.draft.members, data.member];
                this.syncMembers(members);
                if (id) delete this.ui.names[id]; else this.ui.newName = '';
                this.setMessage('Family member saved.');
                this.options.onMembersChanged?.();
            } catch (error) { this.setMessage(error.message, true); }
            finally { this.ui.memberBusy = false; this.render(); }
        }

        collectPayload() {
            if (this.ui.busy || this.ui.memberBusy || this.ui.saved) return;
            if (this.ui.loading) { this.setMessage('Wait for family members to finish loading.', true); this.render(); return; }
            if (this.draft.portionMode === 'family' && this.ui.memberReview.length) {
                this.setMessage('Review the updated portions, then choose “Use updated family list” before saving.', true);
                this.render(); return;
            }
            let payload;
            try { payload = root.MealPlanSchedule.payload(this.schedulingDraft()); }
            catch (error) { this.setMessage(error.message, true); this.render(); return; }
            if (!this.form.reportValidity()) return;
            const context = this.edit ? {} : this.options.getContext();
            if (!context) return;
            return {...payload, ...context};
        }

        async submit(event) {
            event.preventDefault();
            if (!this.edit && this.options.onSubmit) return this.options.onSubmit();
            let payload = this.collectPayload();
            if (!payload) return;
            const edit = this.edit;
            let url = '/api/meal-plan/batches', method = 'POST';
            if (edit) {
                method = 'PATCH';
                if (edit.scope === 'meal') {
                    if (payload.allocations.length !== 1) { this.setMessage('Choose one date and one meal.', true); this.render(); return; }
                    const allocation = payload.allocations[0];
                    payload = {date:allocation.date,meal_type:allocation.meal_type,portion_mode:allocation.portion_mode,prep_notes:this.draft.notes,
                        ...(allocation.portion_mode === 'family' ? {member_portions:allocation.member_portions} : {planned_servings:allocation.planned_servings})};
                    url = '/api/meal-plan/' + encodeURIComponent(edit.id);
                } else {
                    url += '/' + encodeURIComponent(edit.id);
                    payload.batch_servings = root.MealPlanSchedule.summary(this.draft).totalServings + edit.spareServings;
                }
            }
            this.ui.busy = true;
            this.setMessage('Saving meal plan…');
            this.render();
            let result;
            try {
                const response = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
                result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to save this meal plan.');
            } catch (error) {
                this.setMessage(error.message, true);
                this.ui.busy = false;
                this.render();
                return;
            }
            // A refresh failure must never turn a successful save into a retry.
            const firstDate = this.draft.selectedDates[0];
            const groups = this.draft.groups;
            // The next open starts a new plan and must use the latest saved
            // personal defaults. Ordinary refreshes still preserve an open draft.
            this.draft = root.MealPlanSchedule.create({today:this.options.today, servings:this.options.servings, members:this.draft.members, groups});
            this.edit = null;
            this.generation += 1;
            this.ui.saved = true;
            this.ui.membersLoaded = false;
            this.ui.refreshMemberDefaults = true;
            this.ui.busy = false;
            this.ui.openDays.clear();
            this.ui.memberReview = [];
            this.ui.groupIds = [];
            this.setMessage('Meal plan saved.');
            this.render();
            this.form.hidden = true;
            try { await this.options.onSaved?.(result, firstDate, edit ? {scope:edit.scope,id:edit.id} : undefined); }
            catch (_) {
                this.setMessage('Meal plan saved. Reload to see the updated schedule.', true);
                this.form.hidden = false;
                this.render();
            }
        }
    }
    root.MealPlanPanel = MealPlanPanel;
})(globalThis);
