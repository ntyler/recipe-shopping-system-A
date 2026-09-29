const {chromium} = require(process.argv[2]);
const {customPlan, selectCalendar, legacyCustomPlan, selectDates} = require('./meal_planner_test_helpers.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Use the repository's isolated Chromium fixture.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        for (const mobile of [false,true]) {
            const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1200},isMobile:mobile,hasTouch:mobile});
            await context.addCookies([cookie]);
            const page=await context.newPage(),errors=[],posts=[];
            page.on('pageerror',e=>errors.push(e.message));
            page.on('console',m=>{if(['error','warning'].includes(m.type()))errors.push(m.text());});
            page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/batches/bulk'))posts.push(r.postDataJSON());});
            await page.goto(base+'/editor-qa');
            assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
            assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
            const dialog=page.locator('#mealPlannerDialog'),shared=dialog.locator('[data-meal-shared-form]');
            const row=i=>dialog.locator('[data-meal-editor]').nth(i),picker=dialog.getByLabel('Calendar for',{exact:true});
            const form=i=>customPlan(dialog,i).locator('[data-meal-editor-form]');
            const snapshot=()=>dialog.evaluate(el=>JSON.stringify([el.mealPlanScheduleState.panel.draft,...el.mealPlanScheduleState.entries.map(e=>e.panel?.draft)]));
            const oneCalendar=async()=>assert.equal(await dialog.locator('[data-meal-editor-form]:visible').count(),1);
            const open=async()=>{
                await page.getByRole('button',{name:'Add Meals',exact:true}).click();
                await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
                await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
            };
            await open();
            await selectDates(shared, [mobile?'2026-10-28':'2026-09-28']);
            for(const recipe of ['recipe://bread','recipe://rice']){
                await dialog.locator('[data-meal-editor-add]').click();
                await dialog.locator('[data-meal-editor]').last().locator('[name="recipe_url"]').selectOption(recipe);
            }
            for(const i of [0,1]){
                await legacyCustomPlan(row(i));await oneCalendar();
                await selectDates(form(i), [`2026-${mobile?'10':'09'}-${26+i}`]);
                await form(i).locator('[data-schedule-section="notes"] > summary').click();
                await form(i).locator('[data-schedule-field="notes"]').fill(`Custom notes ${i}`);
            }
            assert.equal(await dialog.locator('[data-meal-editors] [data-meal-editor-form]').count(),0,'Calendar forms belong below the recipe list');
            assert.equal(await picker.locator('option').count(),3);
            const before=await snapshot();
            for(const i of [null,0,1,null]){
                await selectCalendar(dialog,i);await oneCalendar();assert.equal(await snapshot(),before);
                assert.equal(await shared.isVisible(),i===null);
            }
            // Native select supports keyboard navigation and keeps its focus.
            await picker.focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
            assert.equal(await picker.inputValue(),await row(0).getAttribute('data-meal-editor'));await oneCalendar();
            assert(await picker.evaluate(el=>el===document.activeElement));
            const customAction=row(0).locator('[data-meal-distribution-mode="keep"]');
            await selectCalendar(dialog,null);
            if(!mobile){
                await customAction.hover();await oneCalendar();assert(await form(0).isVisible());assert.equal(await snapshot(),before);
                await page.mouse.move(0,0);assert(await shared.isVisible());assert.equal(await snapshot(),before);
                await selectCalendar(dialog,1);
                await dialog.locator('[data-meal-shared-distribution-mode="upcoming"]').focus();
                await oneCalendar();assert(await shared.isVisible());assert.equal(await snapshot(),before);
                await page.keyboard.press('Escape');assert(await form(1).isVisible());
            }
            if(mobile) await customAction.tap();else await customAction.press('Enter');
            await oneCalendar();assert(await form(0).isVisible());assert.equal(posts.length,0);
            assert.equal(await form(0).locator('.meal-schedule-calendar-heading strong').textContent(),mobile?'October 2026':'September 2026');
            assert.equal(await picker.locator('option').count(),3,'Applying distribution preserves the custom plan');
            const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            await dialog.locator('[data-meal-calendar-workspace]').evaluate(el=>el.scrollIntoView({block:'start'}));
            assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
            if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,`calendar-switch-${mobile?'mobile':'desktop'}.png`)});}
            const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/batches/bulk'));
            await dialog.locator('[data-meal-batch-save]').click();const result=await(await response).json();
            assert.equal(result.ok,true);assert.equal(posts.length,1);assert.equal(posts[0].batches.length,3);
            assert.deepEqual(posts[0].batches.map(b=>b.allocations[0].date),[26,27,28].map(day=>`2026-${mobile?'10':'09'}-${day}`));
            assert.deepEqual(posts[0].batches.slice(0,2).map(b=>b.prep_notes),['Custom notes 0','Custom notes 1']);
            // Removing the original row must not break reopening its reusable editor.
            await open();await legacyCustomPlan(row(0));await oneCalendar();
            await dialog.locator('[data-meal-editor-add]').click();await row(1).locator('[name="recipe_url"]').selectOption('recipe://bread');
            await row(0).locator('[data-meal-editor-remove]').click();await oneCalendar();assert(await shared.isVisible());
            await legacyCustomPlan(row(0));
            await customPlan(dialog,0).locator('[data-meal-editor-reset]').click();await oneCalendar();assert(await picker.isHidden());
            await dialog.locator('[data-meal-batch-footer]').getByRole('button',{name:'Cancel',exact:true}).click();
            await open();await legacyCustomPlan(row(0));await oneCalendar();assert(await form(0).isVisible());
            assert.equal(posts.length,1);assert.deepEqual(errors,[]);await context.close();
        }
        console.log('PASS: one calendar, shared/custom switching, keyboard, previews, draft preservation, atomic save, reset/removal/reopen, desktop/mobile');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
