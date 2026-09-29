// Existing automatic-allocation scenarios explicitly opt in to splitting.
const selectAuto = async (recipe, value) => {
    await recipe.selectOption(value);
    const row=recipe.locator('xpath=ancestor::*[@data-meal-editor]');
    const dialog=row.locator('xpath=ancestor::dialog');
    if (await row.locator('[data-meal-recipe-amount]').isHidden()) {
        await dialog.locator('[data-meal-shared-form]').getByRole('button',{name:'Split recipe yield',exact:true}).click();
    } else {
        for (const entry of await dialog.locator('[data-meal-editor]').all()) {
            if (await entry.evaluate(element=>Boolean(element.mealPlannerEntry.portionsDraft)))
                await entry.getByRole('button',{name:'Auto split',exact:true}).click();
        }
        const automatic=row.getByRole('button',{name:'Auto split',exact:true});
        if (await automatic.isVisible()) await automatic.click();
        else {
            const calendar=dialog.locator('#'+await row.locator('[data-meal-editor-customize]').getAttribute('aria-controls'));
            if(await calendar.isVisible()) await calendar.getByRole('button',{name:'Split recipe yield',exact:true}).click();
        }
    }
};

const customPlan = (dialog, index) => dialog.locator(`[data-meal-calendar-recipe="${index}"]`);
const selectCalendar = async (dialog, index = null) => {
    await dialog.locator('[data-meal-calendar-select]').selectOption(index === null ? '' : await dialog.locator('[data-meal-editor]').nth(index).getAttribute('data-meal-editor'));
};
module.exports = {selectAuto, customPlan, selectCalendar};
