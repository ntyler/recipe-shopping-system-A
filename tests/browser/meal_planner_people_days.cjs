const {selectDates} = require('./meal_planner_test_helpers.cjs');
const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available; use the repository's Playwright workflow.
    // Flow: third option -> portions per person -> future days -> apply -> save/reload.
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
        const row=dialog.locator('[data-meal-editor]').first(), amount=row.locator('[data-meal-recipe-servings]');
        const box=dialog.locator('[data-meal-shared-distribution]'), preview=box.locator('[data-meal-shared-distribution-preview]');
        const proposed=box.locator('[data-meal-shared-distribution-meals] li'), apply=box.locator('[data-meal-shared-distribution-mode="upcoming"]');
        const save=dialog.locator('[data-meal-batch-save]');
        const open=async()=>{
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
            await row.locator('[name="recipe_url"]').selectOption('recipe://bread');
        };
        const third=async()=>{
            await apply.hover();
            assert.equal(await box.locator('[data-meal-shared-distribution-mode="people"]').count(),0);
        };
        const screenshot=async name=>{
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}
        };
        await open();await shared.getByRole('button',{name:'Split recipe yield',exact:true}).click();
        assert.equal(await box.locator('[data-meal-shared-distribution-mode]').count(),2);
        await selectDates(shared, ['2026-09-26']);
        await shared.getByRole('button',{name:'By family member',exact:true}).click();
        const portions=shared.locator('[data-schedule-field="family"][data-meal="dinner"]');
        for(const cell of await portions.all()) await cell.fill('1');
        assert(await amount.isHidden()); // The shared family controls are the only portion inputs.
        await third();assert.equal(await proposed.count(),4);assert(await apply.isEnabled());
        assert.match(await preview.textContent(),/4 meals across 4 days · 8 servings used · 0 remaining/);
        assert.match(await proposed.first().textContent(),/Sep 26, 2026 · dinner · 2 servings · Nate: 1 serving · Gary: 1 serving/);
        assert.match(await proposed.last().textContent(),/Sep 29, 2026/);
        assert.equal(await save.textContent(),'Save 4 Meals');assert.equal(posts.length,0);
        await dialog.evaluate(element=>{element.scrollTop=0;});await screenshot('people-days-preview-desktop.png');
        await page.setViewportSize({width:390,height:844});await box.scrollIntoViewIfNeeded();
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        await screenshot('people-days-preview-mobile.png');await page.setViewportSize({width:1440,height:1200});
        await page.mouse.move(0,0);assert.equal(await save.textContent(),'Save 1 Meal');
        await third();await apply.click();
        assert.equal(await save.textContent(),'Save 4 Meals');assert.equal(posts.length,0);
        assert.equal(await row.locator('[data-meal-editor-form]').count(),0);
        assert(await row.locator('[data-meal-override-container]').isHidden());
        assert.equal(await dialog.locator('[data-meal-editor-form]:visible').count(),1);
        assert.deepEqual(await shared.locator('[data-schedule-action="date"][aria-pressed="true"]').evaluateAll(nodes=>nodes.map(node=>node.dataset.date)),['2026-09-26','2026-09-27','2026-09-28','2026-09-29']);
        await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();await screenshot('people-days-applied-desktop.png');
        await third();assert.equal(await proposed.count(),4);await apply.click();
        const response=page.waitForResponse(res=>res.url().endsWith('/batches/bulk')&&res.request().method()==='POST');
        await save.click();const saved=await(await response).json();await dialog.waitFor({state:'hidden'});
        assert.equal(saved.ok,true);assert.equal(saved.meals.length,4);
        assert(saved.meals.every(meal=>meal.planned_servings===2&&meal.member_portions.length===2&&meal.member_portions.every(part=>part.servings===1)));
        await page.reload();
        const stored=await(await context.request.get(base+'/api/meal-plan?recipe_url=recipe://bread')).json();
        assert.deepEqual(stored.meals.map(meal=>meal.date).sort(),['2026-09-26','2026-09-27','2026-09-28','2026-09-29']);
        assert.equal(stored.meals.reduce((sum,meal)=>sum+meal.planned_servings,0),8);
        await open();await shared.getByRole('button',{name:'By family member',exact:true}).click();
        for(const cell of await portions.all()) await cell.fill('1.5');
        await third();assert.equal(await proposed.count(),3);
        assert.match(await preview.textContent(),/Last meal: 2 servings \(smaller portion\)/);
        assert.match(await proposed.last().textContent(),/Nate: 1 serving · Gary: 1 serving/);
        await portions.first().fill('');assert.equal(await apply.getAttribute('aria-disabled'),'true');
        await portions.first().fill('1.5');assert(await apply.isEnabled());
        const attendance=shared.locator('[data-schedule-field="family-enabled"][data-meal="dinner"]');
        await attendance.last().uncheck();await third();assert.equal(await proposed.count(),6);
        assert(!(await proposed.first().textContent()).includes('Gary'));
        assert.deepEqual(errors,[]);
        console.log('PASS: third option, per-person portions, future dates, desktop/mobile, preview/cancel/apply, repeat apply, saved/reloaded meals, partial final meal, invalid portions, excluded people, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
