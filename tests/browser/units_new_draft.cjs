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
        const page = await context.newPage(); page.setDefaultTimeout(10000);
        const errors = [], creates = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {
            if (['error', 'warning'].includes(message.type()) && !/422|503/.test(message.text())) errors.push(message.text());
        });
        page.on('request', request => {
            if (request.method() === 'POST' && request.url() === base + '/api/master-data/units') creates.push(request.postDataJSON());
        });
        const registry = async () => (await (await context.request.get(base + '/api/master-data/units')).json()).registry;
        const draft = page.locator('[data-unit-new-draft]');
        const name = draft.locator('[data-unit-row-name]'), category = draft.locator('[data-unit-row-category]');
        const add = draft.locator('[data-unit-row-save]'), cancel = draft.locator('[data-unit-row-cancel]');
        const top = page.locator('[data-unit-master-add-button]').first();
        const bottom = page.locator('[data-unit-master-add-button]').last();
        const popover = page.locator('[data-unit-master-form]');
        const alias = popover.locator('[data-unit-master-alias-input]');
        const manage = draft.getByRole('button', {name: 'Manage aliases', exact: true});
        const menu = page.locator('#unitCategoryMenu');
        const scroll = () => page.locator('#appContent').evaluate(e => e.scrollTop);
        const focusIs = async control => assert(await control.evaluate(e => e === document.activeElement));
        const choose = async key => { await category.click(); await menu.locator(`[data-category-id="${key}"]`).click(); };
        const closeAliases = () => popover.getByRole('button', {name: 'Close aliases', exact: true}).click();
        const shot = async filename => {
            if (artifacts) { fs.mkdirSync(artifacts, {recursive: true}); await page.screenshot({path: path.join(artifacts, filename)}); }
        };
        await page.goto(base + '/admin/master-data/units');
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.title(), 'Units'); assert(page.url().endsWith('/admin/master-data/units'));
        assert.equal(await page.locator('[data-unit-master-row]').count(), 35);
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        assert.equal(await page.locator('.unit-master-inline-editor, .unit-master-ai-assist, [data-unit-master-name]').count(), 0);
        const original = await registry();
        await shot('units-new-before.png');

        // Both entry points share one local draft. A pristine draft occupies one table row.
        const startScroll = await scroll();
        await top.click(); await focusIs(name);
        assert.equal(await draft.count(), 1); assert.equal(await name.inputValue(), '');
        assert.equal(await category.evaluate(e => e.value), '');
        assert(await category.isEnabled()); assert(await cancel.isEnabled()); assert(await add.isDisabled());
        assert(await popover.isHidden()); assert.equal(await scroll(), startScroll);
        assert.equal(await draft.locator('[role="cell"]').count(), 7);
        assert.equal(await draft.locator('.unit-master-order-cell').innerText(), 'New');
        assert.equal(await draft.locator('.unit-master-no-aliases').innerText(), 'No aliases');
        assert.equal(await manage.innerText(), '+ Manage aliases');
        assert.equal(await draft.locator('.unit-master-usage').innerText(), '0');
        assert.equal(await draft.locator('.unit-master-source-badge').innerText(), 'User-created');
        assert.equal(await draft.locator('.unit-master-field-error:visible').count(), 0);
        assert.equal((await draft.boundingBox()).height, (await page.locator('[data-unit-master-row][data-unit-id="volume_teaspoon"]').boundingBox()).height);
        const columns = await draft.locator('[role="cell"]').evaluateAll(cells => cells.map(c => Math.round(c.getBoundingClientRect().x)));
        assert.deepEqual(columns, await page.locator('[data-unit-id="volume_teaspoon"] > [role="cell"]').evaluateAll(cells => cells.map(c => Math.round(c.getBoundingClientRect().x))));
        await top.click(); assert.equal(await draft.count(), 1); await focusIs(name);
        await bottom.click(); assert.equal(await draft.count(), 1); await focusIs(name);
        assert.deepEqual(await registry(), original); assert.equal(creates.length, 0);
        await cancel.click(); assert.equal(await draft.count(), 0); assert.equal(creates.length, 0);

        // A bottom draft replaces the footer control at the same scroll position.
        await bottom.scrollIntoViewIfNeeded();
        const bottomScroll = await scroll(), footerY = (await page.locator('.unit-master-add-footer').boundingBox()).y;
        await bottom.click(); await focusIs(name);
        assert.equal(await scroll(), bottomScroll);
        assert(Math.abs((await draft.boundingBox()).y - footerY) <= 1);
        assert(await bottom.isHidden()); assert(await draft.evaluate(e => e.parentElement.classList.contains('unit-master-add-footer')));
        await name.fill('canceled scoop'); await choose('volume');
        await manage.click(); await alias.fill('canceled alias'); await closeAliases();
        const cancelScroll = await scroll();
        await cancel.click(); await focusIs(bottom);
        assert.equal(await scroll(), Math.min(cancelScroll, await page.locator('#appContent').evaluate(e => e.scrollHeight - e.clientHeight)));
        assert.equal(await draft.count(), 0); assert(await bottom.isVisible());
        assert.equal(creates.length, 0); assert.deepEqual(await registry(), original);

        // Local validation checks canonical names and aliases against the entire registry.
        await top.click(); await name.fill('scoop'); assert(await add.isDisabled());
        await choose('volume'); assert(await add.isEnabled());
        for (const conflict of [' TABLESPOON ', ' TbSp ']) {
            await name.fill(conflict); assert(await add.isDisabled());
            assert.match(await draft.locator('[data-unit-row-name-error]').innerText(), /already accepted by tablespoon/);
        }
        await name.fill(' '); assert(await add.isDisabled());
        await name.fill('scoop'); await manage.click(); await focusIs(alias);
        assert(await popover.isVisible()); assert(await popover.evaluate(e => e.matches(':popover-open')));
        const bounds = await popover.boundingBox(); assert(bounds.width <= 360 && bounds.height < 450);
        for (const conflict of ['tbsp', ' TABLESPOON ', ' SCOOP ']) {
            await alias.fill(conflict); assert(await add.isDisabled());
            assert(await popover.locator('[data-unit-master-alias-error]').isVisible());
        }
        await alias.fill('scoopful'); await alias.press('Enter');
        await alias.fill(' SCOOPFUL '); assert(await add.isDisabled());
        assert.match(await popover.locator('[data-unit-master-alias-error]').innerText(), /already in this unit/);
        await alias.fill(''); assert(await add.isEnabled());

        // Suggestions remain optional, filtered, explicitly selected, and local until Add.
        await page.route('**/api/master-data/units/suggest', async route => {
            assert.deepEqual(route.request().postDataJSON(), {unit_id: '', canonical_name: 'scoop', category: 'volume', aliases: ['scoopful']});
            await route.fulfill({json: {ok: true, suggestion: {canonical_name: 'bad AI name', category: 'weight', aliases: ['SCOOP', 'SCOOPFUL', 'TBSP', 'tablespoon', 'scoops', ' SCOOPS ', 'scoop measure']}}});
        }, {times: 1});
        await popover.getByRole('button', {name: 'Suggest aliases', exact: true}).click();
        const suggestions = popover.locator('[data-unit-alias-suggestion-chips] button');
        await suggestions.first().waitFor();
        assert.deepEqual(await suggestions.allTextContents(), ['scoops', 'scoop measure']);
        assert.equal(await name.inputValue(), 'scoop'); assert.equal(await category.evaluate(e => e.value), 'volume');
        await suggestions.filter({hasText: /^scoops$/}).click();
        await popover.getByRole('button', {name: 'Add selected', exact: true}).click();
        await popover.getByRole('button', {name: 'Remove alias scoops', exact: true}).waitFor();
        assert.deepEqual(await registry(), original); assert.equal(creates.length, 0);
        await shot('units-new-aliases.png');
        await closeAliases(); await focusIs(manage);
        await shot('units-new-desktop.png');

        // Adding a category uses the existing dialog and retains the exact draft DOM.
        await name.evaluate(e => { window.draftNameControl = e; });
        await category.click(); await menu.getByRole('menuitem', {name: '+ Add category', exact: true}).click();
        const categoryDialog = page.locator('[data-category-editor]');
        await categoryDialog.getByLabel('Category name', {exact: true}).fill('Scoops');
        const categoryScroll = await scroll();
        await categoryDialog.getByRole('button', {name: 'Add Category', exact: true}).click();
        await categoryDialog.waitFor({state: 'hidden'}); await focusIs(category);
        assert.equal(await scroll(), categoryScroll);
        assert(await name.evaluate(e => e === window.draftNameControl));
        assert.equal(await name.inputValue(), 'scoop');
        const newCategory = await category.evaluate(e => e.value);
        assert.equal((await registry()).categories.find(c => c.key === newCategory).label, 'Scoops');
        assert.equal((await registry()).units.length, original.units.length); assert.equal(creates.length, 0);
        assert.match(await draft.locator('.unit-master-aliases').innerText(), /scoopful/);
        await category.click(); await menu.getByRole('menuitem', {name: /Manage categories/}).click();
        await page.locator('[data-category-manager]').getByRole('button', {name: 'Done', exact: true}).click();
        await focusIs(category); assert.equal(await name.inputValue(), 'scoop');

        // A failed create retains all values and allows correction before retrying.
        await page.route('**/api/master-data/units', route => route.fulfill({status: 422, json: {ok: false, error: 'Name conflict.', errors: {canonical_name: 'Already assigned to another unit.'}}}), {times: 1});
        await add.click(); await draft.locator('[data-unit-row-name-error]').waitFor();
        assert.equal(await name.inputValue(), 'scoop'); assert(await add.isDisabled());
        await focusIs(name);
        assert.equal((await registry()).units.length, original.units.length);
        await name.fill('measuring scoop'); assert(await add.isEnabled());
        await choose('volume');
        const volumeBefore = (await registry()).units.filter(u => u.category === 'volume');
        const saveScroll = await scroll();
        await add.click(); await draft.waitFor({state: 'detached'}); await focusIs(top);
        assert.equal(await scroll(), saveScroll);
        const saved = await registry(), volume = saved.units.filter(u => u.category === 'volume');
        const unit = volume.at(-1);
        assert.equal(unit.name, 'measuring scoop'); assert.equal(unit.sort_order, volumeBefore.length);
        assert.deepEqual([...unit.aliases].sort(), ['scoopful', 'scoops']);
        assert.equal(saved.units.length, original.units.length + 1);
        const row = page.locator(`[data-unit-master-row][data-unit-id="${unit.id}"]`);
        assert.equal(await row.locator('[data-unit-master-order-number]').innerText(), String(volumeBefore.length + 1));
        assert.equal(await page.locator('[data-category="volume"] [data-unit-master-category-count-label]').innerText(), `${volume.length} units`);
        await page.reload(); assert.equal(await row.locator('[data-unit-row-activate="name"]').innerText(), unit.name);
        assert.equal(await page.locator('[data-unit-new-draft]').count(), 0);
        assert.deepEqual((await registry()).units.find(u => u.id === unit.id), unit);

        // The bottom draft stays editable through filtering, and appends on a real save.
        await bottom.click(); await name.fill('second scoop'); await choose('volume');
        await page.locator('[data-unit-master-search]').fill('zzzz no match');
        assert(await draft.isVisible()); assert.equal(await name.inputValue(), 'second scoop');
        await page.locator('[data-unit-master-search]').fill('');
        await name.scrollIntoViewIfNeeded();
        const bottomSaveScroll = await scroll();
        await add.click(); await draft.waitFor({state: 'detached'}); await focusIs(bottom);
        assert.equal(await scroll(), bottomSaveScroll);
        assert.equal((await registry()).units.filter(u => u.category === 'volume').at(-1).name, 'second scoop');

        // Responsive layouts keep the same controls visible without horizontal overflow.
        for (const width of [1440, 1100, 768, 390, 320]) {
            await page.setViewportSize({width, height: 844});
            await bottom.click(); await focusIs(name);
            await name.fill(`mobile scoop ${width}`); await choose(newCategory);
            assert(await add.isEnabled());
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
            const addBox = await add.boundingBox(), cancelBox = await cancel.boundingBox();
            assert(addBox.x + addBox.width <= cancelBox.x + 1); assert.equal(addBox.y, cancelBox.y);
            await name.evaluate(e => e.scrollIntoView({block: 'center'}));
            const manageBox = await manage.boundingBox(), aliasBox = await draft.locator('.unit-master-aliases').boundingBox();
            if (width === 1100) await shot('units-new-compact-desktop.png');
            assert(manageBox.x >= aliasBox.x && manageBox.x + manageBox.width <= aliasBox.x + aliasBox.width + 1,
                `Manage aliases stays inside its column at ${width}px`);
            if (width === 390) await shot('units-new-mobile.png');
            await manage.click(); await alias.fill(`mobile alias ${width}`);
            const panel = await popover.boundingBox();
            assert(panel.x >= 0 && panel.y >= 0 && panel.x + panel.width <= width && panel.y + panel.height <= 844);
            if (width === 390) await shot('units-new-mobile-aliases.png');
            await alias.press('Escape'); await focusIs(manage);
            if (width === 390) {
                await add.click(); await draft.waitFor({state: 'detached'});
                await page.reload();
                assert((await registry()).units.some(u => u.name === 'mobile scoop 390' && u.category === newCategory && u.aliases.includes('mobile alias 390')));
            } else {
                await cancel.click(); assert.equal(await draft.count(), 0);
            }
        }
        assert.deepEqual(errors, []);
        console.log('PASS new-unit draft: both controls, seven columns, immediate focus, one-draft guard, no premature writes, cancel, case-insensitive canonical/alias conflicts, manual aliases, filtered AI suggestions, category creation/management, failed create/retry, ordering/counts, stable scroll, refresh persistence, desktop/tablet/mobile, page identity, overlay and console checks');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
