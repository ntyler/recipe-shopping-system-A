const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Use the existing Playwright/isolated API harness.
    // Flow: nine selected dates, eight servings -> shortage -> adjust dates/portions.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1200}});
        await context.addCookies([cookie]);
        const page = await context.newPage(), errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {if (['error','warning'].includes(message.type())) errors.push(message.text());});
        await page.goto(base + '/editor-qa');
        assert.equal(page.url(), base + '/editor-qa');
        assert.equal(await page.title(), 'AI Pantry — Meal Planner');
        assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
        const dialog = page.locator('#mealPlannerDialog'), shared = dialog.locator('[data-meal-shared-form]');
        const row = index => dialog.locator('[data-meal-editor]').nth(index);
        const amount = row(0).locator('[data-meal-recipe-servings]');
        const date = (form, day) => form.locator(`[data-schedule-action="date"][data-date="${day}"]`);
        const short = form => form.locator('.is-yield-short');
        const screenshot = async name => {
            const dir = process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if (dir) {fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}
        };
        await page.getByRole('button',{name:'Add Meals',exact:true}).click();
        await page.waitForFunction(() => !document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
        await row(0).locator('[name="recipe_url"]').selectOption('recipe://bread');
        await shared.getByRole('button',{name:'Household total',exact:true}).click();
        await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('1');
        await amount.fill('1');
        await shared.getByRole('button',{name:'Select days',exact:true}).click();
        await date(shared,'2026-10-05').click();
        await shared.getByRole('button',{name:'Previous month',exact:true}).click();
        await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
        const start = await date(shared,'2026-09-25').boundingBox();
        await page.mouse.move(start.x + start.width/2, start.y + start.height/2);await page.mouse.down();
        const end = await date(shared,'2026-10-03').boundingBox();
        await page.mouse.move(end.x + end.width/2, end.y + end.height/2);await page.mouse.up();
        assert.equal(await short(shared).count(),1);
        assert.equal(await date(shared,'2026-10-03').locator('small').textContent(),'Short 1');
        assert.equal(await date(shared,'2026-10-03').getAttribute('aria-pressed'),'true');
        assert.match(await date(shared,'2026-10-03').getAttribute('aria-label'),/Bread: 1 serving short/);
        assert.equal(await shared.locator('[data-schedule-action="date"][aria-pressed="true"]:not(.is-yield-short)').count(),8);
        assert.equal(await row(0).locator('[data-meal-yield-remaining]').textContent(),'1 serving beyond one full recipe');
        await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
        await screenshot('yield-coverage-desktop.png');
        await page.setViewportSize({width:390,height:844});
        await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
        assert(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
        assert(await shared.locator('.meal-schedule-calendar').evaluate(element => element.scrollWidth <= element.clientWidth + 1));
        assert(await date(shared,'2026-10-03').locator('small').isVisible());
        await screenshot('yield-coverage-mobile.png');
        await page.setViewportSize({width:1440,height:1200});
        // Removing an earlier date frees a serving for the last one.
        await date(shared,'2026-09-25').click();
        assert.equal(await short(shared).count(),0);
        assert.equal(await date(shared,'2026-10-03').getAttribute('aria-pressed'),'true');
        assert(!(await shared.locator('[data-schedule-yield-legend]').isVisible()));
        await date(shared,'2026-09-25').focus();await page.keyboard.press('Space');
        assert.equal(await short(shared).count(),1);
        // Part of September 30 fits; every later date needs its full portion.
        await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('1.5');
        await amount.fill('1.5');
        assert.equal(await date(shared,'2026-09-30').locator('small').textContent(),'Short 1');
        assert.equal(await date(shared,'2026-10-01').locator('small').textContent(),'Short 1½');
        assert.equal(await short(shared).count(),4);
        await amount.fill('');assert.equal(await short(shared).count(),0,'Invalid portions must clear stale shortage labels');
        await amount.fill('1');
        await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('1');
        // Two entries of one recipe consume one yield and split a same-day shortfall.
        await row(0).getByRole('button',{name:'Auto split',exact:true}).click();
        await dialog.locator('[data-meal-editor-add]').click();
        await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
        assert.equal(await date(shared,'2026-10-03').locator('small').textContent(),'Short 1');
        await row(1).locator('[name="recipe_url"]').selectOption('recipe://soup');
        assert.equal(await date(shared,'2026-10-03').locator('small').textContent(),'Short ½');
        assert.match(await date(shared,'2026-10-03').getAttribute('aria-label'),/Soup: 0.5 servings short/);
        await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
        await row(1).locator('[data-meal-editor-customize]').click();
        const custom = row(1).locator('[data-meal-editor-form]');
        assert.equal(await date(custom,'2026-10-03').locator('small').textContent(),'Short ½');
        assert.match(await date(custom,'2026-10-03').getAttribute('aria-label'),/Bread: 0.5 servings short/);
        await row(1).locator('[data-meal-editor-reset]').click();
        await row(1).locator('[data-meal-editor-remove]').click();
        await shared.getByRole('button',{name:'Split recipe yield',exact:true}).click();
        assert.equal(await short(shared).count(),0,'Spreading eight servings over nine dates clears the shortage');
        assert.equal(await dialog.locator('[data-meal-batch-save]').textContent(),'Save 9 Meals');
        assert.deepEqual(errors,[]);
        console.log('PASS: nine dates/eight servings, date and keyboard changes, partial shortages, invalid input, repeated recipes, custom calendar, split yield, desktop/mobile, clean console');
    } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
