const {customPlan} = require('./meal_planner_test_helpers.cjs');
const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Exercise production markup, controller and APIs.
    // Flow: shared portions -> add/remove recipes -> distribute -> save/reopen.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1100}});
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
        const row=i=>dialog.locator('[data-meal-editor]').nth(i);
        const recipe=i=>row(i).locator('[name="recipe_url"]');
        const amount=i=>row(i).locator('[data-meal-recipe-servings]');
        const household=meal=>shared.locator(`[data-schedule-field="household"][data-meal="${meal}"]`);
        const save=dialog.locator('[data-meal-batch-save]');
        const open=async()=>{
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
            await recipe(0).selectOption('recipe://soup');
        };
        const cancel=()=>dialog.locator('[data-meal-batch-footer]').getByRole('button',{name:'Cancel',exact:true}).click();
        const add=async url=>{await dialog.locator('[data-meal-editor-add]').click();await recipe(1).selectOption(url);};
        const draft=()=>dialog.evaluate(element=>JSON.stringify(element.mealPlanScheduleState.panel.draft));
        const screenshot=async name=>{
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}
        };
        await open();
        assert(await amount(0).isHidden());
        assert.equal(await shared.locator('[data-schedule-servings-heading]').textContent(),'Servings per meal');
        await household('dinner').fill('2');
        await dialog.locator('[data-meal-editor-add]').click();
        assert(await amount(0).isHidden(),'An empty recipe row does not expose a second servings control');
        assert.equal(await household('dinner').inputValue(),'2');
        await recipe(1).selectOption('recipe://bread');
        assert.equal(await amount(0).inputValue(),'2');assert.equal(await amount(1).inputValue(),'1');
        assert.equal(await household('dinner').inputValue(),'2','Adding a recipe retains the entered household total');
        assert.equal(await shared.locator('[data-schedule-servings-heading]').textContent(),'Total servings per meal');
        assert.equal(await dialog.locator('[data-meal-recipe-amount]:visible').count(),2);
        assert.match(await row(0).locator('[data-meal-recipe-amount]').textContent(),/This recipe’s servings per meal/);
        await save.click();assert.equal(posts.length,0);
        assert.match(await row(0).locator('[data-meal-editor-error]').textContent(),/exceed.*total/);
        await household('dinner').fill('3');
        await amount(0).fill('1.5');await amount(1).fill('0.75');
        await dialog.evaluate(element=>{element.scrollTop=0;});await screenshot('servings-multiple-desktop.png');
        await row(1).locator('[data-meal-editor-remove]').click();
        assert(await amount(0).isHidden());assert.equal(await household('dinner').inputValue(),'1.5');
        await add('recipe://bread');assert.equal(await amount(0).inputValue(),'1.5');
        await amount(1).fill('0.5');await row(0).locator('[data-meal-editor-remove]').click();
        assert(await amount(0).isHidden());assert.equal(await household('dinner').inputValue(),'0.5');
        await cancel();

        // Unequal meal amounts and an individually adjusted day survive both transitions.
        await open();await shared.getByRole('button',{name:'Date range',exact:true}).click();
        await shared.locator('[data-schedule-field="end-date"]').fill('2026-10-06');
        await shared.locator('[data-schedule-field="meal"][data-meal="lunch"]').check();
        await household('lunch').fill('0.5');await household('dinner').fill('1.5');
        const day=shared.locator('[data-schedule-day="2026-10-06"]');
        await day.locator('summary').click();
        await day.locator('[data-schedule-field="day-household"][data-meal="dinner"]').fill('2');
        const before=await draft();
        await add('recipe://bread');assert.equal(await amount(0).inputValue(),'');
        assert.equal(await amount(0).getAttribute('placeholder'),'Varies');
        await row(1).locator('[data-meal-editor-remove]').click();
        const after=JSON.parse(await draft()), previous=JSON.parse(before);
        assert.deepEqual(after.householdDefaults,previous.householdDefaults);
        assert.equal(Number(after.days['2026-10-06'].household.dinner),2);
        assert.deepEqual(after.selectedDates,previous.selectedDates);
        await dialog.getByRole('button',{name:'Fill upcoming days for all',exact:true}).hover();
        const box=dialog.locator('[data-meal-shared-distribution]'), apply=box.locator('[data-meal-shared-distribution-mode="upcoming"]');
        assert.equal(await box.locator('[data-meal-shared-distribution-meals] li').count(),4);
        assert.match(await box.locator('[data-meal-shared-distribution-meals] li').last().textContent(),/dinner · 1.5 servings/);
        const beforeHover=await draft();await apply.hover();
        assert(await shared.locator('[data-distribution-preview]').isVisible());
        assert.equal(await draft(),beforeHover);assert.equal(posts.length,0);
        await page.mouse.move(0,0);assert.equal(await draft(),beforeHover);
        await page.mouse.move(0,0);
        await shared.getByRole('button',{name:'Split recipe yield',exact:true}).click();
        assert(await amount(0).isHidden());
        assert.match(await row(0).locator('[data-meal-yield-remaining]').textContent(),/All servings/);
        await dialog.getByRole('button',{name:'Fill upcoming days for all',exact:true}).hover();
        assert(await apply.isEnabled());await page.mouse.move(0,0);
        await cancel();

        // Family proportions drive upcoming meals and the final partial portion.
        await open();await shared.getByRole('button',{name:'By family member',exact:true}).click();
        const family=shared.locator('[data-schedule-field="family"][data-meal="dinner"]');
        await family.nth(0).fill('0.5');await family.nth(1).fill('1');
        await add('recipe://bread');await row(1).locator('[data-meal-editor-remove]').click();
        assert.equal(await family.nth(0).inputValue(),'0.5');assert.equal(await family.nth(1).inputValue(),'1');
        await family.nth(0).fill('0.75');
        assert.match(await row(0).locator('[data-meal-editor-summary]').textContent(),/1.75 servings/);
        await family.nth(0).fill('0.5');
        await row(0).locator('[data-meal-editor-customize]').click();
        assert(await amount(0).isVisible(),'A custom recipe retains its own servings control');
        await amount(0).fill('2');await customPlan(dialog,0).locator('[data-meal-editor-reset]').click();
        assert(await amount(0).isHidden());assert.equal(await family.nth(0).inputValue(),'0.5');
        await dialog.getByRole('button',{name:'Fill upcoming days for all',exact:true}).hover();
        assert.equal(await box.locator('[data-meal-shared-distribution-meals] li').count(),3);
        assert.match(await box.locator('[data-meal-shared-distribution-preview]').textContent(),/Last meal: 1 serving/);
        await apply.click();assert.equal(await save.textContent(),'Save 3 Meals');
        await shared.locator('.meal-schedule-columns').scrollIntoViewIfNeeded();await screenshot('servings-single-desktop.png');
        await page.setViewportSize({width:390,height:844});
        assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
        await family.first().scrollIntoViewIfNeeded();await screenshot('servings-single-mobile.png');
        assert(await amount(0).isHidden());
        const response=page.waitForResponse(res=>res.url().endsWith('/batches/bulk')&&res.request().method()==='POST');
        await save.click();const saved=await(await response).json();assert.equal(saved.ok,true);
        assert.deepEqual(saved.meals.map(meal=>meal.planned_servings),[1.5,1.5,1]);
        assert.deepEqual(saved.meals[0].member_portions.map(part=>part.servings),[0.5,1]);
        await page.reload();await open();
        assert.equal(await household('dinner').inputValue(),'1.5','The preference keeps the normal portion, not the smaller final meal');
        assert.deepEqual(errors,[]);
        console.log('PASS: one visible control, contextual labels, empty rows, preserving meal/day/family portions, both removal directions, over-budget validation, custom controls, yield split, hover, partial distribution, preferences, desktop/mobile');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
