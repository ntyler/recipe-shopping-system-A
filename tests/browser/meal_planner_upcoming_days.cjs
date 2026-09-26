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
        page.on('pageerror', error => errors.push(error.message));
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
        const save=dialog.locator('[data-meal-batch-save]');
        const open=async()=>{
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
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
        await dialog.evaluate(element=>{element.scrollTop=0;});await screenshot('upcoming-days-preview-desktop.png');
        await page.setViewportSize({width:390,height:844});
        await box.scrollIntoViewIfNeeded();
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        assert(await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).isEnabled());
        await screenshot('upcoming-days-preview-mobile.png');
        await page.setViewportSize({width:1440,height:1200});
        await box.getByRole('button',{name:'Cancel',exact:true}).click();
        assert.equal(await save.textContent(),'Save 1 Meal');
        for (const cell of await shared.locator('[data-schedule-field="family"][data-meal="breakfast"]').all()) await cell.fill('0.75');
        await amount.fill('1.5');await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        assert.equal(await proposed.count(),3);
        assert.match(await preview.textContent(),/Last meal: 1 serving \(smaller portion\)/);
        await amount.fill('');assert(await box.getByRole('button',{name:'Apply distribution',exact:true}).isDisabled());
        await amount.fill('1');
        for (const cell of await shared.locator('[data-schedule-field="family"][data-meal="breakfast"]').all()) await cell.fill('0.5');
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
        await box.getByRole('button',{name:'Apply distribution',exact:true}).click();
        const response=page.waitForResponse(res=>res.url().endsWith('/batches/bulk')&&res.request().method()==='POST');
        await save.click();const saved=await(await response).json();await dialog.waitFor({state:'hidden'});
        assert.equal(saved.ok,true);assert.equal(saved.meals.length,4);
        assert(saved.meals.every(meal=>meal.planned_servings===1 && meal.member_portions.every(part=>part.servings===0.5)));
        const stored=await(await context.request.get(base+'/api/meal-plan?recipe_url=recipe://soup')).json();
        assert.equal(stored.meals.length,4);assert.equal(stored.meals.reduce((sum,meal)=>sum+meal.planned_servings,0),4);
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
        await box.locator('[data-meal-distribution-mode][value="upcoming"]').check();
        await box.getByRole('button',{name:'Apply distribution',exact:true}).click();
        assert(await row(0).locator('[data-meal-editor-form]').isVisible());
        assert.equal(await shared.locator('[data-schedule-field="single-date"]').inputValue(),'2026-10-05');
        assert.match(await row(1).locator('[data-meal-editor-summary]').textContent(),/1 meal · 2 servings/);
        assert.deepEqual(errors,[]);
        console.log('PASS: one serving per day, preview/cancel/apply, smaller final portion, invalid input, selected dates, family portions, repeat apply, save/reload, shared recipe budget, old modes, desktop/mobile, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
