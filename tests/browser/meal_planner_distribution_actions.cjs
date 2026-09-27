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
            const action=mode=>row(0).locator(`[data-meal-distribution-mode="${mode}"]`);
            const calendar=shared.locator('[data-distribution-preview]'),save=dialog.locator('[data-meal-batch-save]');
            const draft=()=>dialog.evaluate(element=>JSON.stringify(element.mealPlanScheduleState.panel.draft));
            const open=async()=>{
                await page.getByRole('button',{name:'Add Meals',exact:true}).click();
                await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
                await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
                await shared.getByRole('button',{name:'One day',exact:true}).click();
                await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('1');
            };
            await open();
            assert.deepEqual(await row(0).locator('[data-meal-distribution-mode]:visible').allTextContents(),['Fill upcoming days','Distribute on selected days']);
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

            // With two recipes, a recipe's 1-serving share differs from the 2-serving household total.
            await open();await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('2');
            await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
            // Reserve the other recipe on a different date so both strategies fit.
            await row(1).locator('[data-meal-editor-customize]').click();
            await row(1).locator('[data-meal-editor-form]').getByRole('button',{name:'One day',exact:true}).click();
            await row(1).locator('[data-meal-editor-form] [data-schedule-field="single-date"]').fill('2026-10-04');
            await row(0).locator('[data-meal-recipe-servings]').fill('1');
            assert(await action('people').isVisible());
            assert.equal(await action('upcoming').textContent(),'Fill upcoming days at 1 serving per meal');
            await action('upcoming').hover();assert.equal(await row(0).locator('[data-meal-distribution-meals] li').count(),4);
            await action('people').hover();assert.equal(await row(0).locator('[data-meal-distribution-meals] li').count(),2);
            if(mobile) await action('people').tap();else await action('people').click();
            assert(await row(0).locator('[data-meal-editor-form]').isVisible());
            assert.match(await row(0).locator('[data-meal-editor-summary]').textContent(),/2 meals · 4 servings/);
            assert(await action('people').isHidden(),'Identical custom-plan results also combine');
            assert(await action('upcoming').evaluate(element=>document.activeElement===element),'Focus stays on the surviving action');
            assert.equal(await dialog.locator('[data-distribution-preview]').count(),0);
            const custom=row(0).locator('[data-meal-editor-form]');
            await custom.locator('[data-schedule-day="2026-10-06"] summary').click();
            await custom.locator('[data-schedule-day="2026-10-06"] [data-schedule-field="day-household"][data-meal="dinner"]').fill('1');
            assert(await action('people').isVisible(),'A day-specific portion makes the strategies distinct again');
            assert.deepEqual(errors,[]);await context.close();
        }
        console.log('PASS: direct buttons, hover/focus/leave, Enter/Space, first-tap mobile, repeated activation, save boundary, selected dates, distinct and merged custom strategies, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
