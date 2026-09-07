const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;

(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
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
        const shot = async file => { if (artifacts) { fs.mkdirSync(artifacts, {recursive: true}); await page.screenshot({path: path.join(artifacts, file)}); } };
        const registry = async () => (await (await context.request.get(base + '/api/master-data/units')).json()).registry;
        const saved = async () => (await registry()).units.find(u => u.id === 'volume_teaspoon');
        const reveal = r => r.evaluate(e => e.scrollIntoView({block: 'center'}));
        const geometry = r => r.evaluate(e => {
            const rect = n => { const b = n.getBoundingClientRect(); return {x: b.x, y: b.y, right: b.right, bottom: b.bottom, width: b.width, height: b.height}; };
            return {row: rect(e), cells: [...e.children].map(n => ({...rect(n), label: getComputedStyle(n, '::before').content})),
                chips: [...e.querySelectorAll('code')].map(rect), plus: rect(e.querySelector('[data-unit-row-alias]')),
                background: getComputedStyle(e).backgroundColor};
        });
        const viewportFits = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
        for (const width of [320, 375, 390, 430]) {
            await page.setViewportSize({width, height: 844});
            await page.goto(base + '/admin/master-data/units');
            await page.evaluate(() => document.fonts.ready);
            assert.equal(await page.title(), 'Units'); assert(page.url().endsWith('/admin/master-data/units'));
            assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
            assert.equal(await page.locator('[data-unit-master-row]').count(), 38);
            assert.equal(await page.locator('[data-unit-row-save]:visible').count(), 0);
            await reveal(unit);
            const compact = await geometry(unit);
            assert(compact.row.height <= 180, `Compact resting card at ${width}px: ${compact.row.height}`);
            assert.equal(compact.background, 'rgba(0, 0, 0, 0)');
            const [orderCell, nameCell, aliasesCell, categoryCell, usageCell, sourceCell] = compact.cells;
            assert(orderCell.x < nameCell.x && nameCell.right <= sourceCell.x + 1);
            assert(aliasesCell.y >= Math.max(orderCell.bottom, nameCell.bottom, sourceCell.bottom));
            assert(categoryCell.y >= aliasesCell.bottom && usageCell.y >= aliasesCell.bottom);
            assert(categoryCell.right <= usageCell.x + 1);
            assert(compact.cells.every(c => ['none', 'normal'].includes(c.label)), 'No repeated column labels');
            assert(compact.plus.width >= 44 && compact.plus.height >= 44);
            await shot(`units-mobile-rest-${width}.png`);
            for (const fixture of fixtures) {
                const r = row(fixture.id);
                await reveal(r);
                const boxes = await geometry(r);
                assert.equal(await display(r).innerText(), fixture.canonical_name);
                assert(await display(r).evaluate(e => e.scrollWidth <= e.clientWidth && e.scrollHeight <= e.clientHeight), 'Full long name wraps');
                assert.equal(boxes.chips.length, fixture.aliases.length);
                assert(boxes.chips.every(c => c.x >= boxes.row.x && c.right <= boxes.row.right && c.width > 0));
                assert(boxes.plus.right <= boxes.row.right);
                for (const chip of boxes.chips) assert(chip.right <= boxes.plus.x || chip.bottom <= boxes.plus.y || chip.y >= boxes.plus.bottom);
                assert(await viewportFits());
            }
            assert.equal(await row(fixtures[0].id).locator('[data-unit-row-activate="category"]').innerText(), categoryName);
            await reveal(row(fixtures[0].id)); await shot(`units-mobile-long-${width}.png`);

            // Card taps activate just that unit, then validation and cancel preserve saved data.
            const original = await saved(), beforeWrites = writes.length;
            await reveal(unit); await unit.locator('.unit-master-source-badge').tap();
            assert.equal(await page.locator('.is-inline-editing').count(), 1);
            assert(await name(unit).isVisible()); assert(await save(unit).isDisabled()); assert(await cancel(unit).isVisible());
            assert((await name(unit).boundingBox()).width > (await unit.boundingBox()).width - 24);
            await name(unit).fill('TBSP');
            assert(await save(unit).isDisabled()); assert.equal(await name(unit).getAttribute('aria-invalid'), 'true');
            const error = unit.locator('[data-unit-row-name-error]');
            assert(await error.isVisible());
            const errorBox = await error.boundingBox();
            assert(errorBox.y + errorBox.height <= (await unit.locator('.unit-master-aliases').boundingBox()).y);
            await shot(`units-mobile-validation-${width}.png`);
            await name(unit).fill(`Phone teaspoon ${width}`); assert(await save(unit).isEnabled());
            await row('volume_tablespoon').locator('.unit-master-source-badge').tap();
            assert.equal(await page.locator('.is-inline-editing').count(), 1);
            assert.equal(await name(unit).inputValue(), `Phone teaspoon ${width}`);
            await cancel(unit).tap(); assert.equal(writes.length, beforeWrites); assert.equal((await saved()).name, original.name);
            assert(await save(unit).isHidden());

            // Accessible category selector and aliases share the same saved transaction.
            await display(unit).tap(); await name(unit).fill(`Phone teaspoon ${width}`);
            const category = unit.locator('[data-unit-row-category]');
            assert.equal(await category.getAttribute('aria-haspopup'), 'menu');
            await category.tap();
            const menu = page.locator('#unitCategoryMenu');
            assert.equal(await category.getAttribute('aria-expanded'), 'true');
            await menu.locator(`[data-category-id="${categoryId}"]`).tap();
            assert.equal(await category.innerText(), categoryName);
            await unit.getByRole('button', {name: 'Manage aliases', exact: true}).tap();
            const popover = page.locator('[data-unit-master-form]');
            await popover.locator('[data-unit-master-alias-input]').fill(`phone alias ${width}`);
            await popover.locator('[data-unit-master-alias-input]').press('Enter');
            assert((await popover.boundingBox()).width <= width - 24);
            await popover.getByRole('button', {name: 'Close aliases', exact: true}).tap();
            const saveBox = await save(unit).boundingBox(), cancelBox = await cancel(unit).boundingBox();
            assert(saveBox.height >= 44 && cancelBox.height >= 44);
            assert.equal(saveBox.y, cancelBox.y); assert(saveBox.x + saveBox.width <= cancelBox.x);
            await shot(`units-mobile-edit-${width}.png`);
            await save(unit).tap(); await display(unit).waitFor();
            assert(await save(unit).isHidden()); assert(await display(unit).evaluate(e => e === document.activeElement));
            assert.equal((await saved()).name, `Phone teaspoon ${width}`); assert.equal((await saved()).category, categoryId);
            assert((await saved()).aliases.includes(`phone alias ${width}`));
            await page.reload(); assert.equal(await display(unit).innerText(), `Phone teaspoon ${width}`);
            await display(unit).tap(); await category.tap(); await menu.locator('[data-category-id="volume"]').tap(); await save(unit).tap(); await display(unit).waitFor();

            // The handle opens touch-sized moves; order is local until Save and Cancel restores it.
            const orderBefore = (await registry()).units.filter(u => u.category === 'volume').map(u => u.id);
            await reveal(unit); await handle(unit).tap();
            const up = unit.locator('[data-unit-master-order-action="up"]');
            assert(await up.isVisible()); assert((await up.boundingBox()).height >= 44);
            await up.tap(); assert(await save(unit).isEnabled());
            assert.deepEqual((await registry()).units.filter(u => u.category === 'volume').map(u => u.id), orderBefore);
            await cancel(unit).tap();
            assert.deepEqual(await page.locator('[data-category="volume"] [data-unit-master-row]').evaluateAll(rows => rows.map(r => r.dataset.unitId)), orderBefore);
            await handle(unit).tap(); await up.tap(); await save(unit).tap(); await display(unit).waitFor();
            const orderAfter = (await registry()).units.filter(u => u.category === 'volume').map(u => u.id);
            assert.equal(orderAfter.indexOf('volume_teaspoon'), orderBefore.indexOf('volume_teaspoon') - 1);

            // Final category, last card, footer Add, and the draft can clear the fixed navigation.
            const bottom = page.locator('[data-unit-master-add-button]').last();
            await bottom.evaluate(e => e.scrollIntoView({block: 'end'}));
            const nav = await page.locator('.app-mobile-bottom-nav').boundingBox();
            assert((await bottom.boundingBox()).y + (await bottom.boundingBox()).height <= nav.y - 8);
            const last = page.locator('[data-unit-master-row]').last();
            assert((await last.boundingBox()).y + (await last.boundingBox()).height <= nav.y - 8);
            await shot(`units-mobile-bottom-${width}.png`);
            await bottom.tap();
            const draft = page.locator('[data-unit-new-draft]');
            await name(draft).fill(`new phone measure ${width}`);
            await draft.locator('[data-unit-row-category]').tap(); await menu.locator('[data-category-id="volume"]').tap();
            await save(draft).evaluate(e => e.scrollIntoView({block: 'end'}));
            assert((await cancel(draft).boundingBox()).y + (await cancel(draft).boundingBox()).height <= (await page.locator('.app-mobile-bottom-nav').boundingBox()).y - 8);
            await cancel(draft).tap(); assert(await draft.isHidden());
            assert(await viewportFits());
            console.log(`PASS ${width}px: compact list, full long names, long categories, 50 aliases, touch targets, single-row edit, validation, alias/category save and reload, cancel, reorder Save/Cancel, footer/nav clearance.`);
        }
        assert.deepEqual(errors, []);
        await context.close();
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
