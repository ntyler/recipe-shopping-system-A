// Existing automatic-allocation scenarios explicitly opt in to splitting.
const selectAuto = async (recipe, value) => {
    await recipe.selectOption(value);
    const row=recipe.locator('xpath=ancestor::*[@data-meal-editor]');
    const dialog=row.locator('xpath=ancestor::dialog');
    if (await row.locator('[data-meal-recipe-amount]').isHidden()) {
        await dialog.locator('[data-meal-shared-form]').getByRole('button',{name:'Split recipe yield',exact:true}).click();
    } else if (await row.evaluate(element=>Boolean(element.mealPlannerEntry.panel))) {
        const calendar=dialog.locator('#'+await row.evaluate(element=>element.mealPlannerEntry.overrideContainer.id));
        if(await calendar.isVisible()) await calendar.getByRole('button',{name:'Split recipe yield',exact:true}).click();
    } else {
        await dialog.getByRole('button',{name:'Auto split all',exact:true}).click();
    }
};

const customPlan = (dialog, index) => dialog.locator(`[data-meal-calendar-recipe="${index}"]`);
const selectCalendar = async (dialog, index = null) => {
    await dialog.locator('[data-meal-calendar-select]').selectOption(index === null ? '' : await dialog.locator('[data-meal-editor]').nth(index).getAttribute('data-meal-editor'));
};
// Retain coverage for legacy custom drafts through explicit fixture setup.
// New Add Meals flows have no Customize control and use only the shared calendar.
const legacyCustomPlan = async row => row.evaluate(element =>
    customizeMealPlannerRecipe(element.closest('dialog'), element.mealPlannerEntry));

const selectedPlanDates = async form => form.evaluate(element => {
    const state = element.closest('dialog').mealPlanScheduleState;
    const panel = [state.panel, ...state.entries.map(entry => entry.panel)].find(panel => panel?.form === element);
    return panel.draft.selectedDates;
});

// Change dates using the rendered calendar, including navigation across months.
const selectDates = async (form, dates) => {
    const previous = await selectedPlanDates(form);
    const changed = [...new Set([...previous, ...dates])].filter(date => previous.includes(date) !== dates.includes(date));
    for (const date of changed) {
        const day = form.locator(`[data-schedule-action="date"][data-date="${date}"]`);
        for (let attempt = 0; !(await day.count()) && attempt < 24; attempt++) {
            const first = await form.locator('[data-schedule-action="date"]').first().getAttribute('data-date');
            await form.getByRole('button', {name:date < first ? 'Previous month' : 'Next month', exact:true}).click();
        }
        await day.click();
    }
};

const dateRange = (start, end) => {
    const dates = [], day = new Date(start + 'T00:00:00Z');
    while (day.toISOString().slice(0, 10) <= end) {
        dates.push(day.toISOString().slice(0, 10));
        day.setUTCDate(day.getUTCDate() + 1);
    }
    return dates;
};

module.exports = {selectAuto, customPlan, selectCalendar, legacyCustomPlan, selectDates, selectedPlanDates, dateRange};
