const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
    // Browser plugin not available: production UI and isolated real APIs.
    // Flow: two people, one lunch, two recipes -> customize shares -> save -> reopen.
    const browser = await chromium.launch({channel:process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome',headless:true});
    try {
        const context = await browser.newContext({viewport:{width:1440,height:1200}});
        await context.addCookies([cookie]);
        const members = [];
        for (const name of ['Nate','Gary']) {
            const response = await context.request.post(base+'/api/meal-plan/members',{data:{name}});
            assert.equal(response.status(),201);members.push((await response.json()).member);
        }
        const page = await context.newPage(), errors = [], posts = [];
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => {if (['error','warning'].includes(m.type())) errors.push(m.text());});
        page.on('request', r => {if (r.method()==='POST' && r.url().endsWith('/batches/bulk')) posts.push(r.postDataJSON());});
        await page.goto(base+'/editor-qa');
        assert.equal(page.url(),base+'/editor-qa');assert.equal(await page.title(),'AI Pantry — Meal Planner');
        assert(await page.getByRole('heading',{name:'Meal Planner',exact:true}).isVisible());
        const dialog = page.locator('#mealPlannerDialog'), shared = dialog.locator('[data-meal-shared-form]');
        const row = i => dialog.locator('[data-meal-editor]').nth(i);
        const custom = i => row(i).locator('[data-meal-editor-form]');
        const portion = (form,member) => form.locator(`[data-schedule-field="family"][data-member="${member.id}"][data-meal="lunch"]`);
        const save = dialog.locator('[data-meal-batch-save]'), total = dialog.locator('[data-meal-batch-help]');
        const ready = () => page.waitForFunction(() => {const s=document.getElementById('mealPlannerDialog').mealPlanScheduleState;return s.panel && !s.panel.ui.loading && s.entries.every(e=>!e.panel?.ui.loading);});
        const add = async name => {await dialog.locator('[data-meal-editor-add]').click();await dialog.locator('[data-meal-editor]').last().locator('[name="recipe_url"]').selectOption('recipe://'+name);};
        const screenshot = async name => {const dir=process.env.AI_PANTRY_BROWSER_ARTIFACTS;if(dir){fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,name)});}};
        await page.getByRole('button',{name:'Add Meals',exact:true}).click();await ready();
        await row(0).locator('[name="recipe_url"]').selectOption('recipe://bread');await add('soup');
        await shared.locator('[data-schedule-field="meal"][data-meal="dinner"]').uncheck();
        await shared.locator('[data-schedule-field="meal"][data-meal="lunch"]').check();
        await shared.getByRole('button',{name:'By family member',exact:true}).click();
        for (const member of members) assert.equal(await portion(shared,member).inputValue(),'1');
        for (const i of [0,1]) assert.match(await row(i).locator('[data-meal-editor-summary]').textContent(),/1 meal · 1 servings \(1 per meal\).*Share of meal total/);
        assert.equal(await total.textContent(),'2 recipes · 1 meal · 2 servings being planned');
        assert.equal(await save.textContent(),'Save 1 Meal');
        assert.match(await shared.locator('[data-schedule-summary]').textContent(),/2 servings.*divided between recipes/);
        await dialog.evaluate(e=>{e.scrollTop=0;});await screenshot('shared-lunch-desktop.png');
        await page.setViewportSize({width:390,height:844});
        assert(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1));await screenshot('shared-lunch-mobile.png');
        await page.setViewportSize({width:1440,height:1200});
        await row(1).locator('[data-meal-editor-customize]').click();
        for (const member of members) assert.equal(await portion(custom(1),member).inputValue(),'0.5');
        await portion(custom(1),members[0]).fill('0.75');
        assert.match(await row(0).locator('[data-meal-editor-summary]').textContent(),/0.75 servings/);
        assert.equal(await total.textContent(),'2 recipes · 1 meal · 2 servings being planned');
        await portion(custom(1),members[0]).fill('1.25');await save.click();
        assert.equal(posts.length,0,'Overallocating one person cannot save even if the combined total fits');
        assert.match(await row(0).locator('[data-meal-editor-error]').textContent(),/exceed.*Nate/);
        await portion(custom(1),members[0]).fill('0.75');
        await row(1).locator('[data-meal-editor-reset]').click();
        await add('rice');assert.match(await total.textContent(),/3 recipes · 1 meal · 2 servings/);
        await row(2).locator('[data-meal-editor-remove]').click();
        // Small valid shares must remain editable when division takes them
        // below the old number input minimum of 0.01.
        for (const member of members) await portion(shared,member).fill('0.01');
        await row(1).locator('[data-meal-editor-customize]').click();
        for (const member of members) {
            assert.equal(await portion(custom(1),member).inputValue(),'0.005');
            assert(await portion(custom(1),member).evaluate(input=>input.checkValidity()));
        }
        await row(1).locator('[data-meal-editor-reset]').click();
        for (const member of members) await portion(shared,member).fill('1');
        await row(1).locator('[data-meal-editor-customize]').click();
        await portion(custom(1),members[0]).fill('0.75');
        const response = page.waitForResponse(r=>r.url().endsWith('/batches/bulk') && r.request().method()==='POST');
        await save.click();const saved=await(await response).json();await dialog.waitFor({state:'hidden'});
        assert.equal(saved.ok,true);assert.equal(posts.length,1);assert.equal(saved.meals.length,2);
        assert.deepEqual(saved.meals.map(m=>m.planned_servings),[0.75,1.25]);
        assert.deepEqual(saved.batches.map(b=>b.batch_servings),[0.75,1.25]);
        for (const member of members) assert.equal(saved.meals.reduce((sum,m)=>sum+m.member_portions.find(p=>p.member_id===member.id).servings,0),1);
        await page.reload();
        const stored = await(await context.request.get(base+'/api/meal-plan?recipe_url=recipe://bread')).json();
        assert.equal(stored.meals[0].planned_servings,0.75);
        // The QA host has no calendar cards: mount a normal edit trigger for the
        // saved meal, then exercise the real edit controller and form.
        await page.evaluate(id=>{const b=document.createElement('button');b.textContent='Edit saved lunch';b.dataset.mealId=id;b.onclick=()=>openMealPlannerEditDialog(b,'meal');document.body.appendChild(b);},saved.meals[0].id);
        await page.getByRole('button',{name:'Edit saved lunch',exact:true}).click();await ready();
        assert.equal(await portion(shared,members[0]).inputValue(),'0.25');
        assert.equal(await portion(shared,members[1]).inputValue(),'0.5');
        assert.match(await shared.locator('[data-schedule-summary]').textContent(),/¾ servings/);
        await screenshot('saved-lunch-shares.png');
        const update = page.waitForResponse(r=>r.request().method()==='PATCH' && r.url().endsWith('/api/meal-plan/'+saved.meals[0].id));
        await shared.getByRole('button',{name:'Save changes',exact:true}).click();
        assert.equal((await update).status(),200);await dialog.waitFor({state:'hidden'});
        assert.deepEqual(errors,[]);
        console.log('PASS: two-person lunch divided across recipes; custom shares, over-allocation protection, exact totals, saved/reopened portions, desktop/mobile, clean console');
    } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
