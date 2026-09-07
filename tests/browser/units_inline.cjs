const { chromium } = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[3];
const cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;
(async () => {
    const browser = await chromium.launch({ channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true });
    try {
        const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, colorScheme: 'dark' });
        await context.addCookies([cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], writes = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (message.type() === 'error' && !message.text().includes('422')) errors.push(message.text()); });
        page.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/api/master-data/units/')) writes.push(request.postDataJSON()); });
        const row = id => page.locator(`[data-unit-master-row][data-unit-id="${id}"]`);
        const a = () => row('volume_teaspoon'), b = () => row('volume_tablespoon');
        const name = r => r.locator('[data-unit-row-name]'), category = r => r.locator('[data-unit-row-category]');
        const display = (r, field = 'name') => r.locator(`[data-unit-row-activate="${field}"]`);
        const save = r => r.locator('[data-unit-row-save]'), cancel = r => r.locator('[data-unit-row-cancel]');
        const form = page.locator('[data-unit-master-form]'), alias = form.locator('[data-unit-master-alias-input]');
        const group = r => r.evaluate(e => e.closest('[data-unit-master-category]').dataset.category);
        const screenshot = async filename => { if (artifacts) { fs.mkdirSync(artifacts, { recursive: true }); await page.screenshot({ path: path.join(artifacts, filename) }); } };
        const openCategory = async (r, key = null) => {
            if (key) await display(r, 'category').press(key); else await display(r, 'category').click();
            await page.locator('#unitCategoryMenu').waitFor({state: 'visible'});
            assert(await category(r).isEnabled());
            assert(await page.locator('#unitCategoryMenu [aria-checked="true"]').evaluate(e => e === document.activeElement));
        };
        const selectCategory = async (control, key) => {
            await control.click();
            await page.locator(`#unitCategoryMenu [data-category-id="${key}"]`).click();
        };
        let releaseScript;
        const gate = new Promise(resolve => releaseScript = resolve);
        await page.route('**/js/units.js*', async route => { await gate; await route.continue(); });
        const navigation = page.goto(base + '/admin/master-data/units');
        await display(a()).waitFor();
        assert.equal(await page.title(), 'Units');
        assert.equal(await page.locator('[data-unit-master-row] input, [data-unit-master-row] select').count(), 0);
        const height = (await a().boundingBox()).height;
        assert.equal(height, 68);
        releaseScript(); await navigation; await page.evaluate(() => document.fonts.ready);
        assert.equal((await a().boundingBox()).height, height);
        assert.equal(await page.locator('[data-unit-master-row]').count(), 35);
        await screenshot('units-click-rest.png');

        // The exact reported failure: click the displayed teaspoon, type, cancel.
        await display(a()).click();
        assert(await name(a()).isEnabled()); assert(await name(a()).evaluate(e => e === document.activeElement && e.tagName === 'INPUT' && !e.readOnly));
        assert.equal(await name(a()).inputValue(), 'teaspoon');
        assert(await form.isHidden()); assert(await save(a()).isDisabled()); assert(await cancel(a()).isEnabled());
        await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.type('temporary teaspoon');
        assert.equal(await name(a()).inputValue(), 'temporary teaspoon'); assert(await save(a()).isEnabled());
        await page.keyboard.press('Backspace'); assert.equal(await name(a()).inputValue(), 'temporary teaspoo');
        await cancel(a()).click(); assert.equal(await display(a()).innerText(), 'teaspoon');
        assert.equal(await name(a()).count(), 0); assert.equal(writes.length, 0);

        // Every built-in has the same real controls and all valid categories.
        const registry = await page.locator('#ingredientUnitConfig').evaluate(e => JSON.parse(e.textContent));
        for (const unit of registry.units) {
            const r = row(unit.id);
            await display(r).click();
            assert.equal(await name(r).inputValue(), unit.name); assert(await name(r).isEnabled());
            assert(await category(r).isEnabled()); assert.equal(await category(r).evaluate(e => e.value), unit.category);
            await category(r).click();
            assert.deepEqual(await page.locator('#unitCategoryMenu [role="menuitemradio"]').evaluateAll(options => options.map(o => o.dataset.categoryId)), registry.categories.map(c => c.key));
            await page.keyboard.press('Escape');
            assert.equal(await page.locator('.is-inline-editing').count(), 1);
            await cancel(r).click();
        }

        // Keyboard activation, normal focus navigation, and Escape cancellation.
        await display(a()).focus(); await page.keyboard.press('Enter');
        assert(await name(a()).evaluate(e => e === document.activeElement));
        await page.keyboard.press('Tab'); assert(await a().locator('[data-unit-row-alias="add"]').evaluate(e => e === document.activeElement));
        await page.keyboard.press('Tab'); assert(await category(a()).evaluate(e => e === document.activeElement));
        await page.keyboard.press('Escape'); assert.equal(await name(a()).count(), 0);
        await display(a()).press('Space'); assert(await name(a()).evaluate(e => e === document.activeElement));
        await name(a()).press('Escape');
        await openCategory(a(), 'Enter'); await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
        assert.equal(await category(a()).count(), 0);
        await openCategory(a(), 'Space'); await page.keyboard.press('Escape'); await cancel(a()).click();

        await display(a()).click(); await name(a()).fill(' TABLESPOON ');
        assert(await save(a()).isDisabled()); assert.match(await a().locator('[data-unit-row-name-error]').innerText(), /already accepted/);
        await name(a()).fill(' TBSP '); assert(await save(a()).isDisabled());
        await name(a()).fill('valid teaspoon draft'); await display(b()).click();
        assert.equal(await name(b()).count(), 0); assert.equal(await name(a()).inputValue(), 'valid teaspoon draft');
        assert.match(await a().locator('[data-unit-row-status]').innerText(), /Save or cancel/);
        assert.equal(await page.locator('.is-inline-editing').count(), 1);
        await cancel(a()).click();

        // First click opens the category menu; keyboard selection commits locally only.
        await openCategory(a()); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
        assert.equal(await category(a()).evaluate(e => e.value), 'weight'); assert.equal(await group(a()), 'volume');
        assert.equal(writes.length, 0); assert(await save(a()).isEnabled());
        assert.equal((await a().boundingBox()).height, height);
        const scroll = await page.locator('#appContent').evaluate(e => e.scrollTop);
        await save(a()).click();
        await display(a()).waitFor();
        assert.equal(await group(a()), 'weight'); assert.equal(await display(a(), 'category').innerText(), 'Weight');
        assert.equal(await page.locator('#appContent').evaluate(e => e.scrollTop), scroll);
        assert.equal(await a().locator('.unit-master-source-badge').innerText(), 'Built-in');
        assert.match(await a().locator('.unit-master-usage').innerText(), /3\s+recipes/);
        assert.match(await page.locator('[data-category="volume"] [data-unit-master-category-count-label]').innerText(), /^8 units$/);
        assert.match(await page.locator('[data-category="weight"] [data-unit-master-category-count-label]').innerText(), /^5 units$/);
        const savedRegistry = (await (await context.request.get(base + '/api/master-data/units')).json()).registry;
        assert.equal(savedRegistry.units.filter(u => u.category === 'weight').at(-1).id, 'volume_teaspoon');
        for (const key of ['volume', 'weight']) {
            const units = savedRegistry.units.filter(u => u.category === key);
            assert.deepEqual(units.map(u => u.sort_order), units.map((_, i) => i));
        }
        await page.reload(); assert.equal(await display(a()).innerText(), 'teaspoon'); assert.equal(await group(a()), 'weight');

        // The alias popover shares the active row's draft and single Save/Cancel workflow.
        await display(a()).click();
        await a().locator('[data-unit-row-alias="add"]').click();
        assert(await name(a()).isEnabled()); assert(await form.isVisible());
        assert.equal(await form.locator('[data-unit-master-name]:visible, [data-unit-master-category-select]:visible').count(), 0);
        await alias.fill('TBSP'); assert(await save(a()).isDisabled());
        await alias.fill('tea measure'); await alias.press('Enter');
        await page.route('**/api/master-data/units/suggest', route => route.fulfill({ json: { ok: true, suggestion: { canonical_name: 'BAD AI NAME', category: 'optional', aliases: ['tsp', 'tsps', 'teaspoons', 'tea measure'] } } }), { times: 1 });
        await form.locator('[data-unit-master-ai-suggest]').click();
        await form.getByRole('button', { name: 'Remove alias tea measure', exact: true }).waitFor();
        assert.equal(await name(a()).inputValue(), 'teaspoon'); assert.equal(await category(a()).evaluate(e => e.value), 'weight');
        await form.getByRole('button', { name: 'Close aliases', exact: true }).click();
        await name(a()).fill('measuring teaspoon'); await save(a()).click(); await display(a()).waitFor();
        assert.equal(await display(a()).innerText(), 'measuring teaspoon'); assert.match(await a().locator('.unit-master-aliases').innerText(), /tea measure/);
        await display(a()).click(); await a().locator('[data-unit-row-alias="add"]').click(); await alias.fill('canceled alias');
        await name(a()).fill('canceled name'); await selectCategory(category(a()), 'optional'); await cancel(a()).click();
        assert(await form.isHidden()); assert.equal(await display(a()).innerText(), 'measuring teaspoon'); assert.equal(await group(a()), 'weight');

        await display(a()).click(); await name(a()).fill('server conflict draft');
        await page.route('**/api/master-data/units/volume_teaspoon', route => route.fulfill({ status: 422, json: { ok: false, error: 'Name conflict.', errors: { canonical_name: 'Already assigned to another unit.' } } }), { times: 1 });
        await save(a()).click(); await a().locator('[data-unit-row-name-error]').waitFor();
        assert.equal(await name(a()).inputValue(), 'server conflict draft'); assert(await save(a()).isDisabled());
        await cancel(a()).click();
        await display(a()).click(); await name(a()).fill('filtered draft'); await page.locator('[data-unit-master-search]').fill('tablespoon');
        assert(await a().isVisible()); assert.equal(await name(a()).inputValue(), 'filtered draft');
        await page.locator('[data-unit-master-search]').fill(''); await cancel(a()).click();

        // Delegated clicks keep working after save, filter, and reorder rebuilds.
        let ordered = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/units/volume_teaspoon'));
        await a().locator('[data-unit-master-drag-handle]').press('Home'); await save(a()).click(); assert((await ordered).ok());
        await page.waitForFunction(() => document.querySelector('[data-unit-id="volume_teaspoon"] [data-unit-master-order-number]').textContent === '1');
        ordered = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/units/volume_teaspoon'));
        await a().locator('[data-unit-master-drag-handle]').dragTo(row('weight_gram'), { targetPosition: { x: 50, y: 60 } }); await save(a()).click(); assert((await ordered).ok());
        await display(a()).click(); await name(a()).fill('desktop draft'); await screenshot('units-click-edit.png'); await cancel(a()).click();
        await page.setViewportSize({ width: 390, height: 844 }); await display(a()).click();
        await name(a()).fill('mobile draft'); await selectCategory(category(a()), 'volume');
        assert(await save(a()).isEnabled()); assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        const saveBox = await save(a()).boundingBox(), cancelBox = await cancel(a()).boundingBox();
        assert(saveBox.x + saveBox.width <= cancelBox.x); assert.equal(saveBox.y, cancelBox.y);
        await name(a()).evaluate(e => e.scrollIntoView({ block: 'center' })); await screenshot('units-click-mobile.png'); await cancel(a()).click();
        await page.setViewportSize({ width: 1920, height: 1080 });

        // Reproduce a long-running server's cached static-cell template with fresh JS.
        await page.route('**/admin/master-data/units', async route => {
            const response = await route.fetch();
            const html = (await response.text()).replace('data-unit-row-interaction="click-to-edit"', '')
                .replace(/<section class="unit-master-alias-suggestions"[\s\S]*?<\/section>/, '')
                .replace(/<button[^>]*data-unit-row-activate="(name|category)"[^>]*>([^<]*)<\/button>/g, '<span>$2</span>');
            assert(!html.includes('data-unit-row-activate='));
            await route.fulfill({ response, body: html });
        }, { times: 1 });
        await page.reload(); await display(a()).click();
        assert(await name(a()).evaluate(e => e === document.activeElement)); await name(a()).fill('cached template draft'); await cancel(a()).click();
        await openCategory(a()); await page.keyboard.press('Escape'); await cancel(a()).click();
        await page.reload(); assert.equal(await display(a()).innerText(), 'measuring teaspoon'); assert.equal(await group(a()), 'weight');
        await page.locator('[data-unit-master-add-button]').first().click();
        const draft = page.locator('[data-unit-new-draft]');
        await name(draft).fill('test scoop'); await selectCategory(category(draft), 'volume');
        await save(draft).click(); await draft.waitFor({ state: 'detached' });
        assert.equal(await page.locator('[data-unit-master-row]').count(), 36);
        assert.deepEqual(errors, []);
        console.log('PASS real click/focus/typing, category menu, all seeded rows, Enter/Space/Tab/Escape, Save/Cancel, single-row guard, conflicts, aliases/AI, category order/counts, saved references, refresh, reorder, mobile, cached static template recovery, Add Unit, console');
    } finally { await browser.close(); }
})().catch(error => { console.error(String(error.message).split('Call log:')[0]); console.error(String(error.stack || '').split('\n').filter(line => /^\s+at /.test(line)).slice(0, 6).join('\n')); process.exitCode = 1; });
