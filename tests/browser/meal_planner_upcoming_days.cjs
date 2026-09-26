const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Test production controls with isolated real APIs.
    // Flow: one meal -> fill upcoming days -> preview four portions -> apply -> save.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1200}});
        await context.addCookies([cookie]);
        for (const name of ['Nate','Gary']) assert.equal((await context.request.post(base+'/api/meal-plan/members',{data:{name}})).status(),201);
        const page = await context.newPage(), errors = [], posts = [];
        page.on('pageerror', error => errors.push(error.stack));
        page.on('console', message => {if (['error','warning'].includes(message.type())) errors.push(message.text());});
        page.on('request', request => {if (request.method()==='POST' && request.url().endsWith('/batches/bulk')) posts.push(request.postDataJSON());});
        await page.goto(base+'/editor-qa');
        assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
        assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
        const dialog=page.locator('#mealPlannerDialog'), shared=dialog.locator('[data-meal-shared-form]');
        const row=index=>dialog.locator('[data-meal-editor]').nth(index);
        const amount=row(0).locator('[data-meal-recipe-servings]');
        const box=row(0).locator('[data-meal-distribution]');
        const preview=box.locator('[data-meal-distribution-preview]');
        const proposed=box.locator('[data-meal-distribution-meals] li');
        const apply=box.locator('[data-meal-distribution-apply]');
        const calendarPreview=shared.locator('.meal-schedule-dates[data-distribution-preview]');
        const selectedDates=locator=>locator.locator('[data-schedule-action="date"][aria-pressed="true"]').evaluateAll(nodes=>nodes.map(node=>node.dataset.date));
        const draftSnapshot=()=>dialog.evaluate(element=>JSON.stringify({
            shared:element.mealPlanScheduleState.panel.draft,
            entries:element.mealPlanScheduleState.entries.map(entry=>({draft:entry.panel?.draft,amount:entry.servingsPerMeal,expanded:entry.expanded}))
        }));
        const calendarLayout=()=>shared.evaluate(element=>{
            const rect=selector=>{
                const {x,y,width,height}=element.querySelector(selector).getBoundingClientRect();
                return {x,y,width,height};
            };
            return {dates:rect('.meal-schedule-dates'),meals:rect('.meal-schedule-meals'),
                scrollTop:element.closest('dialog').scrollTop};
        });
        const assertBoundedPreview=async locator=>{
            const bounds=await locator.boundingBox();
            assert(bounds.width<=640,`Preview must use the normal calendar width, got ${bounds.width}`);
            assert(await locator.evaluate(element=>element.scrollHeight<=element.clientHeight+1),'The normal calendar must have no nested scrolling');
            assert.equal(await locator.locator('[data-schedule-action="date"]').count(),42);
            assert(await locator.getByRole('button',{name:'Previous month',exact:true}).isVisible());
            assert(await locator.getByRole('button',{name:'Next month',exact:true}).isVisible());
            assert.equal(await locator.locator('.meal-schedule-distribution-heading, .meal-schedule-distribution-day').count(),0);
        };
        const save=dialog.locator('[data-meal-batch-save]');
        const open=async()=>{
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
            await shared.getByRole('button',{name:'One day',exact:true}).click();
        };
        const screenshot=async name=>{
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}
        };
        await open();
        await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
        await shared.locator('[data-schedule-field="single-date"]').fill('2026-09-25');
        await shared.locator('[data-schedule-field="meal"][data-meal="dinner"]').uncheck();
        await shared.locator('[data-schedule-field="meal"][data-meal="breakfast"]').check();
        await shared.getByRole('button',{name:'By family member',exact:true}).click();
        for (const cell of await shared.locator('[data-schedule-field="family"][data-meal="breakfast"]').all()) await cell.fill('0.5');
        await amount.fill('1');await row(0).locator('[data-meal-editor-customize]').click();
        await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        assert.equal(await proposed.count(),4);
        assert.match(await proposed.first().textContent(),/Sep 25, 2026 · breakfast · 1 serving$/);
        assert.match(await proposed.last().textContent(),/Sep 28, 2026 · breakfast · 1 serving$/);
        assert.match(await preview.textContent(),/4 meals across 4 days · 4 servings used · 0 remaining/);
        assert.equal(await save.textContent(),'Save 1 Meal','Preview leaves the real plan unchanged');
        const beforeHover=await draftSnapshot();
        await apply.hover();
        assert(await calendarPreview.isVisible());
        await assertBoundedPreview(calendarPreview);
        assert.deepEqual(await selectedDates(calendarPreview),['2026-09-25','2026-09-26','2026-09-27','2026-09-28']);
        assert.equal((await calendarPreview.locator('[data-date="2026-09-25"]').textContent()).trim(),'25');
        assert.match(await shared.locator('[data-day-summary="2026-09-25"]').textContent(),/Breakfast: 1/);
        assert.equal(await shared.locator('[data-schedule-day]').count(),4);
        assert(await shared.locator('.meal-schedule-dates').isVisible());
        assert.equal(await draftSnapshot(),beforeHover);assert.equal(await save.textContent(),'Save 4 Meals');assert.equal(posts.length,0);
        await page.mouse.move(0,0);
        assert(await calendarPreview.isHidden());assert(await shared.locator('.meal-schedule-dates').isVisible());
        assert.equal(await draftSnapshot(),beforeHover);assert.equal(await save.textContent(),'Save 1 Meal');
        assert.equal(await shared.locator('[data-schedule-day]').count(),1);
        // Tab back from Cancel to Apply, then dismiss only the preview with Escape.
        await apply.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
        assert(await calendarPreview.isVisible());
        await calendarPreview.scrollIntoViewIfNeeded();assert(await calendarPreview.isVisible());await screenshot('distribution-preview-desktop.png');
        await page.keyboard.press('Escape');assert(await calendarPreview.isHidden());assert(await dialog.isVisible());
        await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
        assert(await calendarPreview.isVisible());
        await page.keyboard.press('Tab');assert(await calendarPreview.isHidden());
        await dialog.evaluate(element=>{element.scrollTop=0;});await screenshot('upcoming-days-preview-desktop.png');
        await page.setViewportSize({width:390,height:844});
        await box.scrollIntoViewIfNeeded();
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        assert(await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).isEnabled());
        await screenshot('upcoming-days-preview-mobile.png');
        await apply.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
        assert(await calendarPreview.isVisible());
        await calendarPreview.scrollIntoViewIfNeeded();
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        await assertBoundedPreview(calendarPreview);
        await screenshot('distribution-focus-mobile.png');
        await page.keyboard.press('Tab');assert(await calendarPreview.isHidden());
        await page.setViewportSize({width:1440,height:1200});
        await box.getByRole('button',{name:'Cancel',exact:true}).click();
        assert.equal(await save.textContent(),'Save 1 Meal');
        for (const cell of await shared.locator('[data-schedule-field="family"][data-meal="breakfast"]').all()) await cell.fill('0.75');
        await amount.fill('1.5');await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        assert.equal(await proposed.count(),3);
        assert.match(await preview.textContent(),/Last meal: 1 serving \(smaller portion\)/);
        await apply.hover();
        assert.match(await shared.locator('[data-day-total="2026-09-27"]').textContent(),/1 servings/);
        await amount.fill('');assert(await box.getByRole('button',{name:'Apply distribution',exact:true}).isDisabled());
        await amount.fill('1');
        for (const cell of await shared.locator('[data-schedule-field="family"][data-meal="breakfast"]').all()) await cell.fill('0.5');
        assert.equal(await amount.inputValue(),'1','Changing shared portions after hover must not redirect typing into the recipe amount');
        assert.equal(await proposed.count(),4);
        await box.getByRole('button',{name:'Apply distribution',exact:true}).click();
        assert.equal(await save.textContent(),'Save 4 Meals');assert.equal(posts.length,0);
        assert.equal(await row(0).locator('[data-meal-editor-form]').count(),0,'The previous custom editor is removed');
        assert(await row(0).locator('[data-meal-override-container]').isHidden());
        assert.equal(await dialog.locator('[data-meal-editor-form]:visible').count(),1);
        assert.deepEqual(await shared.locator('[data-schedule-action="date"][aria-pressed="true"]').evaluateAll(nodes=>nodes.map(node=>node.dataset.date)),['2026-09-25','2026-09-26','2026-09-27','2026-09-28']);
        assert.equal(await shared.locator('.is-yield-short').count(),0);
        assert.match(await row(0).locator('[data-meal-yield-remaining]').textContent(),/All servings from one full recipe are planned/);
        await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();await screenshot('upcoming-days-applied-desktop.png');
        await page.setViewportSize({width:390,height:844});
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();await screenshot('upcoming-days-applied-mobile.png');
        await page.setViewportSize({width:1440,height:1200});
        // Applying again must be idempotent: do not append another full recipe.
        await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        assert.equal(await proposed.count(),4);
        const selectedBefore=await shared.locator('[data-schedule-action="date"][aria-pressed="true"]').evaluateAll(nodes=>nodes.map(node=>node.dataset.date));
        await apply.scrollIntoViewIfNeeded();await page.mouse.move(0,0);
        const beforeCalendarHover=await calendarLayout();
        for(let attempt=0;attempt<3;attempt++){
            await apply.hover();assert(await calendarPreview.isVisible());
            assert.deepEqual(await calendarLayout(),beforeCalendarHover,'Hover must preserve calendar size, surrounding controls, and scroll position');
            assert(await shared.locator('.meal-schedule-dates').isVisible());
            await page.mouse.move(0,0);assert(await calendarPreview.isHidden());
            assert.deepEqual(await calendarLayout(),beforeCalendarHover);
        }
        // Use keyboard focus to inspect the preview without holding the pointer on Apply.
        await apply.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
        await calendarPreview.evaluate(element=>element.scrollIntoView({block:'center'}));await screenshot('distribution-stable-calendar-desktop.png');
        await page.keyboard.press('Escape');
        await page.setViewportSize({width:390,height:844});
        await apply.scrollIntoViewIfNeeded();
        const beforeMobileHover=await calendarLayout();
        await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
        assert(await calendarPreview.isVisible());
        assert.deepEqual(await calendarLayout(),beforeMobileHover,'Keyboard preview must preserve the mobile calendar layout');
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        await calendarPreview.evaluate(element=>element.scrollIntoView({block:'center'}));await screenshot('distribution-stable-calendar-mobile.png');
        await page.keyboard.press('Escape');
        await page.setViewportSize({width:1440,height:1200});
        assert.deepEqual(await shared.locator('[data-schedule-action="date"][aria-pressed="true"]').evaluateAll(nodes=>nodes.map(node=>node.dataset.date)),selectedBefore);
        await box.getByRole('button',{name:'Apply distribution',exact:true}).click();
        const response=page.waitForResponse(res=>res.url().endsWith('/batches/bulk')&&res.request().method()==='POST');
        await save.click();const saved=await(await response).json();await dialog.waitFor({state:'hidden'});
        assert.equal(saved.ok,true);assert.equal(saved.meals.length,4);
        assert(saved.meals.every(meal=>meal.planned_servings===1 && meal.member_portions.every(part=>part.servings===0.5)));
        const stored=await(await context.request.get(base+'/api/meal-plan?recipe_url=recipe://soup')).json();
        assert.equal(stored.meals.length,4);assert.equal(stored.meals.reduce((sum,meal)=>sum+meal.planned_servings,0),4);
        // Reference screenshot: ordinary September calendar, green dates 26–29,
        // Split recipe yield, proposed day cards, and Save 4 Meals on hover.
        await open();await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
        await shared.locator('[data-schedule-field="single-date"]').fill('2026-09-26');
        await shared.locator('[data-schedule-field="meal"][data-meal="dinner"]').uncheck();
        await shared.locator('[data-schedule-field="meal"][data-meal="breakfast"]').check();
        await shared.getByRole('button',{name:'Select days',exact:true}).click();
        // Each date mode retains its own selection. Choose September explicitly.
        await shared.locator('[data-schedule-action="date"][data-date="2026-10-05"]').click();
        await shared.getByRole('button',{name:'Previous month',exact:true}).click();
        await shared.locator('[data-schedule-action="date"][data-date="2026-09-26"]').click();
        await amount.fill('1');await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        await apply.scrollIntoViewIfNeeded();await page.mouse.move(0,0);
        const referenceDraft=await draftSnapshot(), referenceLayout=await calendarLayout();
        await apply.hover();
        assert.deepEqual(await selectedDates(calendarPreview),['2026-09-26','2026-09-27','2026-09-28','2026-09-29']);
        assert.deepEqual(await calendarLayout(),referenceLayout);
        assert.equal(await shared.getByRole('button',{name:'Split recipe yield',exact:true}).getAttribute('aria-pressed'),'true');
        assert.equal(await shared.locator('[data-schedule-day]').count(),4);
        assert.equal(await save.textContent(),'Save 4 Meals');
        assert.match(await row(0).locator('[data-meal-yield-remaining]').textContent(),/All servings from one full recipe are planned/);
        assert.equal(await draftSnapshot(),referenceDraft);
        await assertBoundedPreview(calendarPreview);
        await calendarPreview.evaluate(element=>element.scrollIntoView({block:'center'}));
        await screenshot('distribution-reference-desktop.png');
        await page.mouse.move(0,0);
        assert.equal(await save.textContent(),'Save 1 Meal');
        assert.deepEqual(await selectedDates(shared),['2026-09-26']);
        assert.equal(await draftSnapshot(),referenceDraft);
        await dialog.locator('[data-meal-batch-footer]').getByRole('button',{name:'Cancel',exact:true}).click();
        // A second entry reserves servings from the same recipe's eight-serving yield.
        await open();await row(0).locator('[name="recipe_url"]').selectOption('recipe://bread');await amount.fill('1');
        await dialog.locator('[data-meal-editor-add]').click();
        await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
        await row(1).locator('[data-meal-recipe-servings]').fill('2');
        await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        assert.match(await box.locator('[data-meal-distribution-budget]').textContent(),/2 already assigned in other entries; 6 available here/);
        assert.equal(await proposed.count(),6);assert.match(await preview.textContent(),/6 servings used · 0 remaining/);
        // Keeping a fixed amount still operates only on selected slots.
        await box.locator('[data-meal-distribution-mode][value="keep"]').check();
        assert.equal(await proposed.count(),1);assert.match(await preview.textContent(),/1 serving used · 5 remaining/);
        assert.match(await box.locator('[data-meal-distribution-keep]').textContent(),/Keep 1 serving per meal/);
        // Multiple entries still need an independent distribution for each recipe.
        await shared.locator('[data-schedule-field="single-date"]').fill('2026-10-29');
        await box.locator('[data-meal-distribution-mode][value="upcoming"]').check();
        const beforeMultiHover=await draftSnapshot();
        await apply.hover();assert(await calendarPreview.isVisible());
        await assertBoundedPreview(calendarPreview);
        assert.equal((await selectedDates(calendarPreview)).length,6);
        assert.deepEqual(await calendarPreview.locator('.meal-schedule-calendar-heading strong').allTextContents(),['October 2026']);
        assert.match(await calendarPreview.locator('[data-date="2026-11-03"]').getAttribute('aria-label'),/Nov 3/);
        assert.equal(await shared.locator('[data-schedule-day]').count(),6);
        assert.equal(await draftSnapshot(),beforeMultiHover);
        await box.getByRole('button',{name:'Apply distribution',exact:true}).click();
        assert(await calendarPreview.isHidden());
        assert(await row(0).locator('[data-meal-editor-form]').isVisible());
        assert.equal(await shared.locator('[data-schedule-field="single-date"]').inputValue(),'2026-10-29');
        assert.match(await row(1).locator('[data-meal-editor-summary]').textContent(),/1 meal · 2 servings/);
        // Once this recipe has an open custom plan, its own calendar previews the change.
        await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        const customPreview=row(0).locator('[data-meal-editor-form] .meal-schedule-dates[data-distribution-preview]');
        const beforeCustomHover=await draftSnapshot();
        await apply.hover();assert(await customPreview.isVisible());assert(await calendarPreview.isHidden());
        assert.equal(await draftSnapshot(),beforeCustomHover);
        await box.getByRole('button',{name:'Cancel',exact:true}).click();assert(await customPreview.isHidden());
        assert.equal(await draftSnapshot(),beforeCustomHover);
        assert.deepEqual(errors,[]);
        console.log('PASS: one serving per day, preview/cancel/apply, smaller final portion, invalid input, selected dates, family portions, repeat apply, save/reload, shared recipe budget, old modes, desktop/mobile, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
