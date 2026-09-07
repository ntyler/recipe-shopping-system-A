const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;

(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        // Browser plugin not available: exercise the real app with isolated fixtures.
        // Flow: Types -> compact phone rows -> expand/edit/cancel/save/usage/reorder -> desktop.
        const context = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true, colorScheme: 'dark'});
        await context.addCookies([cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => { if (['error', 'warning'].includes(m.type())) errors.push(m.text()); });
        const row = id => page.locator(`[data-type-master-row][data-type-id="${id}"]`);
        const main = row('main');
        const name = r => r.locator('[data-type-master-row-name]');
        const toggle = r => r.locator('[data-type-master-row-toggle]');
        const summary = r => r.locator('[data-type-master-row-summary]');
        const save = r => r.locator('[data-type-master-row-save]');
        const cancel = r => r.locator('[data-type-master-row-cancel]');
        const handle = r => r.locator('[data-type-master-drag-handle]');
        const registry = async () => (await (await context.request.get(base + '/api/master-data/types')).json()).registry;
        const original = await registry();
        const ids = original.types.map(t => t.id);
        const originalName = original.types.find(t => t.id === 'main').name;
        const shot = async file => {
            if (artifacts) { fs.mkdirSync(artifacts, {recursive:true}); await page.screenshot({path:path.join(artifacts,file)}); }
        };
        const reveal = r => r.evaluate(e => e.scrollIntoView({block:'center'}));
        const expanded = async r => await toggle(r).getAttribute('aria-expanded') === 'true';
        const assertCollapsed = async r => {
            assert(!await expanded(r)); assert(await summary(r).isVisible());
            for (const selector of ['[data-type-master-row-name]', '[data-type-master-order-number]', '.unit-master-source-badge', '.type-master-row-actions']) {
                assert(await r.locator(selector).isHidden(), selector);
            }
            assert(await r.locator('.unit-master-usage').isVisible());
        };
        for (const width of [320, 375, 390, 480, 600]) {
            await page.setViewportSize({width,height:844});
            await page.goto(base + '/admin/master-data/units');
            const reference = await page.locator('[data-unit-master-row]').first().evaluate(e => {
                const s = getComputedStyle(e); return {height:e.getBoundingClientRect().height, padding:s.padding, border:s.borderBottomColor};
            });
            await page.goto(base + '/admin/master-data/types'); await page.evaluate(() => document.fonts.ready);
            const beforeEdit = await registry();
            assert.equal(await page.title(), 'Types'); assert(page.url().endsWith('/admin/master-data/types'));
            assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
            assert.equal(await page.locator('[data-type-master-row]').count(), ids.length);
            if (width === 480) await shot('types-phone-full-480.png');
            await reveal(main);
            for (const id of ids) {
                const r = row(id); await assertCollapsed(r);
                const geometry = await r.evaluate(e => {
                    const rect = selector => {const b = e.querySelector(selector).getBoundingClientRect(); return {x:b.x,y:b.y,right:b.right,width:b.width,height:b.height};};
                    const s = getComputedStyle(e);
                    return {height:e.getBoundingClientRect().height,padding:s.padding,border:s.borderBottomColor,
                        handle:rect('[data-type-master-drag-handle]'),name:rect('[data-type-master-row-summary]'),usage:rect('.unit-master-usage'),toggle:rect('[data-type-master-row-toggle]')};
                });
                assert.equal(geometry.height, reference.height); assert.equal(geometry.padding, reference.padding); assert.equal(geometry.border, reference.border);
                for (const b of [geometry.handle,geometry.toggle]) assert(b.width >= 44 && b.height >= 44);
                assert(geometry.handle.right <= geometry.name.x && geometry.name.right <= geometry.usage.x + 1 && geometry.usage.right <= geometry.toggle.x + 1);
                assert.equal(geometry.handle.y,geometry.toggle.y);
            }
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
            await shot(`types-phone-rows-${width}.png`);
            await summary(main).tap(); assert(await expanded(main)); assert(await name(main).isVisible());
            assert(await main.locator('.unit-master-source-badge').isVisible());
            assert(await save(main).isDisabled()); assert(await cancel(main).isVisible());
            if (width === 480) await shot('types-phone-expanded-480.png');
            await name(main).fill('Phone draft'); await toggle(main).tap(); await assertCollapsed(main);
            assert.equal(await summary(main).innerText(),'Phone draft'); assert.deepEqual(await registry(),beforeEdit);
            await summary(main).tap(); assert.equal(await name(main).inputValue(),'Phone draft');
            await cancel(main).tap(); await assertCollapsed(main); assert.equal(await summary(main).innerText(),originalName);
            await toggle(main).tap(); await name(main).fill(''); await save(main).tap();
            assert(await main.locator('[data-type-master-row-error]').isVisible()); assert.equal(await name(main).getAttribute('aria-invalid'),'true');
            await cancel(main).tap(); await toggle(main).tap();
            await name(main).fill(`Phone main ${width}`); await save(main).tap();
            await page.waitForFunction(expected => document.querySelector('[data-type-master-row][data-type-id="main"] [data-type-master-row-name]').value === expected && document.querySelector('[data-type-master-row][data-type-id="main"] [data-type-master-row-save]').disabled, `Phone main ${width}`);
            assert.equal((await registry()).types.find(t=>t.id==='main').name,`Phone main ${width}`);
            await name(main).fill(originalName); await save(main).tap();
            await page.waitForFunction(expected => document.querySelector('[data-type-master-row][data-type-id="main"] [data-type-master-row-name]').value === expected && document.querySelector('[data-type-master-row][data-type-id="main"] [data-type-master-row-save]').disabled,originalName);
            await toggle(main).tap(); await assertCollapsed(main);
            const usage = main.locator('[data-type-master-usage-button]');
            assert(await usage.isVisible()); await usage.tap();
            const dialog = page.locator('[data-type-master-usage-dialog]');
            await dialog.getByRole('link').first().waitFor();
            await dialog.locator('[data-type-master-usage-close]').first().tap(); assert(await dialog.isHidden()); await assertCollapsed(main);
            const search = page.locator('[data-type-master-search]');
            await search.fill(originalName); assert.equal(await page.locator('[data-type-master-row]:visible').count(),1);
            assert.equal(await handle(main).getAttribute('aria-disabled'),'true'); await search.fill('');
            assert.deepEqual((await registry()).types.map(t=>({id:t.id,name:t.name,order:t.sort_order})), original.types.map(t=>({id:t.id,name:t.name,order:t.sort_order})));
        }

        await page.setViewportSize({width:390,height:844}); await page.reload(); await reveal(main);
        // A real touch drag saves only order and keeps the summary collapsed.
        const start = await handle(main).boundingBox(), end = await row(ids[1]).boundingBox();
        const touch = await context.newCDPSession(page);
        await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:start.x+22,y:start.y+22,id:1}]});
        await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:start.x+22,y:end.y+end.height-8,id:1}]});
        await page.waitForFunction(()=>document.querySelector('.is-row-drop-after, .is-row-drop-before'));
        await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await touch.detach();
        await page.waitForFunction(()=>JSON.parse(document.getElementById('ingredientTypeConfig').textContent).types[0].id !== 'main' && document.querySelector('[data-type-master-row][data-type-id="main"]').getAttribute('aria-busy') === 'false');
        await assertCollapsed(main); assert.notEqual((await registry()).types[0].id,'main');
        await handle(main).press('Home');
        await page.waitForFunction(()=>JSON.parse(document.getElementById('ingredientTypeConfig').textContent).types[0].id === 'main' && document.querySelector('[data-type-master-row][data-type-id="main"]').getAttribute('aria-busy') === 'false');
        await page.reload(); assert.deepEqual((await registry()).types.map(t=>t.id),ids);

        // Newly created/custom rows retain the disclosure controls after a server render.
        await page.locator('[data-type-master-add-button]').first().tap();
        const create = page.locator('[data-type-master-create-form]');
        await create.locator('[data-type-master-create-name]').fill('Long custom ingredient role for garnish');
        await create.locator('[data-type-master-create-submit]').tap(); await create.waitFor({state:'hidden'});
        const custom = (await registry()).types.find(t=>t.custom);
        const customRow = row(custom.id); await reveal(customRow); await assertCollapsed(customRow);
        await summary(customRow).tap(); assert(await customRow.locator('[data-type-master-row-delete]').isVisible());
        assert.equal((await save(customRow).boundingBox()).y, (await cancel(customRow).boundingBox()).y);
        page.once('dialog', d=>d.accept()); await customRow.locator('[data-type-master-row-delete]').tap(); await customRow.waitFor({state:'detached'});
        const add = page.locator('[data-type-master-add-button]').last(); await add.evaluate(e=>e.scrollIntoView({block:'end'}));
        const addBox = await add.boundingBox(), nav = await page.locator('.app-mobile-bottom-nav').boundingBox();
        assert(addBox.y+addBox.height <= nav.y);
        assert.deepEqual((await registry()).types.map(t=>t.id),ids); assert.deepEqual(errors,[]);

        const desktop = await browser.newContext({viewport:{width:1920,height:1080},colorScheme:'dark'});
        await desktop.addCookies([cookie]); const desk = await desktop.newPage();
        desk.on('pageerror',e=>errors.push(e.message));
        await desk.goto(base+'/admin/master-data/types');
        assert(await desk.getByRole('columnheader',{name:'Order',exact:true}).isVisible());
        for (const id of ids) {
            const r = desk.locator(`[data-type-master-row][data-type-id="${id}"]`);
            assert.equal((await r.boundingBox()).height,68);
            assert(await r.locator('[data-type-master-order-number]').isVisible());
            assert(await r.locator('[data-type-master-row-name]').isEditable());
            assert(await r.locator('[data-type-master-row-toggle]').isHidden());
            assert(await r.locator('[data-type-master-row-cancel]').isHidden());
        }
        if (artifacts) await desk.screenshot({path:path.join(artifacts,'types-desktop.png')});
        assert.deepEqual(errors,[]);
        await desktop.close(); await context.close();
        console.log('PASS compact phone rows at 320/375/390/480/600px; expand/edit/dirty collapse/Cancel/validation/Save; usage links; filtering; touch and keyboard reorder persistence; custom create/delete; footer clearance; desktop Order and controls; console health.');
    } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
