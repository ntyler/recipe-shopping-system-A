const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Exercise real mouse gestures with Playwright.
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1000}});
        await context.addCookies([cookie]);
        const page = await context.newPage(), errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (['error','warning'].includes(message.type())) errors.push(message.text()); });
        await page.goto(base + '/editor-qa');
        assert.equal(await page.title(), 'AI Pantry — Meal Planner');
        const dialog = page.locator('#mealPlannerDialog');
        const row = i => dialog.locator('[data-meal-editor]').nth(i);
        const editor = i => i === 0 ? dialog.locator('[data-meal-shared-form]') : row(i).locator('[data-meal-editor-form]');
        const day = (i,date) => editor(i).locator(`[data-schedule-action="date"][data-date="${date}"]`);
        const selected = i => editor(i).locator('[data-schedule-action="date"][aria-pressed="true"]').evaluateAll(nodes => nodes.map(n => n.dataset.date));
        const point = async locator => { const box=await locator.boundingBox();assert(box);return {x:box.x+box.width/2,y:box.y+box.height/2}; };
        const move = async locator => { const p=await point(locator);await page.mouse.move(p.x,p.y); };
        const drag = async (i,from,to) => {
            await editor(i).locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
            await move(day(i,from));await page.mouse.down();await move(day(i,to));await page.mouse.up();
        };
        const ready = () => page.waitForFunction(() => {const s=document.getElementById('mealPlannerDialog').mealPlanScheduleState;return !s.panel.ui.loading&&s.entries.every(e=>!e.panel?.ui.loading);});
        await page.getByRole('button',{name:'Add Meals',exact:true}).click();await ready();
        await row(0).locator('[name="recipe_url"]').selectOption('recipe://bread');
        await editor(0).getByRole('button',{name:'Select days',exact:true}).click();
        await drag(0,'2026-10-06','2026-10-09');
        assert.deepEqual(await selected(0),['2026-10-05','2026-10-06','2026-10-07','2026-10-08','2026-10-09']);
        assert.match(await editor(0).locator('[data-schedule-summary]').textContent(),/5 days · 5 meals per entry/);
        assert.match(await row(0).locator('[data-meal-editor-summary]').textContent(),/5 meals · 8 servings \(1.6 per meal\)/);
        // Jump across a week boundary: intervening dates are included even when
        // the mouse moves too quickly to emit an event over every individual cell.
        await drag(0,'2026-10-10','2026-10-13');
        assert.equal((await selected(0)).length,9);
        await drag(0,'2026-10-13','2026-10-08');
        assert.deepEqual(await selected(0),['2026-10-05','2026-10-06','2026-10-07'],'Dragging across a fully selected range clears it');
        await move(day(0,'2026-10-15'));await page.mouse.down();
        await move(day(0,'2026-10-12'));await move(day(0,'2026-10-14'));await page.mouse.up();
        assert.deepEqual(await selected(0),['2026-10-05','2026-10-06','2026-10-07','2026-10-14','2026-10-15']);
        await day(0,'2026-10-20').click();assert((await selected(0)).includes('2026-10-20'));
        await day(0,'2026-10-20').click();assert(!(await selected(0)).includes('2026-10-20'));
        await day(0,'2026-10-20').focus();await page.keyboard.press('Space');
        assert((await selected(0)).includes('2026-10-20'));
        await page.keyboard.press('Enter');assert(!(await selected(0)).includes('2026-10-20'));
        // Release outside the calendar, then hover another date without pressing.
        await move(day(0,'2026-10-21'));await page.mouse.down();await move(day(0,'2026-10-22'));
        await page.mouse.move(20,20);await page.mouse.up();const stopped=await selected(0);
        await move(day(0,'2026-10-24'));assert.deepEqual(await selected(0),stopped);
        await dialog.locator('[data-meal-editor-add]').click();await ready();
        await row(1).locator('[name="recipe_url"]').selectOption('recipe://soup');
        await row(1).locator('[data-meal-editor-customize]').click();
        await editor(1).getByRole('button',{name:'Select days',exact:true}).click();
        await drag(1,'2026-10-27','2026-11-02');
        assert.deepEqual(await selected(1),[...stopped,'2026-10-27','2026-10-28','2026-10-29','2026-10-30','2026-10-31','2026-11-01','2026-11-02']);
        assert.deepEqual(await selected(0),stopped,'The other meal keeps its dates');
        await editor(0).locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
        await move(day(0,'2026-10-25'));await page.mouse.down();
        await editor(1).locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
        await move(day(1,'2026-10-20'));await page.mouse.up();
        assert(!(await selected(1)).includes('2026-10-20'),'A drag cannot spill into another editor');
        const artifacts=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
        if(artifacts){fs.mkdirSync(artifacts,{recursive:true});await page.screenshot({path:path.join(artifacts,'meal-calendar-drag.png')});}
        // Date selection must be reflected in the actual bulk payload and stored meals.
        const expected=await selected(1);
        await dialog.locator('[data-meal-batch-save]').click();await dialog.waitFor({state:'hidden'});
        const saved=await (await context.request.get(base+'/api/meal-plan?recipe_url=recipe://soup')).json();
        assert.deepEqual(saved.meals.map(meal=>meal.date).sort(),expected);
        // Fresh recipe-less editor: dragging counts as configuring a draft.
        await page.getByRole('button',{name:'Add Meals',exact:true}).click();await ready();
        await editor(0).getByRole('button',{name:'Select days',exact:true}).click();
        await drag(0,'2026-10-06','2026-10-08');
        assert(await dialog.locator('[data-meal-batch-save]').isDisabled(),'Shared calendar alone does not create a blank recipe');
        // Regression: the first drag from an already selected Sep 25 must
        // select Sep 25–27, without deselecting the anchor on mouse down.
        for (const date of await selected(0)) await day(0,date).click();
        await editor(0).getByRole('button',{name:'Previous month',exact:true}).click();
        await day(0,'2026-09-25').click();
        await editor(0).locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
        await move(day(0,'2026-09-25'));await page.mouse.down();
        assert.deepEqual(await selected(0),['2026-09-25']);
        await move(day(0,'2026-09-27'));await page.mouse.up();
        assert.deepEqual(await selected(0),['2026-09-25','2026-09-26','2026-09-27']);
        if(artifacts) await page.screenshot({path:path.join(artifacts,'selected-start-range.png')});
        await row(0).locator('[name="recipe_url"]').selectOption('recipe://rice');
        // The opposite gesture clears a selected range, including both endpoints
        // across the month boundary, without changing the selection on mouse down.
        await day(0,'2026-09-25').click();
        await drag(0,'2026-09-27','2026-10-09');
        assert.equal((await selected(0)).length,14);
        if(artifacts) await page.screenshot({path:path.join(artifacts,'range-before-clear.png')});
        await move(day(0,'2026-10-09'));await page.mouse.down();
        assert.equal((await selected(0)).length,14);
        await move(day(0,'2026-10-08'));
        assert.equal((await selected(0)).length,12);
        await move(day(0,'2026-10-02'));
        assert.equal((await selected(0)).length,6);
        await move(day(0,'2026-09-26'));await page.mouse.up();
        assert.deepEqual(await selected(0),[],'Oct 9 back to Sep 26 clears the whole selected range');
        assert.match(await editor(0).locator('.meal-schedule-days').textContent(),/Select dates to build your schedule/);
        assert.match(await dialog.locator('[data-meal-batch-help]').textContent(),/1 recipe · 0 meals · 0 servings/);
        if(artifacts) await page.screenshot({path:path.join(artifacts,'range-after-clear.png')});
        await dialog.locator('[data-meal-batch-save]').click();
        assert(await dialog.isVisible(),'An empty schedule stays open for correction');
        assert.match(await dialog.locator('[data-meal-shared-error]').textContent(),/Select at least one date/);
        await drag(0,'2026-09-25','2026-09-27');
        await dialog.locator('[data-meal-batch-save]').click();await dialog.waitFor({state:'hidden'});
        const rice=await (await context.request.get(base+'/api/meal-plan?recipe_url=recipe://rice')).json();
        assert.deepEqual(rice.meals.map(meal=>meal.date).sort(),['2026-09-25','2026-09-26','2026-09-27']);
        assert.deepEqual(errors,[]);

        const mobile=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
        await mobile.addCookies([cookie]);const phone=await mobile.newPage();await phone.goto(base+'/editor-qa');
        await phone.getByRole('button',{name:'Add Meals',exact:true}).tap();
        await phone.getByRole('button',{name:'Select days',exact:true}).tap();
        const touchDay=phone.locator('[data-schedule-action="date"][data-date="2026-10-07"]');
        await touchDay.tap();assert.equal(await touchDay.getAttribute('aria-pressed'),'true');
        await touchDay.tap();assert.equal(await touchDay.getAttribute('aria-pressed'),'false');
        assert.equal(await phone.locator('.meal-schedule-calendar-grid').evaluate(e=>getComputedStyle(e).touchAction),'auto');
        console.log('PASS: selected-anchor extension, selected-range clearing, reverse previews, click toggles, row/month boundaries, outside release, independent meals, stored dates, keyboard and touch');
    } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
