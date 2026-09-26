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
        else if (await row.locator('[data-meal-editor-form]').isVisible())
            await row.locator('[data-meal-editor-form]').getByRole('button',{name:'Split recipe yield',exact:true}).click();
    }
};

module.exports = {selectAuto};
