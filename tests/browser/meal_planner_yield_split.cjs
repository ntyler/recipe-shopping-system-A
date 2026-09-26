const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Test the production modal with isolated APIs.
    // Flow: choose recipes -> split yields over meals -> customize -> save together.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1000}});
        await context.addCookies([cookie]);
        const page = await context.newPage(), errors = [], posts = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {if (['error','warning'].includes(message.type())) errors.push(message.text());});
        page.on('request', request => {if (request.method() === 'POST' && request.url().endsWith('/batches/bulk')) posts.push(request.postDataJSON());});
        await page.goto(base + '/editor-qa');
        assert.equal(page.url(), base + '/editor-qa');
        assert.equal(await page.title(), 'AI Pantry — Meal Planner');
        assert(await page.getByRole('heading', {name:'Meal Planner',exact:true}).isVisible());
        const dialog = page.locator('#mealPlannerDialog'), shared = dialog.locator('[data-meal-shared-form]');
        const row = index => dialog.locator('[data-meal-editor]').nth(index);
        const summary = index => row(index).locator('[data-meal-editor-summary]');
        const save = dialog.locator('[data-meal-batch-save]');
        const open = async () => {
            await page.getByRole('button', {name:'Add Meals',exact:true}).click();
            await page.waitForFunction(() => !document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
        };
        const screenshot = async name => {
            const dir = process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if (dir) {fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}
        };
        await open();
        for (const [index, name] of ['bread','soup','rice'].entries()) {
            if (index) await dialog.locator('[data-meal-editor-add]').click();
            await row(index).locator('[name="recipe_url"]').selectOption('recipe://' + name);
        }
        assert.equal(await shared.getByRole('button',{name:'Split recipe yield',exact:true}).getAttribute('aria-pressed'),'true');
        await shared.getByRole('button',{name:'Date range',exact:true}).click();
        await shared.locator('[data-schedule-field="end-date"]').fill('2026-10-06');
        await shared.locator('[data-schedule-field="meal"][data-meal="lunch"]').check();
        assert.equal(await save.textContent(),'Save 4 Meals');
        for (const [index,total,perMeal] of [[0,8,2],[1,4,1],[2,6,1.5]]) {
            assert((await summary(index).textContent()).includes(`4 meals · ${total} servings (${perMeal} per meal)`));
        }
        await row(1).locator('[data-meal-editor-customize]').click();
        const soup = row(1).locator('[data-meal-editor-form]');
        await soup.getByRole('button',{name:'One day',exact:true}).click();
        await soup.locator('[data-schedule-field="single-date"]').fill('2026-10-09');
        await soup.locator('[data-schedule-field="meal"][data-meal="lunch"]').uncheck();
        assert.match(await summary(1).textContent(),/1 meal · 4 servings \(4 per meal\)/);
        await soup.getByRole('button',{name:'Household total',exact:true}).click();
        await soup.locator('[data-schedule-field="household"][data-meal="dinner"]').fill('2.5');
        assert.match(await summary(1).textContent(),/1 meal · 2.5 servings/);
        await soup.getByRole('button',{name:'Split recipe yield',exact:true}).click();
        assert.match(await summary(1).textContent(),/1 meal · 4 servings/);
        await row(1).locator('[data-meal-editor-customize]').click();
        assert.equal(await save.textContent(),'Save 5 Meals');
        await dialog.evaluate(element => {element.scrollTop = 0;});
        await screenshot('add-meals-split-desktop.png');
        await page.setViewportSize({width:390,height:844});
        await dialog.evaluate(element => {element.scrollTop = 0;});
        const bounds = await dialog.evaluate(element => ({width:element.clientWidth,scroll:element.scrollWidth,height:element.getBoundingClientRect().height}));
        assert(bounds.scroll <= bounds.width + 1);assert(bounds.height <= 844);
        await screenshot('add-meals-split-mobile.png');
        await page.setViewportSize({width:1440,height:1000});
        await save.click();await dialog.waitFor({state:'hidden'});
        assert.equal(posts.length,1);
        for (const [name,count,total,perMeal] of [['bread',4,8,2],['soup',1,4,4],['rice',4,6,1.5]]) {
            const plan = posts[0].batches.find(item => item.recipe_url === 'recipe://' + name);
            assert.equal(plan.allocations.length,count);assert(plan.allocations.every(meal => meal.planned_servings === perMeal));
            const stored = await (await context.request.get(base + '/api/meal-plan?recipe_url=recipe://' + name)).json();
            assert.equal(stored.meals.length,count);
            assert.equal(stored.meals.reduce((sum,meal) => sum + meal.planned_servings,0),total);
        }
        // An uneven split also saves the original yield exactly in the real API.
        await open();await row(0).locator('[name="recipe_url"]').selectOption('recipe://rice');
        await shared.getByRole('button',{name:'Date range',exact:true}).click();
        await shared.locator('[data-schedule-field="start-date"]').fill('2026-11-01');
        await shared.locator('[data-schedule-field="end-date"]').fill('2026-11-07');
        assert.match(await summary(0).textContent(),/7 meals · 6 servings/);
        const response = page.waitForResponse(res => res.url().endsWith('/batches/bulk') && res.request().method() === 'POST');
        await save.click();const result = await (await response).json();await dialog.waitFor({state:'hidden'});
        assert.equal(result.batches[0].batch_servings,6);
        assert.equal(result.batches[0].allocated_servings,6);
        assert.equal(result.meals.length,7);
        assert(result.meals.every(meal => meal.planned_servings > 0));
        // Two entries of the same four-serving
        // recipe in the same date/meal slot must use two servings each.
        await open();await row(0).locator('[name="recipe_url"]').selectOption('recipe://soup');
        await dialog.locator('[data-meal-editor-add]').click();
        await row(1).locator('[name="recipe_url"]').selectOption('recipe://soup');
        for (const index of [0,1]) assert.match(await summary(index).textContent(),/1 meal · 2 servings \(2 per meal\)/);
        assert.match(await dialog.locator('[data-meal-batch-help]').textContent(),/1 recipe · 1 meal/);
        await row(1).locator('[data-meal-editor-customize]').click();
        assert.match(await soup.locator('[data-schedule-summary]').textContent(),/1 meal · 2 servings/);
        await soup.getByRole('button',{name:'Household total',exact:true}).click();
        const portions = soup.locator('[data-schedule-field="household"][data-meal="dinner"]');
        assert.equal(await portions.inputValue(),'2','Manual mode starts with the displayed share');
        await portions.fill('1.5');
        assert.match(await summary(0).textContent(),/1 meal · 2.5 servings/);
        await soup.getByRole('button',{name:'Split recipe yield',exact:true}).click();
        await row(1).locator('[data-meal-editor-reset]').click();
        for (const index of [0,1]) assert.match(await summary(index).textContent(),/1 meal · 2 servings/);
        await dialog.evaluate(element => {element.scrollTop = 0;});
        await screenshot('repeated-recipe-split-desktop.png');
        await page.setViewportSize({width:390,height:844});
        assert(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
        await screenshot('repeated-recipe-split-mobile.png');
        await page.setViewportSize({width:1440,height:1000});
        const repeatedResponse = page.waitForResponse(res => res.url().endsWith('/batches/bulk') && res.request().method() === 'POST');
        await save.click();const repeated = await (await repeatedResponse).json();await dialog.waitFor({state:'hidden'});
        assert.equal(repeated.meals.length,2);
        assert.deepEqual(repeated.meals.map(meal => meal.planned_servings),[2,2]);
        assert.equal(new Set(repeated.meals.map(meal => meal.id)).size,2);
        assert.equal(repeated.meals[0].date,repeated.meals[1].date);
        assert.equal(repeated.meals[0].meal_type,repeated.meals[1].meal_type);
        const edit = await context.request.patch(base + '/api/meal-plan/' + repeated.meals[0].id,{data:{prep_notes:'First portion'}});
        assert.equal(edit.status(),200,'A repeated meal remains individually editable');
        const editBatch = await context.request.patch(base + '/api/meal-plan/batches/' + repeated.batches[1].id,{data:{prep_notes:'Second portion'}});
        assert.equal(editBatch.status(),200,'Its prep plan remains editable');
        const retry = await context.request.post(base + '/api/meal-plan/batches/bulk',{data:posts.at(-1)});
        assert.equal(retry.status(),400,'Retry must not duplicate an already saved batch');
        const allSoup = await (await context.request.get(base + '/api/meal-plan?recipe_url=recipe://soup')).json();
        assert.equal(allSoup.meals.length,3);
        assert.deepEqual(errors,[]);
        console.log('PASS: independent and repeated recipe yield splits, date/meal recalculation, custom portions, atomic save/retry, editable repeated meals, exact fractional totals, desktop/mobile, clean console');
    } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
