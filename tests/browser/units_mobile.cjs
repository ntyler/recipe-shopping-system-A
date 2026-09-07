const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;

(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        // Browser plugin not available: use the repository's authenticated Playwright harness.
        // Flow: Units -> expand one phone row -> edit/validate/save/cancel/reorder -> persisted registry.
        const context = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true, colorScheme: 'dark'});
        await context.addCookies([cookie]);
        const categoryName = 'Special measuring units with a very long category name';
        const createdCategory = await context.request.post(base + '/api/master-data/unit-categories', {data: {name: categoryName}});
        assert(createdCategory.ok());
        const categoryId = (await createdCategory.json()).category_id;
        const fixtures = [
            {canonical_name: 'Very long canonical measurement name for a serving spoon', category: categoryId, aliases: ['one generous serving spoon', 'longalias'.repeat(6)]},
            {canonical_name: 'unbroken'.repeat(7), category: 'volume', aliases: []},
            {canonical_name: 'many aliases measure', category: 'volume', aliases: Array.from({length: 50}, (_, i) => `many aliases variant ${i}`)},
        ];
        for (const fixture of fixtures) {
            const response = await context.request.post(base + '/api/master-data/units', {data: fixture});
            assert(response.ok(), await response.text());
            fixture.id = (await response.json()).unit_id;
        }
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], writes = [];
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => { if (['error', 'warning'].includes(m.type()) && !m.text().includes('422')) errors.push(m.text()); });
        page.on('request', r => { if (r.method() === 'PUT' && r.url().includes('/api/master-data/units/')) writes.push(r.postDataJSON()); });
        const row = id => page.locator(`[data-unit-master-row][data-unit-id="${id}"]`);
        const unit = row('volume_teaspoon');
        const display = r => r.locator('[data-unit-row-activate="name"]');
        const name = r => r.locator('[data-unit-row-name]');
        const save = r => r.locator('[data-unit-row-save]');
        const cancel = r => r.locator('[data-unit-row-cancel]');
        const handle = r => r.locator('[data-unit-master-drag-handle]');
        const toggle = r => r.locator('[data-unit-row-toggle]');
        const expanded = async r => await toggle(r).getAttribute('aria-expanded') === 'true';
        const expand = async r => { if (!await expanded(r)) await toggle(r).tap(); assert(await expanded(r)); };
        const collapse = async r => { if (await expanded(r)) await toggle(r).tap(); assert(!await expanded(r)); };
        const shot = async file => { if (artifacts) { fs.mkdirSync(artifacts, {recursive: true}); await page.screenshot({path: path.join(artifacts, file)}); } };
        const registry = async () => (await (await context.request.get(base + '/api/master-data/units')).json()).registry;
        const saved = async () => (await registry()).units.find(u => u.id === 'volume_teaspoon');
        const reveal = r => r.evaluate(e => e.scrollIntoView({block: 'center'}));
        const geometry = r => r.evaluate(e => {
            const rect = n => { const b = n.getBoundingClientRect(); return {x: b.x, y: b.y, right: b.right, bottom: b.bottom, width: b.width, height: b.height}; };
            return {row: rect(e), cells: [...e.children].map(n => ({...rect(n), label: getComputedStyle(n, '::before').content})),
                order: rect(e.querySelector('.unit-master-order-cell')), name: rect(e.querySelector('.unit-master-name-cell')),
                toggle: rect(e.querySelector('[data-unit-row-toggle]')), usage: rect(e.querySelector('.unit-master-usage')),
                aliases: rect(e.querySelector('.unit-master-aliases')), chips: [...e.querySelectorAll('code')].map(rect),
                plus: rect(e.querySelector('[data-unit-row-alias]')), background: getComputedStyle(e).backgroundColor,
                padding: getComputedStyle(e).padding, divider: getComputedStyle(e).borderBottomColor};
        });
        const viewportFits = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
        const transparent = async r => assert.equal(await r.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
        const volumeOrder = () => page.locator('[data-category="volume"] [data-unit-master-row]').evaluateAll(rows => rows.map(r => r.dataset.unitId));
        const assertCollapsed = async r => {
            assert(!await expanded(r)); assert(await display(r).isVisible());
            for (const selector of ['.unit-master-aliases', '.unit-master-category-cell', '.unit-master-source-badge', '.unit-master-action-cell']) {
                assert(await r.locator(selector).isHidden(), `${selector} is hidden while collapsed`);
            }
            assert.equal(await name(r).count(), 0);
        };
        for (const width of [320, 375, 390, 430]) {
            await page.setViewportSize({width, height: 844});
            await page.goto(base + '/admin/master-data/store-sections');
            const reference = await page.locator('[data-store-section-master-row]').first().evaluate(e => ({height: e.getBoundingClientRect().height, padding: getComputedStyle(e).padding, divider: getComputedStyle(e).borderBottomColor}));
            await page.goto(base + '/admin/master-data/units');
            await page.evaluate(() => document.fonts.ready);
            await shot(`units-mobile-page-${width}.png`);
            assert.equal(await page.title(), 'Units'); assert(page.url().endsWith('/admin/master-data/units'));
            assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
            assert.equal(await page.locator('[data-unit-master-row]').count(), 38);
            assert.equal(await page.locator('[data-unit-row-save]:visible').count(), 0);
            assert.equal(await page.locator('[data-unit-row-toggle][aria-expanded="true"]').count(), 0);
            assert.match(await page.locator('[data-category="volume"] > header').innerText(), /Volume[\s\S]*\d+ units/);
            await reveal(unit);
            const compactRow = row('volume_tablespoon');
            await assertCollapsed(compactRow);
            const compact = await geometry(compactRow);
            assert(compact.row.height <= 72, `Compact resting row at ${width}px: ${compact.row.height}`);
            assert.equal(compact.row.height, reference.height);
            assert.equal(compact.padding, reference.padding);
            assert.equal(compact.divider, reference.divider);
            assert.equal(compact.background, 'rgba(0, 0, 0, 0)');
            assert(compact.order.x < compact.name.x && compact.name.right <= compact.toggle.x + 1);
            assert(Math.max(compact.order.y, compact.name.y, compact.toggle.y) < Math.min(compact.order.bottom, compact.name.bottom, compact.toggle.bottom), 'Header controls stay on one horizontal line');
            assert(compact.toggle.right <= compact.row.right && compact.row.right - compact.toggle.right <= 16);
            assert(compact.cells.filter(c => c.height > 0).every(c => ['none', 'normal'].includes(c.label)), 'No repeated column labels');
            assert(compact.toggle.width >= 40 && compact.toggle.height >= 40);
            assert((await handle(compactRow).boundingBox()).height >= 40);
            await shot(`units-mobile-rest-${width}.png`);

            // Long names remain compact while collapsed; all details fit when explicitly expanded.
            for (const fixture of fixtures) {
                const r = row(fixture.id);
                await reveal(r); await assertCollapsed(r);
                assert.equal(await display(r).innerText(), fixture.canonical_name);
                assert((await r.boundingBox()).height <= 72, 'Long names do not turn collapsed rows into cards');
                assert(await viewportFits());
                await display(r).tap(); assert(await expanded(r));
                assert.equal(await page.locator('[data-unit-row-toggle][aria-expanded="true"]').count(), 1);
                assert.equal(await display(r).innerText(), fixture.canonical_name);
                assert.equal(await name(r).count(), 0, 'Expansion does not activate editing');
                assert(await save(r).isHidden()); assert(await cancel(r).isHidden());
                const boxes = await geometry(r);
                assert(boxes.aliases.y >= Math.max(boxes.order.bottom, boxes.name.bottom, boxes.toggle.bottom));
                assert.equal(boxes.chips.length, fixture.aliases.length);
                assert(boxes.chips.every(c => c.x >= boxes.row.x && c.right <= boxes.row.right && c.width > 0));
                assert(boxes.plus.width >= 44 && boxes.plus.height >= 44 && boxes.plus.right <= boxes.row.right);
                for (const chip of boxes.chips) assert(chip.right <= boxes.plus.x || chip.bottom <= boxes.plus.y || chip.y >= boxes.plus.bottom);
                assert(await r.locator('.unit-master-source-badge').isVisible());
                assert(await r.locator('[data-unit-row-activate="category"]').isVisible());
                if (fixture.category === categoryId) assert.equal(await r.locator('[data-unit-row-activate="category"]').innerText(), categoryName);
                await transparent(r); assert(await viewportFits());
                await reveal(r); await shot(`units-mobile-details-${width}-${fixtures.indexOf(fixture)}.png`);
                await collapse(r); await assertCollapsed(r);
            }

            // Row whitespace and chevron toggle details without a large separate editor.
            await reveal(unit);
            await unit.tap({position: {x: 2, y: (await unit.boundingBox()).height / 2}});
            assert(await expanded(unit));
            await display(unit).tap();
            assert(await name(unit).isVisible()); assert(await save(unit).isHidden()); assert(await cancel(unit).isHidden());
            const inline = await geometry(unit), nameBox = await name(unit).boundingBox();
            assert(nameBox.x >= inline.order.right && nameBox.x + nameBox.width <= inline.toggle.x + 1, 'Name edits inline in the compact header');
            await transparent(unit); await collapse(unit);
            await toggle(unit).focus(); await toggle(unit).press('Enter'); assert(await expanded(unit));

            // Validation is local; dirty collapse/reopen retains the draft and Cancel restores saved data.
            const original = await saved(), beforeWrites = writes.length;
            await name(unit).fill('TBSP');
            assert(await save(unit).isVisible()); assert(await save(unit).isDisabled());
            assert.equal(await name(unit).getAttribute('aria-invalid'), 'true');
            const error = unit.locator('[data-unit-row-name-error]');
            assert(await error.isVisible());
            const errorBox = await error.boundingBox(), invalidRow = await unit.boundingBox();
            assert(errorBox.x >= invalidRow.x && errorBox.x + errorBox.width <= invalidRow.x + invalidRow.width);
            assert(errorBox.y + errorBox.height <= (await unit.locator('.unit-master-aliases').boundingBox()).y);
            await shot(`units-mobile-validation-${width}.png`);
            await name(unit).fill(`Phone teaspoon ${width}`); assert(await save(unit).isEnabled());
            await transparent(unit); await collapse(unit); await assertCollapsed(unit);
            assert.equal(writes.length, beforeWrites);
            await expand(unit); assert.equal(await name(unit).inputValue(), `Phone teaspoon ${width}`);
            assert.equal(await page.locator('.is-inline-editing').count(), 1);
            await cancel(unit).tap(); await display(unit).waitFor();
            assert.equal(writes.length, beforeWrites); assert.equal((await saved()).name, original.name);
            await collapse(unit); await assertCollapsed(unit);

            // Category and alias controls stay in the expanded row and share its saved transaction.
            await expand(unit); await display(unit).tap(); await name(unit).fill(`Phone teaspoon ${width}`);
            const category = unit.locator('[data-unit-row-category]');
            assert.equal(await category.getAttribute('aria-haspopup'), 'menu');
            await category.tap();
            const menu = page.locator('#unitCategoryMenu');
            assert.equal(await category.getAttribute('aria-expanded'), 'true'); assert(await expanded(unit));
            await menu.locator(`[data-category-id="${categoryId}"]`).tap();
            assert.equal(await category.innerText(), categoryName); assert(await expanded(unit));
            await unit.getByRole('button', {name: 'Manage aliases', exact: true}).tap(); assert(await expanded(unit));
            const popover = page.locator('[data-unit-master-form]');
            await popover.locator('[data-unit-master-alias-input]').fill(`phone alias ${width}`);
            await popover.locator('[data-unit-master-alias-input]').press('Enter');
            assert((await popover.boundingBox()).width <= width - 24);
            await popover.getByRole('button', {name: 'Close aliases', exact: true}).tap(); assert(await expanded(unit));
            const saveBox = await save(unit).boundingBox(), cancelBox = await cancel(unit).boundingBox();
            assert(saveBox.height >= 44 && cancelBox.height >= 44);
            assert.equal(saveBox.y, cancelBox.y); assert(saveBox.x + saveBox.width <= cancelBox.x);
            await reveal(unit); await shot(`units-mobile-edit-${width}.png`);
            const actionsHeight = (await unit.locator('.unit-master-action-cell').boundingBox()).height;
            assert(actionsHeight <= 70, `Dirty actions contain only controls and status: ${actionsHeight}px`);
            await save(unit).tap(); await display(unit).waitFor(); await collapse(unit); await assertCollapsed(unit);
            assert.equal((await saved()).name, `Phone teaspoon ${width}`); assert.equal((await saved()).category, categoryId);
            assert((await saved()).aliases.includes(`phone alias ${width}`));
            await page.reload(); assert.equal(await display(unit).innerText(), `Phone teaspoon ${width}`);
            await expand(unit); await display(unit).tap(); await category.tap(); await menu.locator('[data-category-id="volume"]').tap(); await save(unit).tap(); await display(unit).waitFor();

            // Touch-sized moves preserve expansion; order is local until Save and Cancel restores it.
            const orderBefore = (await registry()).units.filter(u => u.category === 'volume').map(u => u.id);
            await reveal(unit); await expand(unit); await handle(unit).tap(); assert(await expanded(unit));
            await handle(unit).press('ArrowUp'); assert(await save(unit).isEnabled());
            assert.deepEqual((await registry()).units.filter(u => u.category === 'volume').map(u => u.id), orderBefore);
            assert.notDeepEqual(await volumeOrder(), orderBefore);
            await cancel(unit).tap(); await display(unit).waitFor(); assert.deepEqual(await volumeOrder(), orderBefore);
            await expand(unit); await handle(unit).press('ArrowUp'); await save(unit).tap(); await display(unit).waitFor();
            const orderAfter = (await registry()).units.filter(u => u.category === 'volume').map(u => u.id);
            assert.equal(orderAfter.indexOf('volume_teaspoon'), orderBefore.indexOf('volume_teaspoon') - 1);

            // A real touch drag changes ordering without a handle tap toggling the source row.
            const volumeRows = page.locator('[data-category="volume"] [data-unit-master-row]');
            const dragId = await volumeRows.nth(0).getAttribute('data-unit-id');
            const dragRow = row(dragId), dragOrderBefore = await volumeOrder();
            await reveal(dragRow); await handle(dragRow).tap(); assert(!await expanded(dragRow));
            const start = await handle(dragRow).boundingBox(), end = await volumeRows.nth(1).boundingBox();
            const touch = await context.newCDPSession(page);
            await touch.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: start.x + start.width / 2, y: start.y + start.height / 2, id: 1}]});
            await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: start.x + start.width / 2, y: end.y + end.height - 8, id: 1}]});
            await page.waitForFunction(() => document.querySelector('.is-row-drop-after, .is-row-drop-before'));
            await touch.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
            await touch.detach();
            // Finish Chromium's touch gesture and the app's 400ms synthetic-tap guard.
            await page.waitForTimeout(450);
            // Auto-scroll can select a later row than the original pointer coordinates imply.
            await page.waitForFunction(previous => JSON.stringify([...document.querySelectorAll('[data-category="volume"] [data-unit-master-row]')].map(r => r.dataset.unitId)) !== JSON.stringify(previous), dragOrderBefore);
            await toggle(dragRow).tap();
            await page.waitForFunction(id => document.querySelector(`[data-unit-id="${id}"] [data-unit-row-toggle]`).getAttribute('aria-expanded') === 'true', dragId);
            assert(await expanded(dragRow)); assert(await save(dragRow).isEnabled());
            assert.deepEqual((await registry()).units.filter(u => u.category === 'volume').map(u => u.id), orderAfter);
            await reveal(dragRow);
            await cancel(dragRow).tap();
            await display(dragRow).waitFor(); assert.deepEqual(await volumeOrder(), dragOrderBefore);

            // Usage opens recipe links without changing either collapsed or expanded state.
            const usageButton = unit.locator('[data-unit-master-usage-button]');
            for (const open of [false, true]) {
                await reveal(unit); if (open) await expand(unit); else await collapse(unit);
                if (!await usageButton.isVisible()) { assert(!open, 'Full usage is available in expanded details'); continue; }
                await usageButton.tap(); assert.equal(await expanded(unit), open);
                const usage = page.locator('[data-unit-master-usage-dialog]');
                await usage.waitFor({state: 'visible'}); await usage.getByRole('link').first().waitFor();
                assert(await usage.getByRole('link').count() > 0);
                assert.match(await usage.getByRole('link').first().getAttribute('href'), /recipe/);
                await usage.locator('[data-unit-master-usage-close]').first().tap();
                assert(await usage.isHidden()); assert.equal(await expanded(unit), open);
            }
            await collapse(unit);

            // Final rows, footer Add, and the new-unit draft all clear the fixed navigation.
            const bottom = page.locator('[data-unit-master-add-button]').last();
            await bottom.evaluate(e => e.scrollIntoView({block: 'end'}));
            const nav = await page.locator('.app-mobile-bottom-nav').boundingBox();
            assert((await bottom.boundingBox()).y + (await bottom.boundingBox()).height <= nav.y - 8);
            const last = page.locator('[data-unit-master-row]').last();
            assert((await last.boundingBox()).y + (await last.boundingBox()).height <= nav.y - 8);
            await shot(`units-mobile-bottom-${width}.png`);
            await bottom.tap();
            const draft = page.locator('[data-unit-new-draft]');
            assert(await name(draft).isVisible()); assert(await cancel(draft).isVisible()); assert(await save(draft).isDisabled());
            await name(draft).fill(`new phone measure ${width}`);
            await draft.locator('[data-unit-row-category]').tap(); await menu.locator('[data-category-id="volume"]').tap();
            assert(await save(draft).isEnabled());
            await save(draft).evaluate(e => e.scrollIntoView({block: 'end'}));
            assert((await cancel(draft).boundingBox()).y + (await cancel(draft).boundingBox()).height <= (await page.locator('.app-mobile-bottom-nav').boundingBox()).y - 8);
            await cancel(draft).tap(); assert(await draft.isHidden());
            assert(await viewportFits());
            console.log(`PASS ${width}px: compact expandable rows, long names/categories, 50 wrapping aliases, touch targets, inline editing, validation, dirty collapse, alias/category save/reload, Cancel, real touch reorder, usage links, footer/nav clearance.`);
        }
        assert.deepEqual(errors, []);
        await context.close();
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
