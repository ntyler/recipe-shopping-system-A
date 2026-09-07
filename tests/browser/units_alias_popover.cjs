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
        const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
        await context.addCookies([cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], writes = [], requests = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', msg => { if (['error', 'warning'].includes(msg.type()) && !msg.text().includes('503')) errors.push(msg.text()); });
        page.on('request', req => { if (req.method() === 'PUT' && req.url().includes('/api/master-data/units/')) writes.push(req.postDataJSON()); });
        const row = page.locator('[data-unit-id="volume_tablespoon"][data-unit-master-row]');
        const other = page.locator('[data-unit-id="volume_teaspoon"][data-unit-master-row]');
        const cell = row.locator('.unit-master-aliases');
        const add = row.locator('[data-unit-row-alias="add"]');
        const form = page.locator('[data-unit-master-form]');
        const suggest = form.getByRole('button', {name: 'Suggest aliases', exact: true});
        const openManage = async (target = row) => {
            await target.getByRole('button', {name:'Manage aliases',exact:true}).click();
        };
        const input = form.locator('[data-unit-master-alias-input]');
        const chips = form.locator('[data-unit-alias-suggestion-chips]');
        const save = row.locator('[data-unit-row-save]'), cancel = row.locator('[data-unit-row-cancel]');
        const selected = form.getByRole('button', {name: 'Add selected', exact: true});
        const scroll = () => page.evaluate(() => [scrollX, scrollY, ...[...document.querySelectorAll('#appContent, .app-content')].map(e => e.scrollTop)]);
        const focused = locator => locator.evaluate(e => e === document.activeElement);
        const shot = async name => { if (artifacts) { fs.mkdirSync(artifacts, {recursive:true}); await page.screenshot({path:path.join(artifacts, name)}); } };
        const insideViewport = async () => {
            const box = await form.boundingBox(), size = page.viewportSize();
            assert(box.x >= 11 && box.y >= 11, JSON.stringify(box));
            assert(box.x + box.width <= size.width - 11 && box.y + box.height <= size.height - 11, JSON.stringify(box));
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        };
        await page.goto(base + '/admin/master-data/units');
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.title(), 'Units'); assert.match(page.url(), /\/admin\/master-data\/units$/);
        assert.equal(await page.locator('[data-unit-master-row]').count(), 35);
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        await row.evaluate(e => e.scrollIntoView({block:'center'}));
        await page.mouse.move(0, 0);
        const height = (await row.boundingBox()).height;
        const accepted = await cell.locator('code').allTextContents();
        assert(accepted.includes('tbsp'));
        assert.equal(await cell.locator('.unit-master-alias-actions').evaluate(e => getComputedStyle(e).opacity), '1');
        assert(await add.isVisible()); assert(await add.isEnabled());
        const restingBorder = await add.evaluate(e => getComputedStyle(e).borderColor);
        await add.hover();
        await page.waitForFunction(border => {
            const control = document.querySelector('[data-unit-id="volume_tablespoon"] [data-unit-row-alias="add"]');
            return getComputedStyle(control).borderColor !== border;
        }, restingBorder);
        await page.mouse.move(0, 0);
        assert.equal(await cell.locator('[data-unit-row-alias]').count(),1);
        assert.equal(await page.locator('[data-unit-row-alias="suggest"]').count(),0);
        assert.equal(await add.getAttribute('title'), 'Manage aliases');
        assert.equal(await add.getAttribute('aria-label'), 'Manage aliases');
        assert.equal((await row.boundingBox()).height, height);
        await shot('units-alias-rest.png');

        // Keyboard entry, unchanged layout/scroll, validation, normalization and draft chips.
        await row.locator('[data-unit-row-activate="name"]').focus();
        await page.keyboard.press('Tab'); assert(await focused(add));
        assert.equal(await row.locator('[data-unit-row-name]').count(), 0);
        assert.equal((await row.boundingBox()).height, height);
        const before = await scroll(); await add.press('Enter');
        assert(await focused(input)); assert.equal(await form.getAttribute('role'), 'dialog');
        assert(await form.evaluate(e => e.matches(':popover-open')));
        assert.equal(await form.locator('[data-unit-master-name]:visible, [data-unit-master-category-select]:visible').count(), 0);
        assert.equal(await page.locator('[data-unit-master-category-rows] > form').count(), 0);
        assert.deepEqual(await scroll(), before); assert.equal((await row.boundingBox()).height, height);
        assert(await suggest.isVisible()); assert.match(await suggest.getAttribute('class'), /secondary/);
        await insideViewport();
        for (const [value, message] of [[' TBSP ', /already in this unit/], ['T.B.S.P.', /already in this unit/], ['ＴＢＳＰ', /already in this unit/], ['TSP', /already accepted by teaspoon/], ['.', /Enter an alias/]]) {
            await input.fill(value); await input.press('Enter');
            assert.match(await form.locator('[data-unit-master-alias-error]').innerText(), message);
            assert(await save.isDisabled()); assert.deepEqual(await cell.locator('code').allTextContents(), accepted);
            assert.equal((await row.boundingBox()).height, height, 'Alias validation stays in the popover without expanding the row');
        }
        await input.fill('  table measure  ');
        assert.match(await form.locator('[data-unit-master-alias-preview]').innerText(), /“table measure” will normalize to “tablespoon”/);
        await input.press('Enter');
        assert((await cell.locator('code').allTextContents()).includes('table measure')); assert(await save.isEnabled());
        assert.equal(writes.length, 0); assert.deepEqual(await scroll(), before);
        await input.press('Escape'); assert(await form.isHidden()); assert(await focused(add));
        assert(await save.isEnabled()); assert.deepEqual(await scroll(), before);
        await add.press('Space');
        await form.getByRole('button', {name:'Remove alias table measure', exact:true}).click();
        assert(await focused(input)); assert(await save.isDisabled());
        await input.fill('table measure'); await form.locator('[data-unit-master-alias-add]').click();
        await shot('units-alias-manual.png');
        await form.getByRole('button', {name:'Close aliases', exact:true}).click(); assert(await focused(add));
        await cancel.click(); assert.deepEqual(await cell.locator('code').allTextContents(), accepted); assert.equal(writes.length, 0);

        // Controlled delayed AI: no automatic selections, duplicates/conflicts filtered.
        let release;
        let gate = new Promise(resolve => release = resolve);
        await page.route('**/api/master-data/units/suggest', async route => {
            requests.push(route.request().postDataJSON()); await gate;
            await route.fulfill({json:{ok:true, suggestion:{canonical_name:'wrong name', category:'optional', aliases:['TBSP', 'T.B.S.P.', 'TSP', 'teaspoon', '.', 'x'.repeat(61), 'table measure', 'TABLE MEASURE', 'table scoop']}}});
        });
        await openManage(); await suggest.click();
        await form.getByText('Suggesting aliases…', {exact:true}).waitFor();
        assert.equal(writes.length, 0); assert.deepEqual(await cell.locator('code').allTextContents(), accepted);
        await input.fill('manual while loading'); await input.press('Enter');
        release(); await chips.getByRole('button', {name:'table measure', exact:true}).waitFor();
        assert.deepEqual(await chips.locator('button').allTextContents(), ['table measure', 'table scoop']);
        assert.equal(await chips.locator('[aria-pressed="true"]').count(), 0); assert(await selected.isDisabled());
        assert.equal(await row.locator('[data-unit-row-name]').inputValue(), 'tablespoon');
        assert.equal(await row.locator('[data-unit-row-category]').evaluate(e => e.value), 'volume');
        await chips.getByRole('button', {name:'table measure', exact:true}).press('Space');
        assert(await selected.isEnabled());
        await chips.getByRole('button', {name:'table scoop', exact:true}).press('Enter');
        await chips.getByRole('button', {name:'table scoop', exact:true}).press('Space');
        await shot('units-alias-suggestions.png');
        await selected.click();
        assert((await cell.locator('code').allTextContents()).includes('table measure'));
        assert(!(await cell.locator('code').allTextContents()).includes('table scoop')); assert.equal(writes.length, 0);
        await input.press('Escape'); assert(await focused(add));
        await save.click(); await row.locator('[data-unit-row-activate="name"]').waitFor();
        assert.equal(writes.length, 1); assert(writes[0].aliases.includes('manual while loading'));
        assert(!writes[0].aliases.includes('table scoop'));
        await page.reload(); assert((await cell.locator('code').allTextContents()).includes('table measure'));
        assert.equal(await row.locator('.unit-master-source-badge').innerText(), 'Built-in');

        // Cancel/close/switch while a response is delayed; stale work cannot reopen or leak.
        gate = new Promise(resolve => release = resolve);
        await openManage(); await suggest.click(); await form.getByText('Suggesting aliases…', {exact:true}).waitFor();
        await input.press('Escape'); await row.locator('[data-unit-row-name]').press('Escape');

        await page.route('**/api/master-data/units/suggest', route => route.fulfill({json:{ok:true,suggestion:{aliases:['fresh suggestion']}}}), {times:1});
        await openManage(); await suggest.click(); await chips.getByRole('button', {name:'fresh suggestion',exact:true}).waitFor();
        assert(await save.isDisabled(), 'Receiving suggestions alone must not dirty the row');
        await chips.getByRole('button', {name:'fresh suggestion',exact:true}).click(); await selected.click();
        assert(await save.isEnabled()); await cancel.click();
        assert(!(await cell.locator('code').allTextContents()).includes('fresh suggestion'));
        await openManage(other);
        release();
        await page.waitForTimeout(150);
        assert.match(await form.locator('[data-unit-master-editor-title]').innerText(), /teaspoon/);
        assert.equal(await chips.locator('button').count(), 0);
        assert.equal(await other.locator('.unit-master-aliases code').filter({hasText:'table scoop'}).count(), 0);
        await input.press('Escape'); await other.locator('[data-unit-row-cancel]').click();

        // Request failures preserve the draft and allow retry.
        await page.unroute('**/api/master-data/units/suggest');
        await page.route('**/api/master-data/units/suggest', route => route.fulfill({status:503, json:{ok:false,error:'Suggestions temporarily unavailable.'}}), {times:1});
        await openManage(); await suggest.click(); await form.getByText('Suggestions temporarily unavailable.', {exact:true}).waitFor();
        assert(await input.isEnabled()); assert(await form.locator('[data-unit-master-ai-suggest]').isEnabled());
        await input.press('Escape'); await cancel.click();

        // Natural Tab exit restores the row context without moving the page.
        await openManage();
        await input.focus(); const tabScroll = await scroll();
        await page.keyboard.press('Shift+Tab'); assert(await form.isHidden()); assert(await focused(add));
        await add.click(); await form.getByRole('button', {name:'Close aliases',exact:true}).focus();
        await page.keyboard.press('Tab'); assert(await form.isHidden());
        assert(await focused(row.locator('[data-unit-row-category]'))); assert.deepEqual(await scroll(), tabScroll);
        await cancel.click();

        // Viewport edges, narrow screens, long aliases and resizing while open.
        for (const size of [{width:390,height:844}, {width:320,height:568}, {width:844,height:390}]) {
            await page.setViewportSize(size);
            await row.locator('[data-unit-row-activate="name"]').click();
            await row.evaluate(e => e.scrollIntoView({block:'end'}));
            await add.focus(); const mobileScroll = await scroll(), rowHeight = (await row.boundingBox()).height;
            await add.press('Enter'); await insideViewport(); assert.deepEqual(await scroll(), mobileScroll);
            assert.equal((await row.boundingBox()).height, rowHeight);
            await input.fill('long accepted alias with several words'); await input.press('Enter');
            await insideViewport(); assert(await focused(input));
            if (size.width === 390) await shot('units-alias-mobile.png');
            await input.press('Escape'); assert(await focused(add)); assert.deepEqual(await scroll(), mobileScroll);
            await cancel.click();
        }
        await page.setViewportSize({width:1440,height:900}); await openManage();
        await page.setViewportSize({width:320,height:480}); await insideViewport();
        await input.press('Escape'); await row.locator('[data-unit-row-name]').press('Escape');
        assert.equal(writes.length, 1); assert.deepEqual(errors, []);
        // Existing servers can cache the old two-button markup with current JS.
        await page.route('**/admin/master-data/units', async route => {
            const response = await route.fetch();
            const html = (await response.text())
                .replaceAll('aria-label="Manage aliases" title="Manage aliases"', 'aria-label="Add alias" title="Add alias"')
                .replaceAll('<span class="unit-master-alias-actions">', '<span class="unit-master-alias-actions"><button type="button" data-unit-row-alias="suggest" aria-label="Suggest aliases">✨</button>');
            await route.fulfill({response,body:html});
        }, {times:1});
        await page.reload(); await openManage();
        assert.equal(await page.locator('[data-unit-row-alias="suggest"]').count(),0);
        assert.equal(await add.getAttribute('title'),'Manage aliases'); assert(await suggest.isVisible());
        await input.press('Escape'); await cancel.click();
        assert.deepEqual(errors, []);
        console.log('PASS alias popover: keyboard/focus/scroll, stable rows, manual add/remove, normalization, case/conflict validation, selective AI, delayed/canceled requests, failures, save/reload, seeded status, mobile/landscape/resize.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
