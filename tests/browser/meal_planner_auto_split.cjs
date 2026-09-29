const {chromium} = require(process.argv[2]);
const {customPlan} = require('./meal_planner_test_helpers.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Flow: shared + custom recipes -> Auto split all -> Save Meals.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        for (const mobile of [false,true]) {
            const context = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1200},isMobile:mobile,hasTouch:mobile});
            await context.addCookies([cookie]);
            const page=await context.newPage(),errors=[],posts=[];
            page.on('pageerror',e=>errors.push(e.message));
            page.on('console',m=>{if(['error','warning'].includes(m.type()))errors.push(m.text());});
            page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/batches/bulk'))posts.push(r.postDataJSON());});
            await page.goto(base+'/editor-qa');
            assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
            assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            const dialog=page.locator('#mealPlannerDialog'),shared=dialog.locator('[data-meal-shared-form]');
            const row=i=>dialog.locator('[data-meal-editor]').nth(i),amount=i=>row(i).locator('[data-meal-recipe-servings]');
            const automatic=dialog.getByRole('button',{name:'Auto split all',exact:true});
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
            await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
            assert(await automatic.isHidden(),'One recipe already uses all shared portions');
            await shared.getByRole('button',{name:'One day',exact:true}).click();
            await shared.locator('[data-schedule-field="single-date"]').fill(mobile?'2026-10-12':'2026-10-05');
            for (const recipe of ['recipe://soup','recipe://rice']) {
                await dialog.locator('[data-meal-editor-add]').click();
                await dialog.locator('[data-meal-editor]').last().locator('[name="recipe_url"]').selectOption(recipe);
            }
            await row(2).locator('[data-meal-editor-customize]').click();
            const custom=customPlan(dialog,2).locator('[data-meal-editor-form]');
            await custom.locator('[data-schedule-section="notes"] > summary').click();
            await custom.locator('[data-schedule-field="notes"]').fill('Keep custom portions');
            await row(2).locator('[data-meal-editor-customize]').click();
            await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('5');
            await amount(0).fill('3');await amount(1).fill('3');
            assert.equal(await dialog.locator('[data-meal-shared-distribution-mode="keep"]').getAttribute('aria-disabled'),'true');
            const customBefore=await row(2).evaluate(el=>JSON.stringify(el.mealPlannerEntry.panel.draft));
            const sharedBefore=await shared.evaluate(el=>JSON.stringify(document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.draft));
            const payloads=()=>dialog.evaluate(el=>JSON.stringify(el.mealPlanScheduleState.entries.map(entry=>MealPlanSchedule.payload(mealPlannerRecipeDraft(el.mealPlanScheduleState,entry)))));
            assert.equal(await dialog.locator('[data-meal-editors] [data-meal-portions-auto]').count(),0);
            if (mobile) await automatic.tap();
            else {
                await dialog.locator('[data-meal-shared-distribution-mode="keep"]').focus();await page.keyboard.press('Tab');
                assert(await automatic.evaluate(el=>el===document.activeElement&&el.matches(':focus-visible')));
                assert(await automatic.evaluate(el=>getComputedStyle(el).outlineStyle!=='none'));
                await page.keyboard.press('Enter');
            }
            assert.equal(await amount(0).inputValue(),'2');assert.equal(await amount(1).inputValue(),'2');
            assert.match(await row(0).locator('[data-meal-yield-planned]').textContent(),/4 of 4 servings planned across 2 entries/);
            assert.equal(await row(2).evaluate(el=>JSON.stringify(el.mealPlannerEntry.panel.draft)),customBefore);
            assert.equal(await shared.evaluate(el=>JSON.stringify(document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.draft)),sharedBefore);
            assert.equal(await dialog.locator('[data-meal-shared-distribution-mode="keep"]').getAttribute('aria-disabled'),'false');
            const applied=await payloads();
            if(mobile) await automatic.tap();else await automatic.press('Space');
            assert.equal(await payloads(),applied);assert.equal(posts.length,0);
            const toolbar=dialog.locator('[data-meal-shared-distribution] .app-meal-distribution-toolbar');
            assert.equal(await toolbar.locator('button:visible').count(),4);
            if(mobile) await dialog.locator('[data-meal-shared-distribution-preview]').tap();
            await toolbar.evaluate(el=>el.scrollIntoView({block:'center'}));
            assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
            const bounds=await toolbar.locator('button:visible').evaluateAll(buttons=>buttons.map(button=>{const b=button.getBoundingClientRect();return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,height:b.height};}));
            for(let i=0;i<bounds.length;i++){
                assert(bounds[i].height>=44);
                for(let j=0;j<i;j++) assert(bounds[i].right<=bounds[j].left||bounds[j].right<=bounds[i].left||bounds[i].bottom<=bounds[j].top||bounds[j].bottom<=bounds[i].top,'Toolbar buttons must not overlap');
            }
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,`auto-split-${mobile?'mobile':'desktop'}.png`)});}
            const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/batches/bulk'));
            await dialog.locator('[data-meal-batch-save]').click();const result=await(await response).json();
            assert.equal(result.ok,true);assert.equal(posts.length,1);
            assert.deepEqual(posts[0].batches.map(batch=>batch.allocations[0].planned_servings),[2,2,1]);
            assert.equal(posts[0].batches[2].prep_notes,'Keep custom portions');
            assert.deepEqual(errors,[]);await context.close();
        }
        console.log('PASS: Auto split all placement, shared/custom scope, repeated recipe budget, invalid portion recovery, keyboard/touch, idempotence, save boundary, responsive toolbar, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
