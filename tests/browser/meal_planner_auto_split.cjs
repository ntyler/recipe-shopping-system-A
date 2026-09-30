const {chromium} = require(process.argv[2]);
const {customPlan, legacyCustomPlan, selectDates, dateRange} = require('./meal_planner_test_helpers.cjs');
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
            await selectDates(shared, [mobile?'2026-10-12':'2026-10-05']);
            for (const recipe of ['recipe://soup','recipe://rice']) {
                await dialog.locator('[data-meal-editor-add]').click();
                await dialog.locator('[data-meal-editor]').last().locator('[name="recipe_url"]').selectOption(recipe);
            }
            await legacyCustomPlan(row(2));
            const custom=customPlan(dialog,2).locator('[data-meal-editor-form]');
            await custom.locator('[data-schedule-section="notes"] > summary').click();
            await custom.locator('[data-schedule-field="notes"]').fill('Keep custom portions');
            await legacyCustomPlan(row(2));
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
            assert.deepEqual(await shared.evaluate(el=>JSON.parse(JSON.stringify(document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.draft))),{...JSON.parse(sharedBefore),portionMode:'recipe'});
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
            await dialog.waitFor({state:'hidden'});

            // Reproduction: a four-serving recipe and a two-serving recipe,
            // four selected meals with old per-day totals of 2, 2, 1, 1.
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
            await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
            await dialog.locator('[data-meal-editor-add]').click();
            await row(1).locator('[name="recipe_url"]').selectOption('recipe://salad');
            const dates=dateRange(mobile?'2026-10-20':'2026-09-29',mobile?'2026-10-23':'2026-10-02');
            await selectDates(shared,dates);
            await shared.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('2');
            for(const date of dates.slice(2)) {
                await shared.locator(`[data-schedule-day="${date}"] > summary`).click();
                await shared.locator(`[data-schedule-field="day-household"][data-date="${date}"][data-meal="dinner"]`).fill('1');
            }
            if(mobile) await automatic.tap();else await automatic.press('Enter');
            assert.equal(await amount(0).inputValue(),'1');assert.equal(await amount(1).inputValue(),'0.5');
            assert.deepEqual(await dialog.locator('.app-meal-recipe-table th').allTextContents(),['Recipe','Yield','Servings / meal','Planned','Actions']);
            assert.deepEqual(await dialog.locator('[data-meal-table-planned]').allTextContents(),['4 / 4','2 / 2']);
            if(!mobile) {
                const columns=await dialog.locator('[data-meal-editor]').evaluateAll(rows=>rows.map(row=>({
                    height:row.getBoundingClientRect().height,
                    left:[...row.cells].map(cell=>cell.getBoundingClientRect().left)
                })));
                assert.deepEqual(columns[0].left,columns[1].left,'Recipe rows use aligned columns');
                assert(columns.every(row=>row.height<150),'The table keeps recipe rows compact');
            }
            const stepper=await row(0).locator('.app-meal-recipe-stepper').evaluate(element=>[...element.children].map(child=>{
                const box=child.getBoundingClientRect();return {top:box.top,height:box.height};
            }));
            assert(stepper.every(box=>box.top===stepper[0].top&&box.height===stepper[0].height),'Portion controls align and have equal height');
            assert.equal(await shared.getByRole('button',{name:'Split recipe yield',exact:true}).getAttribute('aria-pressed'),'true');
            assert.match(await row(0).locator('[data-meal-yield-planned]').textContent(),/4 of 4 servings/);
            assert.match(await row(1).locator('[data-meal-yield-planned]').textContent(),/2 of 2 servings/);
            assert.equal(await shared.locator('.is-yield-short').count(),0);
            assert.match(await dialog.locator('[data-meal-shared-distribution-preview]').textContent(),/4 meals across 4 days.*6 servings used.*0 remaining/);
            const split=await payloads();if(mobile)await automatic.tap();else await automatic.press('Space');
            assert.equal(await payloads(),split);assert.equal(posts.length,1);
            // The split continues to follow calendar edits without another click.
            const extra=mobile?'2026-10-24':'2026-10-03';
            await selectDates(shared,[...dates,extra]);
            assert.equal(await amount(0).inputValue(),'0.8');assert.equal(await amount(1).inputValue(),'0.4');
            await selectDates(shared,dates);assert.equal(await payloads(),split);
            await dialog.evaluate(el=>{el.scrollTop=0;});
            if(dir)await page.screenshot({path:path.join(dir,`auto-split-yields-${mobile?'mobile':'desktop'}.png`)});
            await shared.locator('.meal-schedule-calendar').scrollIntoViewIfNeeded();
            if(dir)await page.screenshot({path:path.join(dir,`auto-split-calendar-${mobile?'mobile':'desktop'}.png`)});
            assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
            const splitResponse=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/batches/bulk'));
            await dialog.locator('[data-meal-batch-save]').click();const splitResult=await(await splitResponse).json();
            assert.equal(splitResult.ok,true);assert.equal(posts.length,2);
            assert.deepEqual(posts[1].batches.map(batch=>batch.allocations.map(meal=>meal.planned_servings)),[[1,1,1,1],[0.5,0.5,0.5,0.5]]);
            assert(posts[1].batches.every(batch=>JSON.stringify(batch.allocations.map(meal=>meal.date))===JSON.stringify(dates)));
            assert.deepEqual(errors,[]);await context.close();
        }
        console.log('PASS: Auto split all placement, shared/custom scope, repeated recipe budget, invalid portion recovery, keyboard/touch, idempotence, save boundary, responsive toolbar, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
