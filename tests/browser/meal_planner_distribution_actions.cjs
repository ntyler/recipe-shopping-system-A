const {customPlan} = require('./meal_planner_test_helpers.cjs');
const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Exercise production controls and isolated APIs.
    // Flow: preview a direct action -> activate -> leave -> repeat -> save.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        for (const mobile of [false,true]) {
            const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1200},isMobile:mobile,hasTouch:mobile});
            await context.addCookies([cookie]);
            const page=await context.newPage(),errors=[],posts=[];
            page.on('pageerror',error=>errors.push(error.message));
            page.on('console',message=>{if(['error','warning'].includes(message.type()))errors.push(message.text());});
            page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/batches/bulk'))posts.push(request.postDataJSON());});
            await page.goto(base+'/editor-qa');
            assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
            assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
            const dialog=page.locator('#mealPlannerDialog'),shared=dialog.locator('[data-meal-shared-form]');
            const row=i=>dialog.locator('[data-meal-editor]').nth(i);
            const toolbar=dialog.locator('[data-meal-shared-distribution]');
            const action=mode=>toolbar.locator(`[data-meal-shared-distribution-mode="${mode}"]`);
            const calendar=shared.locator('[data-distribution-preview]'),save=dialog.locator('[data-meal-batch-save]');
            const draft=()=>dialog.evaluate(element=>JSON.stringify(element.mealPlanScheduleState.panel.draft));
            const open=async(useDefaults=false)=>{
                await page.getByRole('button',{name:'Add Meals',exact:true}).click();
                await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
                await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
                await shared.getByRole('button',{name:'One day',exact:true}).click();
                if(!useDefaults) await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('1');
            };
            await open();
            // Both viewports use the same isolated account; save different weeks.
            if(mobile) await shared.locator('[data-schedule-field="single-date"]').fill('2026-10-12');
            assert.deepEqual(await toolbar.locator('[data-meal-shared-distribution-mode]:visible').allTextContents(),['Fill upcoming days for all','Distribute all on selected days']);
            assert(await row(0).locator('[data-meal-distribution]').isHidden());
            assert(await toolbar.locator('[data-meal-editor-add]').isVisible());
            assert.equal(await row(0).locator('[data-meal-distribution] input[type="radio"]').count(),0);
            assert.equal(await dialog.getByRole('button',{name:'Apply distribution',exact:true}).count(),0);
            assert.equal(await dialog.getByRole('button',{name:'Distribute recipe servings',exact:true}).count(),0);
            const before=await draft();
            if (mobile) {
                await action('upcoming').tap();
            } else {
                await action('upcoming').hover();assert.equal(await draft(),before);assert(await calendar.isVisible());
                await page.mouse.move(0,0);assert.equal(await draft(),before);assert(await calendar.isHidden());
                await action('keep').focus();await page.keyboard.press('Shift+Tab');
                assert(await action('upcoming').evaluate(element=>document.activeElement===element));
                assert(await calendar.isVisible());assert.equal(await save.textContent(),'Save 4 Meals');
                await page.keyboard.press('Tab');
                assert(await action('keep').evaluate(element=>document.activeElement===element));
                assert.equal(await save.textContent(),'Save 1 Meal');assert.equal(await draft(),before);
                await page.keyboard.press('Tab');assert(await calendar.isHidden());
                await page.keyboard.press('Shift+Tab');await page.keyboard.press('Shift+Tab');
                await page.keyboard.press('Enter');
            }
            assert.equal(await save.textContent(),'Save 4 Meals');assert(await calendar.isHidden());assert.equal(posts.length,0);
            const applied=await draft();assert.notEqual(applied,before);
            if (mobile) await action('upcoming').tap();
            else {
                await page.keyboard.press('Tab');await page.mouse.move(0,0);assert.equal(await draft(),applied);
                await action('upcoming').press('Space');
            }
            assert.equal(await draft(),applied,'Repeated activation replaces the draft and never appends meals');
            assert(await calendar.isHidden());assert.equal(posts.length,0);
            assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
            await dialog.evaluate(element=>{element.scrollTop=0;});
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,`distribution-actions-${mobile?'mobile':'desktop'}.png`)});}
            const response=page.waitForResponse(res=>res.url().endsWith('/batches/bulk')&&res.request().method()==='POST');
            if(mobile) await save.tap();else await save.click();
            const saved=await(await response).json();assert.equal(saved.ok,true);assert.equal(saved.meals.length,4);assert.equal(posts.length,1);

            // Preserve nonconsecutive dates and portions when applying selected days.
            await open();await shared.getByRole('button',{name:'Select days',exact:true}).click();
            await shared.locator('[data-schedule-action="date"][data-date="2026-10-07"]').click();
            await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('1.5');
            if(mobile) await action('keep').tap();else await action('keep').press('Enter');
            assert.deepEqual(JSON.parse(await draft()).selectedDates,['2026-10-05','2026-10-07']);
            assert.equal(await save.textContent(),'Save 2 Meals');
            assert.match(await row(0).locator('[data-meal-yield-remaining]').textContent(),/1 serving left/);
            await dialog.locator('[data-meal-batch-footer]').getByRole('button',{name:'Cancel',exact:true}).click();

            // Selecting two recipes with their default portions must work
            // without first finding and increasing the shared meal total.
            await open(true);
            await shared.locator('[data-schedule-field="single-date"]').fill('2026-09-26');
            await shared.locator('[data-schedule-field="meal"][data-meal="breakfast"]').check();
            await shared.locator('[data-schedule-field="meal"][data-meal="dinner"]').uncheck();
            await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
            assert.equal(await shared.locator('[data-schedule-field="household"][data-meal="breakfast"]').inputValue(),'2');
            assert.equal(await action('upcoming').getAttribute('aria-disabled'),'false');
            assert.equal(await action('keep').getAttribute('aria-disabled'),'false');
            const defaultDraft=await draft(),defaultPosts=posts.length;
            if(mobile) await action('keep').tap();else await action('keep').press('Enter');
            assert.deepEqual(JSON.parse(await draft()).selectedDates,['2026-09-26']);
            const afterKeep=await draft();
            if(!mobile){await action('upcoming').hover();assert.equal(await draft(),afterKeep);assert(await calendar.isVisible());}
            if(mobile) await action('upcoming').tap();else await action('upcoming').click();
            assert.equal(await save.textContent(),'Save 8 Meals');assert.equal(posts.length,defaultPosts);
            const defaultApplied=await draft();assert.notEqual(defaultApplied,defaultDraft);
            if(mobile) await action('upcoming').tap();else await action('upcoming').press('Space');
            assert.equal(await draft(),defaultApplied);
            const defaultAmounts=await dialog.evaluate(element=>element.mealPlanScheduleState.entries.map(entry=>MealPlanSchedule.summary(mealPlannerRecipeDraft(element.mealPlanScheduleState,entry)).totalServings));
            assert.deepEqual(defaultAmounts,[4,8]);
            if(mobile) await toolbar.evaluate(element=>element.scrollIntoView({block:'start'}));
            else await dialog.evaluate(element=>{element.scrollTop=0;});
            if(dir) await page.screenshot({path:path.join(dir,`default-portions-${mobile?'mobile':'desktop'}.png`)});
            // An explicitly smaller total still blocks the action and explains
            // the actual numbers, without partially applying the distribution.
            await dialog.locator('[data-meal-batch-footer]').getByRole('button',{name:'Cancel',exact:true}).click();
            await open();
            await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
            const explicitDraft=await draft();
            await action('keep').focus();await page.keyboard.press('Enter');
            assert.equal(await draft(),explicitDraft);assert.equal(posts.length,defaultPosts);
            assert.match(await toolbar.locator('[data-meal-shared-distribution-preview]').textContent(),/2 planned; 1 available/);
            await dialog.locator('[data-meal-batch-footer]').getByRole('button',{name:'Cancel',exact:true}).click();

            // Both shared recipes use their own 1-serving contribution, not the 2-serving meal total.
            await open();await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('2');
            await shared.locator('[data-schedule-field="single-date"]').fill(mobile?'2026-11-16':'2026-11-02');
            await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
            await row(0).locator('[data-meal-recipe-servings]').fill('1');
            assert.equal(await dialog.locator('[data-meal-distribution]:visible').count(),0);
            assert.equal(await toolbar.locator('button:visible').count(),3);
            const beforeAll=await draft();await action('upcoming').focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
            assert(await calendar.isVisible());assert.equal(await save.textContent(),'Save 8 Meals');assert.equal(await draft(),beforeAll);
            assert.equal(await shared.locator('.meal-schedule-calendar-heading strong').textContent(),'November 2026');
            assert.equal(await toolbar.locator('[data-meal-shared-distribution-meals] li').count(),12);
            if(mobile) {
                await toolbar.evaluate(element=>element.scrollIntoView({block:'start'}));
                await dialog.evaluate(element=>{element.scrollTop=Math.max(0,element.scrollTop-60);});
            } else await dialog.evaluate(element=>{element.scrollTop=0;});
            if(dir) await page.screenshot({path:path.join(dir,`merged-distribution-${mobile?'mobile':'desktop'}.png`)});
            await page.keyboard.press('Escape');assert(await calendar.isHidden());assert(await dialog.isVisible());
            // An invalid recipe prevents the complete action; even the other recipe stays untouched.
            await row(1).locator('[data-meal-recipe-servings]').fill('');
            const invalid=await draft();const sent=posts.length;
            assert.equal(await action('upcoming').getAttribute('aria-disabled'),'true');
            await action('upcoming').focus();await page.keyboard.press('Enter');
            assert.equal(await draft(),invalid);assert.equal(posts.length,sent);
            assert.match(await toolbar.locator('[data-meal-shared-distribution-preview]').textContent(),/Recipe [12].*(?:positive|servings|portions)/);
            await row(1).locator('[data-meal-recipe-servings]').fill('1');
            // A custom schedule keeps both its draft and its own action buttons.
            await dialog.locator('[data-meal-editor-add]').click();await row(2).locator('[name="recipe_url"]').selectOption('recipe://rice');
            await row(2).locator('[data-meal-editor-customize]').click();
            const custom=customPlan(dialog,2).locator('[data-meal-editor-form]');
            await custom.getByRole('button',{name:'One day',exact:true}).click();
            await custom.locator('[data-schedule-field="single-date"]').fill(mobile?'2026-11-15':'2026-11-01');
            await row(2).locator('[data-meal-editor-customize]').click();
            assert(await row(2).locator('[data-meal-distribution]').isVisible());
            const customBefore=await row(2).evaluate(element=>JSON.stringify(element.mealPlannerEntry.panel.draft));
            if(mobile) await action('upcoming').tap();else await action('upcoming').press('Enter');
            assert.equal(await row(2).evaluate(element=>JSON.stringify(element.mealPlannerEntry.panel.draft)),customBefore);
            assert.equal(await save.textContent(),'Save 9 Meals');assert.equal(posts.length,sent);assert(await calendar.isHidden());
            const amounts=await dialog.evaluate(element=>element.mealPlanScheduleState.entries.map(entry=>MealPlanSchedule.summary(mealPlannerRecipeDraft(element.mealPlanScheduleState,entry)).totalServings));
            assert.deepEqual(amounts,[4,8,1]);
            const allApplied=await draft();if(mobile) await action('upcoming').tap();else await action('upcoming').press('Space');
            assert.equal(await draft(),allApplied);assert.equal(posts.length,sent);
            const allResponse=page.waitForResponse(res=>res.url().endsWith('/batches/bulk')&&res.request().method()==='POST');
            await save.click();const allSaved=await(await allResponse).json();assert.equal(allSaved.ok,true);assert.equal(allSaved.meals.length,13);
            assert.equal(posts.at(-1).batches.length,3);
            assert.deepEqual(posts.at(-1).batches.map(batch=>batch.allocations.length),[4,8,1]);
            // Repeated entries divide one recipe yield and remain in the shared plan.
            await open();await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('2');
            await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://soup');
            await row(0).locator('[data-meal-recipe-servings]').fill('1');
            await action('upcoming').click();assert.equal(await save.textContent(),'Save 2 Meals');
            assert.match(await dialog.locator('[data-meal-batch-help]').textContent(),/4 servings/);
            assert.equal(await dialog.locator('[data-meal-editor-form]').count(),1);
            assert(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth+1));
            assert.deepEqual(errors,[]);await context.close();
        }
        console.log('PASS: direct buttons, hover/focus/leave, Enter/Space, first-tap mobile, repeated activation, save boundary, selected dates, distinct and merged custom strategies, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
