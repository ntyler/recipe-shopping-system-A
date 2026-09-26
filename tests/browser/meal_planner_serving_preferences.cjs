const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available. Use production controls with isolated real APIs.
    // Flow: Add Meals -> distinct recipe portions -> save -> refresh -> restore/edit.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1000}});
        await context.addCookies([cookie]);
        const page = await context.newPage(), errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {if (['error','warning'].includes(message.type())) errors.push(message.text());});
        await page.goto(base+'/editor-qa');
        assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
        assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
        const dialog = page.locator('#mealPlannerDialog'), shared = dialog.locator('[data-meal-shared-form]');
        const row = i => dialog.locator('[data-meal-editor]').nth(i);
        const recipe = i => row(i).locator('[name="recipe_url"]');
        const amount = i => row(i).locator('[data-meal-recipe-servings]');
        const total = dialog.locator('[data-meal-batch-help]'), save = dialog.locator('[data-meal-batch-save]');
        const open = async () => {
            await page.getByRole('button',{name:'Add Meals',exact:true}).click();
            await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.panel.ui.loading);
        };
        const cancel = () => dialog.getByRole('button',{name:'Cancel',exact:true}).click();
        const saveMeals = async () => {
            const response = page.waitForResponse(res=>res.url().endsWith('/batches/bulk') && res.request().method()==='POST');
            await save.click();const saved = await(await response).json();assert.equal(saved.ok,true);
            await dialog.waitFor({state:'hidden'});return saved;
        };
        const screenshot = async name => {
            const dir = process.env.AI_PANTRY_BROWSER_ARTIFACTS;
            if (dir) {fs.mkdirSync(dir,{recursive:true});await dialog.evaluate(e=>{e.scrollTop=0;});await page.screenshot({path:path.join(dir,name)});}
        };

        await open();await recipe(0).selectOption('recipe://bread');
        assert.equal(await amount(0).inputValue(),'1');assert.match(await total.textContent(),/1 meal · 1 serving/);
        await amount(0).fill('2.5');await recipe(0).selectOption('recipe://soup');
        assert.equal(await amount(0).inputValue(),'1');await recipe(0).selectOption('recipe://bread');
        assert.equal(await amount(0).inputValue(),'1','Switching back discards an unsaved preference');
        await amount(0).fill('3');await cancel();await open();await recipe(0).selectOption('recipe://bread');
        assert.equal(await amount(0).inputValue(),'1','Cancel must not remember portions');

        await amount(0).fill('2.5');
        await shared.getByRole('button',{name:'Date range',exact:true}).click();
        await shared.locator('[data-schedule-field="end-date"]').fill('2026-10-06');
        await shared.locator('[data-schedule-field="meal"][data-meal="lunch"]').check();
        await shared.locator('[data-schedule-section="notes"] > summary').click();
        await shared.locator('[data-schedule-field="notes"]').fill('Keep servings while planning');
        assert.equal(await amount(0).inputValue(),'2.5');assert.match(await total.textContent(),/4 meals · 10 servings/);
        await dialog.locator('[data-meal-editor-add]').click();await recipe(1).selectOption('recipe://soup');
        assert.equal(await amount(1).inputValue(),'1');await amount(1).fill('0.75');
        assert.equal(await amount(0).inputValue(),'2.5','A different recipe retains its own amount');
        assert.match(await total.textContent(),/2 recipes · 4 meals · 13 servings/);
        await screenshot('serving-preferences-desktop.png');
        await page.setViewportSize({width:390,height:844});
        assert(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
        await screenshot('serving-preferences-mobile.png');await page.setViewportSize({width:1440,height:1000});
        const first = await saveMeals();
        assert.deepEqual(first.batches.map(batch=>batch.batch_servings),[10,3]);
        assert.equal(first.meals.length,8);
        assert(first.meals.filter(meal=>meal.recipe_url==='recipe://bread').every(meal=>meal.planned_servings===2.5));
        assert(first.meals.filter(meal=>meal.recipe_url==='recipe://soup').every(meal=>meal.planned_servings===0.75));

        await page.reload();await open();await recipe(0).selectOption('recipe://bread');
        assert.equal(await amount(0).inputValue(),'2.5');
        await recipe(0).selectOption('recipe://soup');assert.equal(await amount(0).inputValue(),'0.75');
        await recipe(0).selectOption('recipe://rice');assert.equal(await amount(0).inputValue(),'1');
        await recipe(0).selectOption('recipe://bread');
        await amount(0).fill('4');
        // A rejected save must retain the previous successful preference.
        await page.route('**/api/meal-plan/batches/bulk', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:false,error:'Simulated save failure'})}));
        await save.click();await page.waitForFunction(()=>!document.getElementById('mealPlannerDialog').mealPlanScheduleState.saving);
        assert(await dialog.isVisible());assert.equal(await amount(0).inputValue(),'4');
        await page.unroute('**/api/meal-plan/batches/bulk');await cancel();await page.reload();await open();
        await recipe(0).selectOption('recipe://bread');assert.equal(await amount(0).inputValue(),'2.5');
        await shared.getByRole('button',{name:'One day',exact:true}).click();
        await shared.locator('[data-schedule-field="single-date"]').fill('2026-10-12');
        await amount(0).fill('4');const latest = await saveMeals();assert.equal(latest.meals[0].planned_servings,4);
        await page.reload();await open();await recipe(0).selectOption('recipe://bread');
        assert.equal(await amount(0).inputValue(),'4','Latest successful save replaces the preference');
        await recipe(0).selectOption('recipe://soup');assert.equal(await amount(0).inputValue(),'0.75');await cancel();

        // Load an older saved meal, whose 2.5 servings differ from the new preference.
        const original = first.meals.find(meal=>meal.recipe_url==='recipe://bread');
        await page.evaluate(meal=>{
            const button=document.createElement('button');button.textContent='Edit saved meal';
            button.dataset.mealId=meal.id;button.dataset.mealName=meal.recipe_name;
            button.addEventListener('click',()=>openMealPlannerEditDialog(button));document.body.appendChild(button);
        },original);
        await page.getByRole('button',{name:'Edit saved meal',exact:true}).click();
        const editAmount=shared.locator('[data-schedule-field="household"]');
        await editAmount.waitFor({state:'visible'});assert.equal(await editAmount.inputValue(),'2.5');
        const editResponse=page.waitForResponse(res=>res.request().method()==='PATCH' && res.url().endsWith('/api/meal-plan/'+original.id));
        await shared.getByRole('button',{name:'Save changes',exact:true}).click();await editResponse;
        await dialog.waitFor({state:'hidden'});
        const stored=await(await context.request.get(base+'/api/meal-plan?recipe_url=recipe://bread')).json();
        assert.equal(stored.meals.find(meal=>meal.id===original.id).planned_servings,2.5);
        assert.equal(stored.meals.reduce((sum,meal)=>sum+meal.planned_servings,0),14);
        await open();await recipe(0).selectOption('recipe://bread');assert.equal(await amount(0).inputValue(),'4');
        // Remember the entered amount even when distribution creates a smaller final meal.
        await recipe(0).selectOption('recipe://rice');await amount(0).fill('2.5');
        await row(0).getByRole('button',{name:'Fill upcoming days',exact:true}).click();
        await row(0).getByRole('button',{name:'Apply distribution',exact:true}).click();
        const distributed=await saveMeals();
        assert.deepEqual(distributed.meals.map(meal=>meal.planned_servings),[2.5,2.5,1]);
        await page.reload();await open();await recipe(0).selectOption('recipe://rice');
        assert.equal(await amount(0).inputValue(),'2.5','The smaller final meal must not replace the entered preference');
        assert.deepEqual(errors,[]);
        console.log('PASS: default 1, independent recipe preferences, date/meal/notes continuity, cancel/failure isolation, latest save, refresh, exact saved totals, existing meal edit, desktop/mobile, clean console');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
