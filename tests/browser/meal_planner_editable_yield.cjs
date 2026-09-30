const {chromium} = require(process.argv[2]);
const {selectDates} = require('./meal_planner_test_helpers.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Flow: Add Meals -> edit/scale Yield -> split/distribute -> Save Meals.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        for (const mobile of [false,true]) {
            const context = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1100},isMobile:mobile,hasTouch:mobile});
            await context.addCookies([cookie]);
            const page = await context.newPage(), errors = [], writes = [];
            page.on('pageerror',error=>errors.push(error.message));
            page.on('console',message=>{if(['error','warning'].includes(message.type()))errors.push(message.text());});
            page.on('request',request=>{if(['POST','PUT','PATCH','DELETE'].includes(request.method()))writes.push(request);});
            await page.goto(base+'/editor-qa');
            assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
            assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
            const dialog=page.locator('#mealPlannerDialog'),shared=dialog.locator('[data-meal-shared-form]');
            const row=index=>dialog.locator('[data-meal-editor]').nth(index);
            const yieldInput=index=>row(index).locator('[data-meal-table-yield]');
            const scale=(index,value)=>row(index).locator(`[data-meal-yield-scale="${value}"]`);
            const portions=index=>row(index).locator('[data-meal-recipe-servings]');
            const activate=async button=>mobile?button.tap():button.click();
            const open=async()=>{
                await page.getByRole('button',{name:'Add Meals',exact:true}).click();
                await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
            };
            const add=async recipe=>{
                await dialog.locator('[data-meal-editor-add]').click();
                await dialog.locator('[data-meal-editor]').last().locator('[name="recipe_url"]').selectOption(recipe);
            };
            const payloads=()=>dialog.evaluate(el=>el.mealPlanScheduleState.entries.map(entry=>MealPlanSchedule.payload(mealPlannerRecipeDraft(el.mealPlanScheduleState,entry))));
            await open();
            assert(await yieldInput(0).isDisabled());
            await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
            assert.equal(await yieldInput(0).inputValue(),'4');
            const original=await payloads();
            await activate(scale(0,2));assert.equal(await yieldInput(0).inputValue(),'8');
            assert.equal(await scale(0,2).getAttribute('aria-pressed'),'true');
            assert.deepEqual(await payloads(),original,'Manual meal portions stay unchanged when the yield budget changes');
            await yieldInput(0).fill('9.5');await yieldInput(0).press('Enter');
            assert.equal(await yieldInput(0).inputValue(),'9.5');
            await activate(row(0).locator('[data-meal-yield-step="1"]'));assert.equal(await yieldInput(0).inputValue(),'10.5');
            await activate(row(0).locator('[data-meal-yield-step="-1"]'));assert.equal(await yieldInput(0).inputValue(),'9.5');
            await activate(scale(0,3));assert.equal(await yieldInput(0).inputValue(),'12');
            await activate(scale(0,1));assert.equal(await yieldInput(0).inputValue(),'4');
            for(const invalid of ['0','-1','','4001']) {
                await yieldInput(0).fill(invalid);await yieldInput(0).press('Tab');
                assert.equal(await yieldInput(0).inputValue(),'4');
                assert.match(await row(0).locator('[data-meal-yield-error]').textContent(),/Yield has not changed/);
                assert.deepEqual(await payloads(),original);
            }
            await activate(scale(0,1));assert(await row(0).locator('[data-meal-yield-error]').isHidden());
            const dates=mobile?['2026-10-12','2026-10-13','2026-10-14','2026-10-15']:['2026-10-05','2026-10-06','2026-10-07','2026-10-08'];
            await selectDates(shared,dates);await add('recipe://salad');
            await activate(dialog.locator('[data-meal-shared-portions-auto]'));
            assert.equal(await portions(0).inputValue(),'1');assert.equal(await portions(1).inputValue(),'0.5');
            if(mobile)await scale(0,2).tap();else {
                await scale(0,1).focus();await page.keyboard.press('Tab');
                assert(await scale(0,2).evaluate(el=>el===document.activeElement&&el.matches(':focus-visible')&&getComputedStyle(el).outlineStyle!=='none'));
                await page.keyboard.press('Space');
            }
            await activate(scale(1,3));
            assert.equal(await portions(0).inputValue(),'2');assert.equal(await portions(1).inputValue(),'1.5');
            assert.deepEqual(await dialog.locator('[data-meal-table-planned]').allTextContents(),['8 / 8','6 / 6']);
            assert.equal(await shared.locator('.is-yield-short').count(),0);
            assert.equal(writes.length,0,'Yield changes and splitting only affect the draft');
            await dialog.evaluate(el=>{el.scrollTop=0;});
            assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
            const controls=await row(0).locator('.app-meal-yield-controls button').evaluateAll(buttons=>buttons.map(button=>{
                const box=button.getBoundingClientRect();return {width:box.width,height:box.height};
            }));
            assert(controls.every(box=>box.width>=44&&box.height>=44),'Yield controls have touch targets');
            if(!mobile) {
                const stepper=await row(0).locator('.app-meal-yield-stepper').boundingBox();
                const scales=await row(0).locator('.app-meal-yield-scales').boundingBox();
                assert.equal(scales.y,stepper.y,'Yield shortcuts align beside the servings input');
                assert(scales.x>=stepper.x+stepper.width,'Yield shortcuts do not overlap the servings input');
            }
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,`editable-yield-${mobile?'mobile':'desktop'}.png`)});}
            await add('recipe://soup');assert.equal(await yieldInput(2).inputValue(),'8');
            await activate(dialog.locator('[data-meal-shared-portions-auto]'));
            assert.equal(await portions(0).inputValue(),'1');assert.equal(await portions(2).inputValue(),'1');
            await yieldInput(2).fill('12');await yieldInput(2).press('Tab');
            assert.equal(await yieldInput(0).inputValue(),'12');assert.equal(await portions(0).inputValue(),'1.5');
            await activate(scale(2,2));assert.equal(await yieldInput(0).inputValue(),'8');
            const split=await payloads();
            const keep=dialog.locator('[data-meal-shared-distribution-mode="keep"]');
            if(!mobile){await keep.hover();assert.deepEqual(await payloads(),split);await keep.focus();assert.deepEqual(await payloads(),split);}
            await activate(keep);await activate(keep);assert.deepEqual(await payloads(),split);
            assert.equal(writes.length,0);
            const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/batches/bulk'));
            await dialog.locator('[data-meal-batch-save]').click();const result=await(await response).json();assert.equal(result.ok,true,JSON.stringify(result));
            await dialog.waitFor({state:'hidden'});assert.equal(writes.length,1);
            assert(writes[0].url().endsWith('/batches/bulk'));
            assert.deepEqual(writes[0].postDataJSON().batches.map(batch=>batch.allocations.map(meal=>meal.planned_servings)),[[1,1,1,1],[1.5,1.5,1.5,1.5],[1,1,1,1]]);
            await open();await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
            assert.equal(await yieldInput(0).inputValue(),'4','A new plan starts from the original recipe yield');
            await activate(scale(0,3));await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
            await open();await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
            assert.equal(await yieldInput(0).inputValue(),'4','Cancel discards the draft yield');
            assert.equal(writes.length,1);assert.deepEqual(errors,[]);await context.close();
        }
        console.log('PASS: editable yield, scale, fractions, invalid input, keyboard/touch, duplicate budget, split, preview, idempotence, Save Meals and Cancel');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
