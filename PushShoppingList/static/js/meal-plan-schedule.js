/* Calendar dates and portion allocations shared by the recipe planning controls. */
(function (root) {
    'use strict';

    const MEAL_TYPES = Object.freeze(['breakfast', 'lunch', 'dinner', 'snack']);
    const clone = value => JSON.parse(JSON.stringify(value));
    const validMeal = meal => MEAL_TYPES.includes(meal);

    function parseDate(value) {
        if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
        const [year, month, day] = value.split('-').map(Number);
        if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31) return null;
        const date = new Date(0);
        date.setHours(12, 0, 0, 0);
        date.setFullYear(year, month - 1, day);
        return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
    }

    function formatDate(date) {
        if (!date || !Number.isFinite(date.getTime())) return '';
        return `${String(date.getFullYear()).padStart(4, '0')}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    function dateRange(start, end) {
        const cursor = parseDate(start);
        if (!cursor || !parseDate(end) || start > end) return [];
        const dates = [];
        while (formatDate(cursor) <= end) {
            dates.push(formatDate(cursor));
            cursor.setDate(cursor.getDate() + 1);
            if (cursor.getFullYear() > 9999) break;
        }
        return dates;
    }

    function shiftMonth(month, change) {
        const date = parseDate(`${month}-01`);
        if (!date || !Number.isInteger(change)) return '';
        date.setMonth(date.getMonth() + change);
        return date.getFullYear() >= 1 && date.getFullYear() <= 9999 ? formatDate(date).slice(0, 7) : '';
    }

    function calendarMonth(month) {
        const cursor = parseDate(`${month}-01`);
        if (!cursor) return {month: '', label: '', days: []};
        const label = cursor.toLocaleDateString(undefined, {month: 'long', year: 'numeric'});
        cursor.setDate(cursor.getDate() - (cursor.getDay() + 6) % 7);
        const days = [];
        for (let i = 0; i < 42; i += 1) {
            const date = formatDate(cursor);
            days.push({date, day: cursor.getDate(), inMonth: date.startsWith(`${month}-`)});
            cursor.setDate(cursor.getDate() + 1);
        }
        return {month, label, days};
    }

    function portion(value) {
        if ((typeof value !== 'string' && typeof value !== 'number') ||
            !/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(String(value).trim())) return null;
        const result = Number(value);
        return Number.isFinite(result) && result > 0 ? result : null;
    }

    // Add decimal quantities using integers, avoiding 0.1 + 0.2 display artifacts.
    function sum(values) {
        if (!values.length) return 0;
        if (values.some(value => !Number.isFinite(value))) return Infinity;
        const decimals = values.map(value => {
            const [mantissa, exponent = '0'] = String(value).toLowerCase().split('e');
            const [whole, fraction = ''] = mantissa.split('.');
            const scale = fraction.length - Number(exponent);
            return {digits: BigInt(whole + fraction), scale};
        });
        const scale = Math.max(0, ...decimals.map(value => value.scale));
        const digits = decimals.reduce((total, value) => total + value.digits * 10n ** BigInt(scale - value.scale), 0n);
        const text = (digits < 0n ? -digits : digits).toString().padStart(scale + 1, '0');
        return Number(`${digits < 0n ? '-' : ''}${scale ? `${text.slice(0, -scale)}.${text.slice(-scale)}` : text}`);
    }

    function splitServings(servings, count) {
        if (!count || portion(servings) === null) return [];
        const [mantissa, exponent = '0'] = String(servings).toLowerCase().split('e');
        const [whole, fraction = ''] = mantissa.split('.');
        const decimals = fraction.length - Number(exponent);
        const scale = Math.max(6, decimals + Math.ceil(Math.log10(count)));
        const units = BigInt(whole + fraction) * 10n ** BigInt(scale - decimals);
        const each = units / BigInt(count), remainder = units % BigInt(count);
        // Keep the recipe total exact, assigning any rounding remainder to the
        // last meal instead of rounding every meal up and creating servings.
        return Array.from({length: count}, (_, index) =>
            Number(`${each + (index === count - 1 ? remainder : 0n)}e-${scale}`));
    }

    function splitRecipeYield(drafts, servings) {
        // All rows for one recipe share one serving budget. Explicit household
        // or family portions consume that budget before automatic portions.
        const totals = drafts.map(draft => summary({...draft, recipePortions: undefined, recipeSplitError: ''}));
        const remaining = sum([servings, ...totals.map((total, index) => drafts[index].portionMode === 'recipe' ? 0 : -total.totalServings)]);
        const count = totals.reduce((value, total, index) => value + (drafts[index].portionMode === 'recipe' ? total.mealCount : 0), 0);
        const portions = splitServings(remaining, count);
        let offset = 0;
        return drafts.map((draft, index) => {
            if (draft.portionMode !== 'recipe') return draft;
            const recipePortions = portions.slice(offset, offset + totals[index].mealCount);
            offset += totals[index].mealCount;
            return {...draft, recipeYield: servings, recipePortions,
                recipeSplitError: remaining <= 0 ? 'No servings remain to split. Reduce this recipe’s custom portions or use Household total for every entry.' : ''};
        });
    }

    function normalizedMembers(members, retained = new Set()) {
        const seen = new Set();
        return (Array.isArray(members) ? members : []).filter(member => {
            if (!member || (member.archived === true && !retained.has(member.id)) || typeof member.id !== 'string' || !member.id || seen.has(member.id)) return false;
            seen.add(member.id);
            return true;
        }).map(member => ({
            id: member.id, name: String(member.name || [member.first_name, member.last_name].filter(Boolean).join(' ')),
            first_name: String(member.first_name || ''), last_name: String(member.last_name || ''),
            default_portion: portion(member.default_portion) || 1, ...(member.archived ? {archived:true} : {}),
            group_ids: [...new Set((Array.isArray(member.group_ids) ? member.group_ids : []).filter(id => typeof id === 'string' && id))]
        }));
    }

    function normalizedGroups(groups) {
        const seen = new Set();
        return (Array.isArray(groups) ? groups : []).filter(group => {
            if (!group || group.archived === true || typeof group.id !== 'string' || !group.id || seen.has(group.id)) return false;
            seen.add(group.id);
            return true;
        }).map(group => ({id: group.id, name: String(group.name || '')}));
    }

    function newFamilyDefaults(members) {
        return Object.fromEntries(members.map(member => [member.id,
            Object.fromEntries(MEAL_TYPES.map(meal => [meal, {enabled: true, servings: member.default_portion}]))]));
    }

    function defaultDay(draft) {
        return {
            mealEnabled: Object.fromEntries(MEAL_TYPES.map(meal => [meal, draft.mealTypes.includes(meal)])),
            household: clone(draft.householdDefaults),
            family: clone(draft.familyDefaults),
            overrides: {meals: false, household: false, family: false},
            notes: '', mealNotes: {}, allocationIds: {}, mealPortionModes: {}
        };
    }

    function ensureDay(draft, date) {
        if (!parseDate(date)) return null;
        if (!Object.hasOwn(draft.days, date)) draft.days[date] = defaultDay(draft);
        return draft.days[date];
    }

    function syncDefaults(draft) {
        Object.values(draft.days).forEach(day => {
            if (!day.overrides.meals) day.mealEnabled = Object.fromEntries(MEAL_TYPES.map(meal => [meal, draft.mealTypes.includes(meal)]));
            if (!day.overrides.household) day.household = clone(draft.householdDefaults);
            if (!day.overrides.family) day.family = clone(draft.familyDefaults);
        });
    }

    // Recipe-specific portions follow the shared schedule, including individual
    // day meal choices and notes. Neither source draft is changed.
    function withPortions(shared, portions) {
        const draft = clone(shared);
        for (const key of ['portionMode', 'householdDefaults', 'familyDefaults']) draft[key] = clone(portions[key]);
        setMembers(draft, shared.members, {newMembersEnabled: false});
        Object.values(draft.days).forEach(day => {
            day.overrides.household = false;
            day.overrides.family = false;
        });
        syncDefaults(draft);
        return draft;
    }

    function refreshDates(draft) {
        if (draft.dateMode === 'single') draft.selectedDates = parseDate(draft.singleDate) ? [draft.singleDate] : [];
        else if (draft.dateMode === 'range') draft.selectedDates = dateRange(draft.startDate, draft.endDate);
        else draft.selectedDates = [...draft.selectedDays].sort();
        draft.selectedDates.forEach(date => ensureDay(draft, date));
        return draft;
    }

    function create(options = {}) {
        const today = parseDate(options.today) ? options.today : formatDate(new Date());
        const members = normalizedMembers(options.members);
        const servings = portion(options.servings) || 1;
        return refreshDates({
            dateMode: 'single', singleDate: today, startDate: today, endDate: today,
            selectedDates: [], selectedDays: [today], calendarMonth: today.slice(0, 7),
            portionMode: options.splitRecipeYield ? 'recipe' : 'household', mealTypes: ['dinner'],
            ...(options.splitRecipeYield ? {recipeYield: servings} : {}),
            householdDefaults: Object.fromEntries(MEAL_TYPES.map(meal => [meal, servings])),
            familyDefaults: newFamilyDefaults(members), members, groups: normalizedGroups(options.groups), days: {}, prepSteps: [], notes: ''
        });
    }

    function setDateMode(draft, mode) {
        if (!['single', 'range', 'days'].includes(mode)) throw new Error('Choose a valid date mode.');
        draft.dateMode = mode;
        return refreshDates(draft);
    }

    function setSingleDate(draft, date) {
        if (draft.edit?.scope === 'meal' && parseDate(date) && date !== draft.singleDate) {
            const previous = Object.keys(draft.days).find(key => draft.days[key]?.allocationIds?.[draft.mealTypes[0]] === draft.edit.id);
            if (previous && previous !== date) {
                draft.days[date] = draft.days[previous];
                delete draft.days[previous];
            }
        }
        draft.singleDate = date;
        return refreshDates(draft);
    }

    function setRange(draft, start, end) {
        draft.startDate = start;
        draft.endDate = end;
        return refreshDates(draft);
    }

    function setDates(draft, dates) {
        draft.selectedDays = [...new Set(dates.filter(date => parseDate(date)))].sort();
        draft.dateMode = 'days';
        return refreshDates(draft);
    }

    function toggleDate(draft, date, selected) {
        if (!parseDate(date)) return draft;
        const dates = new Set(draft.selectedDays);
        if (selected === undefined ? !dates.has(date) : selected) dates.add(date);
        else dates.delete(date);
        return setDates(draft, [...dates]);
    }

    function setPortionMode(draft, mode, source = draft) {
        if (!['household', 'family'].includes(mode) && !(mode === 'recipe' && !draft.edit && portion(draft.recipeYield))) throw new Error('Choose a valid portions mode.');
        if (draft.portionMode === mode) return draft;
        if (draft.portionMode === 'recipe' && mode === 'household') {
            const seeded = new Set();
            summary(source).days.forEach(day => day.meals.forEach(meal => {
                draft.days[day.date].household[meal.meal_type] = meal.planned_servings;
                draft.days[day.date].overrides.household = false;
                if (!seeded.has(meal.meal_type)) draft.householdDefaults[meal.meal_type] = meal.planned_servings;
                seeded.add(meal.meal_type);
            }));
        }
        draft.portionMode = mode;
        if (draft.edit) Object.values(draft.days).forEach(day => { day.mealPortionModes = {}; });
        return draft;
    }

    function setMeals(draft, types) {
        if (draft.edit?.scope === 'meal') {
            const next = MEAL_TYPES.find(meal => types.includes(meal));
            if (!next) return draft;
            const previous = draft.mealTypes[0];
            if (next !== previous) {
                draft.householdDefaults[next] = draft.householdDefaults[previous];
                Object.values(draft.familyDefaults).forEach(cells => { cells[next] = clone(cells[previous]); });
                Object.values(draft.days).forEach(day => {
                    day.household[next] = day.household[previous];
                    Object.values(day.family).forEach(cells => { cells[next] = clone(cells[previous]); });
                    for (const key of ['mealNotes','allocationIds','mealPortionModes']) {
                        day[key][next] = day[key][previous]; delete day[key][previous];
                    }
                    day.mealEnabled = Object.fromEntries(MEAL_TYPES.map(meal => [meal, meal === next]));
                });
            }
            types = [next];
        }
        draft.mealTypes = MEAL_TYPES.filter(meal => types.includes(meal));
        syncDefaults(draft);
        return draft;
    }

    function setHouseholdDefault(draft, meal, value) {
        if (draft.portionMode === 'recipe') setPortionMode(draft, 'household');
        if (validMeal(meal)) draft.householdDefaults[meal] = value;
        syncDefaults(draft);
        return draft;
    }

    function setFamilyDefault(draft, memberId, meal, value) {
        if (validMeal(meal) && Object.hasOwn(draft.familyDefaults, memberId)) {
            Object.assign(draft.familyDefaults[memberId][meal], value);
        }
        syncDefaults(draft);
        return draft;
    }

    function setDayMeal(draft, date, meal, enabled) {
        const day = ensureDay(draft, date);
        if (day && validMeal(meal)) {
            day.mealEnabled[meal] = !!enabled;
            day.overrides.meals = true;
        }
        return draft;
    }

    function setDayHousehold(draft, date, meal, value) {
        if (draft.portionMode === 'recipe') setPortionMode(draft, 'household');
        const day = ensureDay(draft, date);
        if (day && validMeal(meal)) {
            day.household[meal] = value;
            day.overrides.household = true;
        }
        return draft;
    }

    function setDayFamily(draft, date, memberId, meal, value) {
        const day = ensureDay(draft, date);
        if (day && validMeal(meal) && Object.hasOwn(day.family, memberId)) {
            Object.assign(day.family[memberId][meal], value);
            day.overrides.family = true;
        }
        return draft;
    }

    function setDayNotes(draft, date, notes) {
        const day = ensureDay(draft, date);
        if (day) day.notes = String(notes);
        return draft;
    }

    function setMealNotes(draft, date, meal, notes) {
        const day = ensureDay(draft, date);
        if (day && validMeal(meal)) day.mealNotes[meal] = String(notes);
        return draft;
    }

    function mealPortionMode(draft, date, meal) {
        return draft.days[date]?.mealPortionModes?.[meal] || draft.portionMode;
    }

    function canAssignMember(draft, member, date, meal) {
        if (!member.archived) return true;
        const id = date ? draft.days[date]?.allocationIds?.[meal] : draft.edit?.scope === 'meal' ? draft.edit.id : null;
        return !!id && !!draft.edit?.assignments?.[id]?.includes(member.id);
    }

    function seedSavedFamilyDefaults(draft, initialize = false) {
        if (draft.edit?.scope !== 'batch' || !draft.edit.defaultSeeds) return;
        const baseline = draft.edit.seedCells || {}, next = {};
        for (const member of draft.members) {
            next[member.id] = {};
            for (const meal of MEAL_TYPES) {
                const saved = draft.edit.defaultSeeds[meal]?.member_portions?.find(part => part.member_id === member.id);
                const desired = {enabled:!member.archived && !!saved, servings:saved?.servings ?? member.default_portion};
                const current = draft.familyDefaults[member.id][meal], previous = baseline[member.id]?.[meal];
                // A later active-member lookup can identify a saved assignee.
                // Seed only untouched defaults; keep edits typed during loading.
                if (initialize || (previous && current.enabled === previous.enabled && Number(current.servings) === Number(previous.servings))) {
                    draft.familyDefaults[member.id][meal] = clone(desired);
                }
                if (member.archived) draft.familyDefaults[member.id][meal].enabled = false;
                next[member.id][meal] = desired;
            }
        }
        draft.edit.seedCells = next;
    }

    function applyDefaults(draft) {
        draft.selectedDates.forEach(date => {
            const day = ensureDay(draft, date);
            const defaults = defaultDay(draft);
            day.mealEnabled = defaults.mealEnabled;
            day.overrides.meals = false;
            // Applying family defaults does not destroy the household draft, or vice versa.
            if (draft.portionMode !== 'recipe') {
                day[draft.portionMode] = defaults[draft.portionMode];
                day.overrides[draft.portionMode] = false;
            }
            if (draft.edit) day.mealPortionModes = {};
        });
        return draft;
    }

    function setMembers(draft, members, {newMembersEnabled = true, refreshDefaults = false} = {}) {
        const previous = new Map(draft.members.map(member => [member.id, member]));
        const retained = new Set(Object.keys(draft.edit?.savedMembers || {}));
        const list = Array.isArray(members) ? [...members] : [];
        for (const [id, member] of Object.entries(draft.edit?.savedMembers || {})) {
            if (!list.some(item => item.id === id)) list.push({...member, archived:true});
        }
        draft.members = normalizedMembers(list, retained);
        const defaults = newFamilyDefaults(draft.members);
        for (const member of draft.members) {
            if (Object.hasOwn(draft.familyDefaults, member.id)) {
                const existing = draft.familyDefaults[member.id];
                MEAL_TYPES.forEach(meal => {
                    const cell = existing[meal];
                    // Update untouched defaults on a fresh plan, preserving
                    // edits made while the member request was in flight.
                    if (!refreshDefaults || !cell.enabled || Number(cell.servings) !== previous.get(member.id)?.default_portion) {
                        defaults[member.id][meal] = cell;
                    }
                });
            }
            else if (!newMembersEnabled || draft.edit) MEAL_TYPES.forEach(meal => { defaults[member.id][meal].enabled = false; });
        }
        draft.familyDefaults = defaults;
        seedSavedFamilyDefaults(draft);
        Object.values(draft.days).forEach(day => {
            day.family = Object.fromEntries(draft.members.map(member => [member.id,
                Object.hasOwn(day.family, member.id) ? day.family[member.id] : clone(defaults[member.id])]));
        });
        syncDefaults(draft);
        return draft;
    }

    function setGroups(draft, groups) {
        draft.groups = normalizedGroups(groups);
        return draft;
    }

    function selectGroupMembers(draft, groupIds) {
        const activeGroups = new Set(draft.groups.map(group => group.id));
        const selected = new Set((Array.isArray(groupIds) ? groupIds : []).filter(id => activeGroups.has(id)));
        if (!selected.size) throw new Error('Choose at least one active group.');
        for (const member of draft.members) {
            const enabled = !member.archived && member.group_ids.some(id => selected.has(id));
            MEAL_TYPES.forEach(meal => { draft.familyDefaults[member.id][meal].enabled = enabled; });
        }
        // Group membership is resolved now, never bound to future group edits.
        // Like other default edits, this preserves explicit per-day overrides.
        syncDefaults(draft);
        return draft;
    }

    function summary(draft) {
        const errors = [];
        if (draft.dateMode === 'range' && (!parseDate(draft.startDate) || !parseDate(draft.endDate))) errors.push('Choose a valid start and end date.');
        else if (draft.dateMode === 'range' && draft.startDate > draft.endDate) errors.push('The end date must be on or after the start date.');
        else if (!draft.selectedDates.length) errors.push('Select at least one date.');
        if (draft.portionMode === 'family' && !draft.members.length) errors.push('Add at least one family member.');

        const splitCount = draft.portionMode === 'recipe' ? draft.selectedDates.reduce((count, date) =>
            count + MEAL_TYPES.filter(meal => ensureDay(draft, date).mealEnabled[meal]).length, 0) : 0;
        const split = draft.recipePortions || splitServings(draft.recipeYield, splitCount);
        let splitIndex = 0;
        if (draft.portionMode === 'recipe' && portion(draft.recipeYield) === null) errors.push('The recipe needs a valid serving yield.');
        if (draft.portionMode === 'recipe' && draft.recipeSplitError) errors.push(draft.recipeSplitError);

        const memberValues = Object.fromEntries(draft.members.map(member => [member.id, []]));
        const days = draft.selectedDates.map(date => {
            const day = ensureDay(draft, date);
            const meals = [];
            for (const meal of MEAL_TYPES) {
                if (!day.mealEnabled[meal]) continue;
                let servings;
                const memberPortions = [];
                const mode = mealPortionMode(draft, date, meal);
                if (mode === 'household' || mode === 'recipe') {
                    servings = portion(mode === 'recipe' ? split[splitIndex++] : day.household[meal]);
                    if (servings === null) errors.push(`${date} ${meal}: enter a finite number of servings greater than zero.`);
                } else {
                    for (const member of draft.members) {
                        const cell = day.family[member.id][meal];
                        if (!cell.enabled) continue;
                        if (!canAssignMember(draft, member, date, meal)) {
                            errors.push(`${date} ${meal}: ${member.name} is archived and cannot be assigned to another meal.`);
                            continue;
                        }
                        const value = portion(cell.servings);
                        if (value === null) errors.push(`${date} ${meal}: enter positive, finite portions for ${member.name || 'this family member'}.`);
                        else {
                            memberPortions.push({member_id: member.id, servings: value});
                            memberValues[member.id].push(value);
                        }
                    }
                    servings = sum(memberPortions.map(member => member.servings));
                    // A meal with nobody eating is skipped, rather than persisted as zero servings.
                    if (!servings) continue;
                }
                if (servings !== null) meals.push({meal_type: meal, planned_servings: servings, member_portions: memberPortions, ...(draft.edit ? {portion_mode:mode} : {})});
            }
            const customized = day.overrides.meals || day.overrides[draft.portionMode];
            return {date, meals, totalServings: sum(meals.map(meal => meal.planned_servings)), customized};
        });
        const mealCount = days.reduce((total, day) => total + day.meals.length, 0);
        const totalServings = sum(days.map(day => day.totalServings));
        if (!mealCount && !errors.length) errors.push('Select at least one meal with servings.');
        if (!Number.isFinite(totalServings)) errors.push('The total number of servings is too large.');
        const memberTotals = Object.fromEntries(draft.members.map(member => [member.id, sum(memberValues[member.id])]));
        return {valid: !errors.length, errors, dayCount: days.length, mealCount, totalServings, memberTotals, days};
    }

    function payload(draft) {
        const totals = summary(draft);
        if (!totals.valid) throw new Error(totals.errors[0]);
        const steps = draft.prepSteps.map(step => ({date: step.date, instruction: String(step.instruction || '').trim(),
            // Completion is edited in the planner, not this form. Omitting it
            // preserves a completion change made while this editor was open.
            ...(draft.edit && step.id ? {id:step.id} : {})}));
        for (const step of steps) {
            if (!parseDate(step.date) || !step.instruction) throw new Error('Every preparation task needs a valid date and an instruction.');
        }
        return {
            portion_mode: draft.portionMode === 'recipe' ? 'household' : draft.portionMode,
            prep_notes: String(draft.notes || ''),
            prep_steps: steps,
            allocations: totals.days.flatMap(day => day.meals.map(meal => ({
                date: day.date, meal_type: meal.meal_type,
                prep_notes: draft.days[day.date].mealNotes[meal.meal_type] ?? draft.days[day.date].notes,
                ...(draft.edit && draft.days[day.date].allocationIds[meal.meal_type] ? {id:draft.days[day.date].allocationIds[meal.meal_type]} : {}),
                ...(draft.edit ? {portion_mode:meal.portion_mode} : {}),
                ...(mealPortionMode(draft, day.date, meal.meal_type) === 'family' ? {member_portions: meal.member_portions} : {planned_servings: meal.planned_servings})
            })))
        };
    }

    function fromSaved({meal, batch, meals}, scope = 'meal', options = {}) {
        if (!['meal','batch'].includes(scope)) throw new Error('Choose a valid edit scope.');
        const allocations = scope === 'meal' ? [meal] : meals || batch?.allocations;
        if (!Array.isArray(allocations) || !allocations.length || allocations.some(item => !item?.id || !parseDate(item.date) || !validMeal(item.meal_type))) {
            throw new Error('The saved schedule could not be loaded.');
        }
        const source = scope === 'meal' ? meal : batch;
        if (!source?.id) throw new Error('The saved schedule has no identifier.');
        const draft = create({...options, today:allocations[0].date, servings:allocations[0].planned_servings});
        const savedMembers = {}, assignments = {};
        allocations.forEach(item => {
            assignments[item.id] = (item.member_portions || []).map(part => part.member_id);
            (item.member_portions || []).forEach(part => {
                savedMembers[part.member_id] = {id:part.member_id, name:part.name || part.name_snapshot || 'Saved family member', default_portion:part.servings, archived:true};
            });
        });
        draft.edit = {scope, id:source.id, savedMembers, assignments};
        setMembers(draft, options.members || [], {newMembersEnabled:false});
        Object.values(draft.familyDefaults).forEach(cells => MEAL_TYPES.forEach(type => { cells[type].enabled = false; }));
        draft.portionMode = source.portion_mode === 'family' ? 'family' : 'household';
        draft.mealTypes = MEAL_TYPES.filter(type => allocations.some(item => item.meal_type === type));
        draft.days = {};
        const dates = [...new Set(allocations.map(item => item.date))].sort();
        setDates(draft, dates);
        if (scope === 'meal') { draft.singleDate = meal.date; setDateMode(draft, 'single'); }
        for (const date of dates) {
            const day = draft.days[date];
            day.mealEnabled = Object.fromEntries(MEAL_TYPES.map(type => [type,false]));
            day.overrides = {meals:true, household:true, family:true};
        }
        for (const item of allocations) {
            const day = draft.days[item.date], type = item.meal_type;
            if (day.allocationIds[type]) throw new Error('This plan has multiple meals in the same slot and cannot be edited together. Edit each meal separately.');
            day.mealEnabled[type] = true;
            day.allocationIds[type] = item.id;
            day.mealNotes[type] = String(item.prep_notes || '');
            day.mealPortionModes[type] = item.portion_mode || ((item.member_portions || []).length ? 'family' : 'household');
            day.household[type] = item.planned_servings;
            (item.member_portions || []).forEach(part => { day.family[part.member_id][type] = {enabled:true,servings:part.servings}; });
        }
        if (scope === 'meal') {
            const day = draft.days[meal.date];
            draft.portionMode = day.mealPortionModes[meal.meal_type];
            draft.householdDefaults = clone(day.household);
            draft.familyDefaults = clone(day.family);
            day.overrides = {meals:false,household:false,family:false};
        }
        draft.notes = String(source.prep_notes || '');
        draft.prepSteps = scope === 'batch' ? clone(batch.prep_steps || []) : [];
        if (scope === 'batch') {
            draft.edit.defaultSeeds = {};
            [...allocations].sort((a,b) => a.date.localeCompare(b.date)).forEach(item => {
                if (!draft.edit.defaultSeeds[item.meal_type]) {
                    draft.edit.defaultSeeds[item.meal_type] = clone(item);
                    draft.householdDefaults[item.meal_type] = item.planned_servings;
                }
            });
            seedSavedFamilyDefaults(draft, true);
        }
        return draft;
    }

    root.MealPlanSchedule = Object.freeze({
        MEAL_TYPES, parseDate, formatDate, dateRange, shiftMonth, calendarMonth, create,
        setDateMode, setSingleDate, setRange, setDates, toggleDate, setPortionMode, setMeals,
        setHouseholdDefault, setFamilyDefault, setDayMeal, setDayHousehold, setDayFamily,
        setDayNotes, setMealNotes, mealPortionMode, canAssignMember, fromSaved,
        applyDefaults, setMembers, setGroups, selectGroupMembers, withPortions, splitRecipeYield, summary, payload
    });
})(globalThis);
