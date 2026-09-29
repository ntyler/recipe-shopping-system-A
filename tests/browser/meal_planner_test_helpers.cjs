// Existing automatic-allocation scenarios explicitly opt in to splitting.
const selectAuto = async (recipe, value) => {
    await recipe.selectOption(value);
    const row=recipe.locator('xpath=ancestor::*[@data-meal-editor]');
    const dialog=row.locator('xpath=ancestor::dialog');
    if (await row.locator('[data-meal-recipe-amount]').isHidden()) {
        await dialog.locator('[data-meal-shared-form]').getByRole('button',{name:'Split recipe yield',exact:true}).click();
    } else if (await row.evaluate(element=>Boolean(element.mealPlannerEntry.panel))) {
        const calendar=dialog.locator('#'+await row.locator('[data-meal-editor-customize]').getAttribute('aria-controls'));
        if(await calendar.isVisible()) await calendar.getByRole('button',{name:'Split recipe yield',exact:true}).click();
    } else {
        await dialog.getByRole('button',{name:'Auto split all',exact:true}).click();
    }
};

const customPlan = (dialog, index) => dialog.locator(`[data-meal-calendar-recipe="${index}"]`);
const selectCalendar = async (dialog, index = null) => {
    await dialog.locator('[data-meal-calendar-select]').selectOption(index === null ? '' : await dialog.locator('[data-meal-editor]').nth(index).getAttribute('data-meal-editor'));
};
module.exports = {selectAuto, customPlan, selectCalendar};
