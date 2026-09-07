const { chromium } = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[3];
const cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: 1920, height: 1080}, colorScheme: 'dark'});
        await context.addCookies([cookie]);
        const page = await context.newPage(); page.setDefaultTimeout(10000);
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (message.type() === 'error' && !/422|503/.test(message.text())) errors.push(message.text()); });
        const shot = async file => { if (artifacts) { fs.mkdirSync(artifacts, {recursive: true}); await page.screenshot({path: path.join(artifacts, file)}); } };
        const row = page.locator('[data-unit-id="volume_teaspoon"][data-unit-master-row]');
        const name = row.locator('[data-unit-row-name]'), picker = row.locator('[data-unit-row-category]');
        const aliases = page.locator('[data-unit-master-alias-input]');
        const menu = page.locator('#unitCategoryMenu');
        const editor = page.getByRole('dialog').filter({has: page.locator('[data-category-form]')});
        const manager = page.getByRole('dialog', {name: 'Manage categories', exact: true});
        const catName = editor.getByLabel('Category name', {exact: true});
        const catDescription = editor.getByLabel('Description (optional)', {exact: true});
        const submit = editor.locator('[data-category-submit]');
        const registry = () => page.locator('#ingredientUnitConfig').evaluate(e => JSON.parse(e.textContent));
        const value = control => control.evaluate(e => e.value);
        const menuAction = async (control, label) => { await control.click(); await menu.getByRole('menuitem', {name: label, exact: true}).click(); };
        const closeManager = async () => { await manager.getByRole('button', {name: 'Done', exact: true}).click(); await manager.waitFor({state: 'hidden'}); };
        const saveCategory = async () => { await submit.click(); await editor.waitFor({state: 'hidden'}); };
        const focusIs = async control => assert(await control.evaluate(e => e === document.activeElement),
            `Expected focus on ${await control.getAttribute('aria-label') || await control.getAttribute('id') || await control.innerText()}; actual ${await page.evaluate(() => document.activeElement.outerHTML.slice(0, 400))}`);

        await page.goto(base + '/admin/master-data/units');
        assert.equal(await page.title(), 'Units'); assert(page.url().endsWith('/admin/master-data/units'));
        assert.equal(await page.locator('[data-unit-master-row]').count(), 35);
        await row.locator('[data-unit-row-activate="name"]').click();
        await name.fill('measuring teaspoon');
        await name.evaluate(e => { window.categoryDraftNode = e; });
        await row.getByRole('button', {name: 'Add alias', exact:true}).click();
        await aliases.fill('tea measure'); await aliases.press('Enter');
        await aliases.fill('tea spoonful');
        await picker.press('Space');
        assert.equal(await picker.getAttribute('aria-haspopup'), 'menu');
        assert.equal(await picker.getAttribute('aria-expanded'), 'true');
        assert.equal(await picker.getAttribute('aria-controls'), 'unitCategoryMenu');
        assert.match(await picker.getAttribute('aria-label'), /category for teaspoon: Volume/i);
        assert.equal(await menu.getAttribute('aria-label'), 'Category');
        assert.equal(await menu.getByRole('separator').count(), 1);
        assert.deepEqual(await menu.locator('button').allTextContents(), ['Volume', 'Weight', 'Count & Package', 'Small Amounts & Optional', '+ Add category', 'Manage categories…']);
        assert.equal(await menu.getByRole('menuitemradio', {name: 'Volume', exact: true}).getAttribute('aria-checked'), 'true');
        await page.keyboard.press('End'); await focusIs(menu.getByRole('menuitem', {name: 'Manage categories…', exact: true}));
        await page.keyboard.press('Home'); await focusIs(menu.getByRole('menuitemradio', {name: 'Volume', exact: true}));
        await page.keyboard.press('w'); await focusIs(menu.getByRole('menuitemradio', {name: 'Weight', exact: true}));
        await page.keyboard.press('Escape'); await focusIs(picker);
        assert.equal(await name.inputValue(), 'measuring teaspoon');
        const scroll = await page.locator('#appContent').evaluate(e => e.scrollTop);
        await picker.press('ArrowDown'); await shot('unit-category-menu.png');
        await page.keyboard.press('End'); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter');
        await editor.waitFor(); await focusIs(catName);
        // Native dialog focus trap: Shift+Tab from the first field wraps to Submit.
        await page.keyboard.press('Shift+Tab'); await focusIs(submit); await page.keyboard.press('Tab'); await focusIs(catName);
        await submit.click(); assert.equal(await catName.getAttribute('aria-invalid'), 'true');
        assert.match(await editor.locator('#unitCategoryNameError').innerText(), /Enter/);
        await catName.fill(' vOLume '); await submit.click();
        assert.match(await editor.locator('#unitCategoryNameError').innerText(), /already exists/);
        await catName.fill('Portions'); await catDescription.fill('Measures for serving food');
        await shot('unit-category-add.png');
        // Retry a failed request without losing either category or unit drafts.
        await page.route('**/api/master-data/unit-categories', route => route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({ok: false, error: 'Please retry.'})}), {times: 1});
        await submit.click(); await editor.getByText('Please retry.', {exact: true}).waitFor();
        assert.equal(await catName.inputValue(), 'Portions');
        await saveCategory(); await focusIs(picker);
        const key = await value(picker);
        assert.match(key, /^category_/); assert.equal(await picker.innerText(), 'Portions');
        assert.equal(await name.inputValue(), 'measuring teaspoon');
        await row.getByRole('button', {name:'Add alias', exact:true}).click();
        assert.equal(await aliases.inputValue(), 'tea spoonful');
        assert(await page.getByRole('button', {name: 'Remove alias tea measure', exact: true}).isVisible());
        assert(await name.evaluate(e => e === window.categoryDraftNode));
        assert.equal(await page.locator('#appContent').evaluate(e => e.scrollTop), scroll);
        assert.equal((await registry()).units.find(u => u.id === 'volume_teaspoon').category, 'volume');

        await menuAction(picker, 'Manage categories…');
        assert.equal(await manager.getByRole('button', {name: 'Delete Volume', exact: true}).count(), 0);
        assert.match(await manager.locator('[data-category-id="volume"]').innerText(), /9 units.*Required/s);
        await manager.getByRole('button', {name: 'Edit Portions', exact: true}).click();
        await catName.fill('WEIGHT'); await submit.click(); assert.match(await editor.locator('#unitCategoryNameError').innerText(), /already exists/);
        await catName.fill('Serving sizes'); await catDescription.fill('Portion and serving measures'); await saveCategory();
        await focusIs(manager.getByRole('button', {name: 'Edit Serving sizes', exact: true}));
        assert.equal(await picker.innerText(), 'Serving sizes'); assert.equal(await value(picker), key);
        for (let index = 3; index >= 0; index--) {
            await manager.getByRole('button', {name: 'Move Serving sizes up', exact: true}).click();
            await page.waitForFunction(({key, index}) => JSON.parse(document.getElementById('ingredientUnitConfig').textContent).categories[index].key === key, {key, index});
        }
        assert(await manager.getByRole('button', {name: 'Move Serving sizes up', exact: true}).isDisabled());
        await focusIs(manager.getByRole('button', {name: 'Edit Serving sizes', exact: true}));
        await manager.getByRole('button', {name: 'Edit Volume', exact: true}).click();
        await catName.fill('Liquid volume'); await saveCategory();
        assert.equal(await page.locator('#unitCategory-volume').innerText(), 'Liquid volume');
        assert.equal(await name.inputValue(), 'measuring teaspoon');
        assert((await row.locator('.unit-master-aliases code').allTextContents()).includes('tea measure'));
        const rowTop = (await row.boundingBox()).y;
        await manager.getByRole('button', {name: 'Move Liquid volume down', exact: true}).click();
        await page.waitForFunction(() => JSON.parse(document.getElementById('ingredientUnitConfig').textContent).categories[2].key === 'volume');
        assert(Math.abs((await row.boundingBox()).y - rowTop) <= 1, 'Category reorder keeps the open row at the same viewport position');
        assert(await name.evaluate(e => e === window.categoryDraftNode));
        await shot('unit-category-manager-desktop.png');
        await closeManager(); await focusIs(picker);
        await row.getByRole('button', {name:'Add alias', exact:true}).click();
        assert.equal(await aliases.inputValue(), 'tea spoonful');
        assert(await name.evaluate(e => e === window.categoryDraftNode));
        await picker.click();
        assert.equal(await menu.locator('[role="menuitemradio"]').first().innerText(), 'Serving sizes');
        await page.keyboard.press('Tab'); assert(await menu.isHidden());
        await row.locator('[data-unit-row-save]').click();
        await row.locator('[data-unit-row-activate="name"]').waitFor();
        assert.equal(await row.locator('[data-unit-row-activate="category"]').innerText(), 'Serving sizes');
        await page.reload();
        assert.equal(await row.locator('[data-unit-row-activate="name"]').innerText(), 'measuring teaspoon');
        assert.equal((await registry()).categories[0].key, key);
        assert.equal((await registry()).categories[0].description, 'Portion and serving measures');
        assert((await registry()).units.find(u => u.id === 'volume_teaspoon').aliases.includes('tea spoonful'));
        assert((await registry()).units.find(u => u.id === 'volume_teaspoon').aliases.includes('tea measure'));

        // Reassignment also preserves edits on a unit whose saved category is deleted.
        await row.locator('[data-unit-row-activate="name"]').click(); await name.fill('another unsaved name');
        await row.getByRole('button', {name:'Add alias', exact:true}).click(); await aliases.fill('another alias');
        await menuAction(picker, 'Manage categories…');
        await manager.getByRole('button', {name: 'Delete Serving sizes', exact: true}).click();
        assert.match(await editor.locator('[data-category-delete-context]').innerText(), /used by 1 unit/);
        await submit.click(); assert.match(await editor.locator('[role="alert"]').innerText(), /Choose a category/);
        await editor.getByLabel('Reassign units to', {exact: true}).selectOption('weight'); await saveCategory();
        assert.equal(await manager.getByRole('button', {name: 'Edit Serving sizes', exact: true}).count(), 0);
        await closeManager(); await focusIs(picker);
        assert.equal(await value(picker), 'weight'); assert.equal(await name.inputValue(), 'another unsaved name');
        await row.getByRole('button', {name:'Add alias', exact:true}).click();
        assert.equal(await aliases.inputValue(), 'another alias');
        assert.equal((await registry()).units.find(u => u.id === 'volume_teaspoon').category, 'weight');
        await row.locator('[data-unit-row-cancel]').click(); await page.reload();
        assert.equal(await row.locator('[data-unit-row-activate="category"]').innerText(), 'Weight');

        // The Add Unit dropdown receives live changes and keeps all unsaved fields too.
        await page.locator('[data-unit-master-add-button]').first().click();
        const addForm = page.locator('[data-unit-master-form]');
        const addPicker = addForm.locator('[data-unit-master-category-select]');
        await addForm.locator('[data-unit-master-name]').fill('test scoop'); await aliases.fill('scoopful');
        await menuAction(addPicker, '+ Add category');
        await catName.fill('Temporary group'); await saveCategory();
        const temporary = await value(addPicker);
        assert.equal(await aliases.inputValue(), 'scoopful');
        assert.equal(await addForm.locator('[data-unit-master-name]').inputValue(), 'test scoop');
        await menuAction(addPicker, 'Manage categories…');
        await manager.getByRole('button', {name: 'Delete Temporary group', exact: true}).click();
        assert.match(await editor.locator('[data-category-delete-context]').innerText(), /unsaved unit/);
        await editor.getByLabel('Reassign units to', {exact: true}).selectOption('count_package'); await saveCategory();
        await closeManager(); assert.equal(await value(addPicker), 'count_package');
        assert(!(await registry()).categories.some(c => c.key === temporary));
        await menuAction(addPicker, '+ Add category'); await catName.fill('Scoops'); await saveCategory();
        await addForm.locator('[data-unit-master-save]').click(); await addForm.waitFor({state: 'hidden'});
        await page.reload();
        assert((await registry()).units.some(u => u.name === 'test scoop' && u.aliases.includes('scoopful')));

        // Mobile layout, Escape cancellation and deletion of an unused category.
        await page.setViewportSize({width: 390, height: 844});
        await row.locator('[data-unit-row-activate="category"]').click(); await page.keyboard.press('Escape');
        await menuAction(picker, '+ Add category'); await catName.fill('Unused'); await saveCategory();
        await picker.click(); await menu.getByRole('menuitemradio', {name: 'Weight', exact: true}).click();
        await menuAction(picker, 'Manage categories…'); await shot('unit-category-manager-mobile.png');
        const bounds = await manager.boundingBox(); assert(bounds.width <= 390 && bounds.height <= 844 && bounds.x >= 0 && bounds.y >= 0);
        await manager.getByRole('button', {name: 'Delete Unused', exact: true}).click();
        assert(await editor.getByLabel('Reassign units to', {exact: true}).isHidden());
        await saveCategory(); await closeManager();
        await menuAction(picker, '+ Add category'); await catName.fill('Canceled'); await page.keyboard.press('Escape');
        await editor.waitFor({state: 'hidden'}); await focusIs(picker);
        assert(!(await registry()).categories.some(c => c.label === 'Canceled' || c.label === 'Unused'));

        // Overflowing menus reveal the selected option and reset typeahead on reopen.
        await row.locator('[data-unit-row-cancel]').click();
        let lastCategory;
        for (let index = 1; index <= 12; index++) {
            const response = await context.request.post(base + '/api/master-data/unit-categories', {
                data: {name: `Overflow category ${index}`, description: `Menu overflow fixture ${index}`},
            });
            assert(response.ok()); lastCategory = (await response.json()).category_id;
        }
        await page.reload();
        await row.locator('[data-unit-row-activate="name"]').click(); await name.fill('overflow menu draft');
        await picker.click(); await menu.getByRole('menuitemradio').last().click();
        assert.equal(await value(picker), lastCategory);
        const overflowScroll = await page.locator('#appContent').evaluate(e => e.scrollTop);
        await picker.press('ArrowUp');
        const selected = menu.getByRole('menuitemradio', {name: 'Overflow category 12', exact: true});
        await focusIs(selected);
        const selectedBounds = await selected.boundingBox(), menuBounds = await menu.boundingBox();
        assert(selectedBounds.y >= menuBounds.y && selectedBounds.y + selectedBounds.height <= menuBounds.y + menuBounds.height,
            'Reopening a long menu reveals the currently selected category');
        assert.equal(await page.locator('#appContent').evaluate(e => e.scrollTop), overflowScroll);
        await shot('unit-category-menu-long-mobile.png');
        await page.keyboard.press('w'); await focusIs(menu.getByRole('menuitemradio', {name: 'Weight', exact: true}));
        await page.keyboard.press('Escape'); await picker.press('ArrowDown');
        await page.keyboard.press('l'); await focusIs(menu.getByRole('menuitemradio', {name: 'Liquid volume', exact: true}));
        await page.keyboard.press('Escape');

        // Canceling a nested delete restores its button without closing or scrolling the manager.
        await picker.click(); await menu.getByRole('menuitem', {name: /^Manage categories/}).click();
        const deleteLast = manager.getByRole('button', {name: 'Delete Overflow category 12', exact: true});
        await deleteLast.scrollIntoViewIfNeeded();
        const managerScroll = await manager.evaluate(e => e.scrollTop);
        const draftScroll = await page.locator('#appContent').evaluate(e => e.scrollTop);
        await deleteLast.click(); await editor.waitFor();
        assert.match(await editor.locator('[data-category-delete-context]').innerText(), /unsaved unit/);
        await page.keyboard.press('Escape'); await editor.waitFor({state: 'hidden'});
        assert(await manager.isVisible()); await focusIs(deleteLast);
        assert.equal(await manager.evaluate(e => e.scrollTop), managerScroll);
        assert.equal(await page.locator('#appContent').evaluate(e => e.scrollTop), draftScroll);
        assert.equal(await name.inputValue(), 'overflow menu draft'); assert.equal(await value(picker), lastCategory);
        await closeManager(); await focusIs(picker);
        assert.deepEqual(errors, []);
        console.log('PASS category keyboard menu and overflow visibility, typeahead reset, dialog focus trap/return and nested cancellation, labels, empty/duplicate validation, retries, add/rename/reorder/delete/reassign, existing and new unit drafts, committed/pending aliases, DOM identity, scroll, description/refresh persistence, desktop/mobile, console');
    } finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
