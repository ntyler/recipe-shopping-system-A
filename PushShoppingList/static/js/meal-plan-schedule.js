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
        const text = digits.toString().padStart(scale + 1, '0');
        return Number(scale ? `${text.slice(0, -scale)}.${text.slice(-scale)}` : text);
    }

    function normalizedMembers(members) {
        const seen = new Set();
        return (Array.isArray(members) ? members : []).filter(member => {
            if (!member || member.archived === true || typeof member.id !== 'string' || !member.id || seen.has(member.id)) return false;
            seen.add(member.id);
            return true;
        }).map(member => ({
            id: member.id, name: String(member.name || [member.first_name, member.last_name].filter(Boolean).join(' ')),
            first_name: String(member.first_name || ''), last_name: String(member.last_name || ''),
            default_portion: portion(member.default_portion) || 1,
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
            notes: ''
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
            portionMode: 'household', mealTypes: ['dinner'],
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

    function setPortionMode(draft, mode) {
        if (!['household', 'family'].includes(mode)) throw new Error('Choose a valid portions mode.');
        draft.portionMode = mode;
        return draft;
    }

    function setMeals(draft, types) {
        draft.mealTypes = MEAL_TYPES.filter(meal => types.includes(meal));
        syncDefaults(draft);
        return draft;
    }

    function setHouseholdDefault(draft, meal, value) {
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

    function applyDefaults(draft) {
        draft.selectedDates.forEach(date => {
            const day = ensureDay(draft, date);
            const defaults = defaultDay(draft);
            day.mealEnabled = defaults.mealEnabled;
            day.overrides.meals = false;
            // Applying family defaults does not destroy the household draft, or vice versa.
            day[draft.portionMode] = defaults[draft.portionMode];
            day.overrides[draft.portionMode] = false;
        });
        return draft;
    }

    function setMembers(draft, members, {newMembersEnabled = true, refreshDefaults = false} = {}) {
        const previous = new Map(draft.members.map(member => [member.id, member]));
        draft.members = normalizedMembers(members);
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
            else if (!newMembersEnabled) MEAL_TYPES.forEach(meal => { defaults[member.id][meal].enabled = false; });
        }
        draft.familyDefaults = defaults;
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
            const enabled = member.group_ids.some(id => selected.has(id));
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

        const memberValues = Object.fromEntries(draft.members.map(member => [member.id, []]));
        const days = draft.selectedDates.map(date => {
            const day = ensureDay(draft, date);
            const meals = [];
            for (const meal of MEAL_TYPES) {
                if (!day.mealEnabled[meal]) continue;
                let servings;
                const memberPortions = [];
                if (draft.portionMode === 'household') {
                    servings = portion(day.household[meal]);
                    if (servings === null) errors.push(`${date} ${meal}: enter a finite number of servings greater than zero.`);
                } else {
                    for (const member of draft.members) {
                        const cell = day.family[member.id][meal];
                        if (!cell.enabled) continue;
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
                if (servings !== null) meals.push({meal_type: meal, planned_servings: servings, member_portions: memberPortions});
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
        const steps = draft.prepSteps.map(step => ({date: step.date, instruction: String(step.instruction || '').trim()}));
        for (const step of steps) {
            if (!parseDate(step.date) || !step.instruction) throw new Error('Every preparation task needs a valid date and an instruction.');
        }
        return {
            portion_mode: draft.portionMode,
            prep_notes: String(draft.notes || ''),
            prep_steps: steps,
            allocations: totals.days.flatMap(day => day.meals.map(meal => ({
                date: day.date, meal_type: meal.meal_type, prep_notes: draft.days[day.date].notes,
                ...(draft.portionMode === 'family' ? {member_portions: meal.member_portions} : {planned_servings: meal.planned_servings})
            })))
        };
    }

    root.MealPlanSchedule = Object.freeze({
        MEAL_TYPES, parseDate, formatDate, dateRange, shiftMonth, calendarMonth, create,
        setDateMode, setSingleDate, setRange, setDates, toggleDate, setPortionMode, setMeals,
        setHouseholdDefault, setFamilyDefault, setDayMeal, setDayHousehold, setDayFamily,
        setDayNotes, applyDefaults, setMembers, setGroups, selectGroupMembers, summary, payload
    });
})(globalThis);
