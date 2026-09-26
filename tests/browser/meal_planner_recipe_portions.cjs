const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Exercise production controls with isolated APIs.
    // Flow: family meal -> inline recipe amounts -> shared date changes -> save/reload.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1200}});
        await context.addCookies([cookie]);
        for (const name of ['Nate','Gary']) assert.equal((await context.request.post(base+'/api/meal-plan/members',{data:{name}})).status(),201);
        const page = await context.newPage(), errors = [], posts = [];
        page.on('pageerror', e=>errors.push(e.message));
        page.on('console', m=>{if (['error','warning'].includes(m.type())) errors.push(m.text());});
        page.on('request', r=>{if (r.method()==='POST'&&r.url().endsWith('/batches/bulk')) posts.push(r.postDataJSON());});
        await page.goto(base+'/editor-qa');
        assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
        assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
        const dialog=page.locator('#mealPlannerDialog'),shared=dialog.locator('[data-meal-shared-form]');
        const row=i=>dialog.locator('[data-meal-editor]').nth(i),amount=i=>row(i).locator('[data-meal-recipe-servings]');
        const save=dialog.locator('[data-meal-batch-save]');
        const screenshot=async name=>{const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}};
        await page.getByRole('button',{name:'Add Meals',exact:true}).click();
        await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
        await row(0).locator('[name="recipe_url"]').selectOption('recipe://bread');
        await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://soup');
        await shared.getByRole('button',{name:'By family member',exact:true}).click();
        assert.equal(await amount(0).inputValue(),'1');assert.equal(await amount(1).inputValue(),'1');
        await amount(0).fill('1.5');assert.equal(await amount(1).inputValue(),'0.5');
        assert.equal(await dialog.locator('[data-meal-editor-form]').count(),1,'Inline amounts retain one shared schedule');
        assert.match(await row(0).locator('[data-meal-portions-help]').textContent(),/Nate: 0.75 · Gary: 0.75/);
        await shared.getByRole('button',{name:'Date range',exact:true}).click();
        await shared.locator('[data-schedule-field="end-date"]').fill('2026-10-07');
        assert.match(await row(0).locator('[data-meal-editor-summary]').textContent(),/3 days.*4.5 servings/);
        assert.match(await row(1).locator('[data-meal-editor-summary]').textContent(),/3 days.*1.5 servings/);
        assert.match(await dialog.locator('[data-meal-batch-help]').textContent(),/2 recipes · 3 meals · 6 servings/);
        assert.match(await row(0).locator('[data-meal-yield-remaining]').textContent(),/^3.5 servings left/);
        await dialog.evaluate(e=>{e.scrollTop=0;});await screenshot('recipe-portions-desktop.png');
        await page.setViewportSize({width:390,height:844});
        assert(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1));await screenshot('recipe-portions-mobile.png');
        await page.setViewportSize({width:1440,height:1200});
        await row(0).getByRole('button',{name:'Decrease Bread servings per meal',exact:true}).click();
        assert.equal(await amount(0).inputValue(),'1');assert.equal(await amount(1).inputValue(),'1');
        await row(0).getByRole('button',{name:'Increase Bread servings per meal',exact:true}).click();
        assert.equal(await amount(0).inputValue(),'1.5');assert.equal(await amount(1).inputValue(),'0.5');
        await amount(0).fill('');await save.click();assert.equal(posts.length,0);
        await amount(0).fill('2.5');await save.click();assert.equal(posts.length,0);
        assert.match(await row(1).locator('[data-meal-editor-error]').textContent(),/exceed|remain/);
        await row(0).getByRole('button',{name:'Auto split',exact:true}).click();
        assert.equal(await amount(0).inputValue(),'1');assert.equal(await amount(1).inputValue(),'1');
        // Moving between inline amounts and per-person customization must keep
        // the same portions, including while an incomplete input is corrected.
        await amount(0).fill('1.5');await row(0).locator('[data-meal-editor-customize]').click();
        const custom=row(0).locator('[data-meal-editor-form]');
        const family=custom.locator('[data-schedule-field="family"][data-meal="dinner"]');
        assert.equal(await family.first().inputValue(),'0.75');
        await amount(0).fill('');await amount(0).fill('1');
        assert.equal(await family.first().inputValue(),'0.5');
        await row(0).locator('[data-meal-editor-reset]').click();
        await amount(0).fill('1.5');await amount(1).fill('1');await save.click();assert.equal(posts.length,0);
        await amount(1).fill('0.5');
        const response=page.waitForResponse(r=>r.url().endsWith('/batches/bulk')&&r.request().method()==='POST');
        await save.click();const saved=await(await response).json();await dialog.waitFor({state:'hidden'});
        assert.equal(saved.ok,true);assert.equal(posts.length,1);
        assert.deepEqual(saved.batches.map(batch=>batch.batch_servings),[4.5,1.5]);
        for (const [url,perPerson] of [['recipe://bread',0.75],['recipe://soup',0.25]]) {
            const meals=saved.meals.filter(meal=>meal.recipe_url===url);
            assert.equal(meals.length,3);assert(meals.every(meal=>meal.member_portions.every(part=>part.servings===perPerson)));
        }
        await page.reload();
        const stored=await(await context.request.get(base+'/api/meal-plan?recipe_url=recipe://bread')).json();
        assert.deepEqual(stored.meals.map(meal=>meal.planned_servings),[1.5,1.5,1.5]);
        assert.deepEqual(errors,[]);
        console.log('PASS: inline recipe amounts, proportional family portions, live dates/totals/balances, steppers, reset, invalid/over-budget inputs, custom editor continuity, saved/reloaded portions, desktop/mobile');
    } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
