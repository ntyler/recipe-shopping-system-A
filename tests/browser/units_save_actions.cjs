const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;

(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: 1920, height: 1080}, colorScheme: 'dark'});
        await context.addCookies([cookie]);
        const page = await context.newPage(), types = await context.newPage();
        page.setDefaultTimeout(10000); types.setDefaultTimeout(10000);
        const errors = [], writes = [];
        for (const tab of [page, types]) {
            tab.on('pageerror', e => errors.push(e.message));
            tab.on('console', m => { if (['error', 'warning'].includes(m.type()) && !/422|503/.test(m.text())) errors.push(m.text()); });
        }
        page.on('request', r => { if (['PUT', 'PATCH'].includes(r.method()) && r.url().includes('/api/master-data/units/')) writes.push(r.postDataJSON()); });
        await types.goto(base + '/admin/master-data/types'); await page.goto(base + '/admin/master-data/units');
        await page.evaluate(() => document.fonts.ready); await types.evaluate(() => document.fonts.ready);
        assert.equal(await page.title(), 'Units'); assert.equal(await types.title(), 'Types');
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        assert.equal(await page.locator('[data-unit-master-row]').count(), 35);
        assert.equal(await page.getByRole('button', {name: /^Edit unit/}).count(), 0);
        assert.equal(await page.locator('[data-unit-row-save]:visible').count(), 35);
        assert.equal(await page.locator('[data-unit-row-save]:enabled').count(), 0);
        assert.equal(await page.locator('[data-unit-row-cancel]:visible').count(), 0);
        const row = page.locator('[data-unit-master-row][data-unit-id="volume_teaspoon"]');
        const name = row.locator('[data-unit-row-name]'), category = row.locator('[data-unit-row-category]');
        const display = row.locator('[data-unit-row-activate="name"]');
        const save = row.locator('[data-unit-row-save]'), cancel = row.locator('[data-unit-row-cancel]');
        const handle = row.locator('[data-unit-master-drag-handle]');
        const typeRow = types.locator('[data-type-master-row]').first();
        const typeSave = typeRow.locator('[data-type-master-row-save]');
        const shot = async (tab, filename) => { if (artifacts) { fs.mkdirSync(artifacts, {recursive: true}); await tab.screenshot({path: path.join(artifacts, filename)}); } };
        const registry = async () => (await (await context.request.get(base + '/api/master-data/units')).json()).registry;
        const savedUnit = async () => (await registry()).units.find(u => u.id === 'volume_teaspoon');
        const scroll = () => page.locator('#appContent').evaluate(e => e.scrollTop);
        const focusIs = async control => assert(await control.evaluate(e => e === document.activeElement));
        const choose = async key => { await category.click(); await page.locator(`#unitCategoryMenu [data-category-id="${key}"]`).click(); };
        const metrics = control => control.evaluate(async e => {
            getComputedStyle(e).opacity;
            await Promise.all(e.getAnimations().map(animation => animation.finished.catch(() => {})));
            const style = getComputedStyle(e), box = e.getBoundingClientRect();
            const cell = e.closest('[role="cell"]').getBoundingClientRect(), row = e.closest('[role="row"]').getBoundingClientRect();
            const properties = ['display', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'textAlign', 'color', 'opacity', 'backgroundColor', 'borderColor', 'borderWidth', 'borderRadius', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft'];
            return {style: Object.fromEntries(properties.map(p => [p, style[p]])), width: box.width, height: box.height,
                x: box.x, cellX: cell.x, cellWidth: cell.width, offsetX: box.x - cell.x, centerY: box.y + box.height / 2 - row.y - row.height / 2};
        });
        const initialTypeStyle = await metrics(typeSave);
        for (const width of [1920, 1440, 1100, 390, 320]) {
            await page.setViewportSize({width, height: 1080}); await types.setViewportSize({width, height: 1080});
            const actual = await metrics(save), expected = await metrics(typeSave);
            assert.deepEqual(actual.style, expected.style, `Types Save styles at ${width}px`);
            assert.equal(actual.height, expected.height, `Save height at ${width}px`);
            assert.equal(actual.offsetX, expected.offsetX, `Save slot at ${width}px`);
            if (width > 760) {
                for (const prop of ['width', 'x', 'cellX', 'cellWidth', 'centerY']) assert(Math.abs(actual[prop] - expected[prop]) < 0.05, `${prop} at ${width}px: ${actual[prop]} vs ${expected[prop]}`);
            }
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        }
        await page.setViewportSize({width: 1920, height: 1080}); await types.setViewportSize({width: 1920, height: 1080});
        await shot(types, 'types-action-reference.png'); await shot(page, 'units-action-rest.png');
        assert.deepEqual(await metrics(typeSave), initialTypeStyle);
        const height = (await row.boundingBox()).height, restingSave = await metrics(save);

        // Each field dirties the same Save action; Escape cancels without a write.
        await display.press('Enter'); await focusIs(name); assert(await save.isDisabled());
        await name.fill('teaspoon draft'); assert(await save.isEnabled());
        const originalTypeName = await typeRow.locator('[data-type-master-row-name]').inputValue();
        await typeRow.locator('[data-type-master-row-name]').fill('Main draft');
        assert.deepEqual((await metrics(save)).style, (await metrics(typeSave)).style, 'Dirty Save matches Types');
        await typeRow.locator('[data-type-master-row-name]').fill(originalTypeName);
        await name.fill('TBSP'); assert(await save.isDisabled());
        assert.equal((await row.boundingBox()).height, height);
        assert.match(await row.locator('[data-unit-row-name-error]').innerText(), /already accepted/);
        await shot(page, 'units-action-validation.png');
        await name.press('Escape'); assert(await save.isDisabled()); assert(await cancel.isHidden()); assert.equal(writes.length, 0);
        await display.click(); await choose('weight'); assert(await save.isEnabled());
        await category.press('Escape'); assert.equal((await savedUnit()).category, 'volume');

        // Order is a draft, including undoing a move or canceling it through Escape.
        const originalIds = (await registry()).units.filter(u => u.category === 'volume').map(u => u.id);
        await handle.press('ArrowDown'); assert(await save.isEnabled()); assert.equal(writes.length, 0);
        assert.deepEqual((await registry()).units.filter(u => u.category === 'volume').map(u => u.id), originalIds);
        await handle.press('ArrowUp'); assert(await save.isDisabled());
        await handle.press('End'); assert(await save.isEnabled());
        const cancelScroll = await scroll(); await handle.press('Escape');
        assert.equal(await scroll(), cancelScroll); assert(await save.isDisabled());
        assert.deepEqual(await page.locator('[data-category="volume"] [data-unit-master-row]').evaluateAll(rows => rows.map(r => r.dataset.unitId)), originalIds);

        // Save all four changes in one transaction; keep the row on failures.
        await handle.press('ArrowDown'); await name.fill('measuring teaspoon'); await choose('weight');
        await row.getByRole('button', {name: 'Manage aliases', exact: true}).click();
        const form = page.locator('[data-unit-master-form]');
        await form.locator('[data-unit-master-alias-input]').fill('tea measure');
        await form.locator('[data-unit-master-alias-input]').press('Enter');
        await form.getByRole('button', {name: 'Close aliases', exact: true}).click();
        assert(await save.isEnabled());
        await page.route('**/api/master-data/units/volume_teaspoon', route => route.fulfill({status: 422, json: {ok: false, error: 'Name conflict.', errors: {canonical_name: 'This name was just taken.'}}}), {times: 1});
        const beforeError = await scroll(), beforeErrorHeight = (await row.boundingBox()).height;
        await save.click(); await row.locator('[data-unit-row-name-error]').waitFor(); await focusIs(name);
        assert.equal(await scroll(), beforeError); assert.equal((await row.boundingBox()).height, beforeErrorHeight);
        assert.equal((await savedUnit()).name, 'teaspoon'); assert.equal((await savedUnit()).category, 'volume');
        await name.fill('precise teaspoon');
        let release;
        const gate = new Promise(resolve => release = resolve);
        await page.route('**/api/master-data/units/volume_teaspoon', async route => { await gate; await route.continue(); }, {times: 1});
        const savingScroll = await scroll();
        await save.press('Enter');
        await page.waitForFunction(() => document.querySelector('[data-unit-id="volume_teaspoon"][role="row"]').getAttribute('aria-busy') === 'true');
        assert(await save.isDisabled()); assert(await name.isDisabled()); assert(await cancel.isDisabled());
        assert.equal((await row.boundingBox()).height, height);
        await shot(page, 'units-action-saving.png'); release(); await display.waitFor();
        assert(await save.isDisabled()); assert(await cancel.isHidden()); await focusIs(display);
        assert.equal(await scroll(), savingScroll); assert.equal((await row.boundingBox()).height, height);
        assert.equal(await row.locator('[data-unit-row-status]').innerText(), 'Saved');
        assert.equal(writes.length, 2); assert.equal(writes[1].position, 2);
        const saved = await savedUnit(); assert.equal(saved.name, 'precise teaspoon'); assert.equal(saved.category, 'weight');
        assert.equal(saved.sort_order, 1); assert(saved.aliases.includes('tea measure'));
        assert.equal(await row.evaluate(e => e.closest('[data-unit-master-category]').dataset.category), 'weight');
        assert.equal(await row.locator('[data-unit-master-order-number]').innerText(), '2');
        assert.equal(await page.locator('[data-category="volume"] [data-unit-master-category-count-label]').innerText(), '8 units');
        assert.equal(await page.locator('[data-category="weight"] [data-unit-master-category-count-label]').innerText(), '5 units');
        await row.scrollIntoViewIfNeeded(); await shot(page, 'units-action-success.png');
        await page.reload(); assert.deepEqual(await savedUnit(), saved); assert(await save.isDisabled());
        assert.equal((await metrics(save)).style.opacity, restingSave.style.opacity);

        // Mobile keyboard and Cancel remain in the shared action slots.
        await page.setViewportSize({width: 390, height: 844});
        await display.click(); await name.fill('mobile teaspoon draft');
        await name.evaluate(e => e.scrollIntoView({block: 'center'}));
        assert(await save.isEnabled()); assert(await cancel.isVisible());
        await shot(page, 'units-action-mobile.png');
        await cancel.click(); assert(await save.isDisabled()); assert(await cancel.isHidden());
        await focusIs(display); assert.equal((await savedUnit()).name, 'precise teaspoon');

        // Types still saves through its original flow and returns to disabled Save.
        const unusedType = types.locator('[data-type-master-row]').last();
        const typeName = unusedType.locator('[data-type-master-row-name]'), originalName = await typeName.inputValue();
        await typeName.fill('Unused type QA'); await unusedType.locator('[data-type-master-row-save]').click();
        await types.waitForFunction(() => [...document.querySelectorAll('[data-type-master-row-name]')].some(e => e.value === 'Unused type QA') && !document.querySelector('[data-type-master-row-save]:enabled'));
        await types.reload(); assert(await types.locator('[data-type-master-row-name]').evaluateAll(inputs => inputs.some(e => e.value === 'Unused type QA')));
        const updatedType = unusedType;
        await updatedType.locator('[data-type-master-row-name]').fill(originalName); await updatedType.locator('[data-type-master-row-save]').click();
        assert.deepEqual(errors, []);
        console.log('PASS Types/Units exact Save styling and geometry, disabled/dirty/saving/success/error, four-field atomic save, local reorder/cancel, keyboard, mobile, stable scroll/row height, aliases, counts, persistence, and Types save regression');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
