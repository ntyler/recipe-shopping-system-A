"""Equipment presentation edits stay scoped and preserve recipe-derived identity."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from PushShoppingList.services import recipe_master_data_service as md
from test_recipe_master_data_routes import configure_master_data_app, seed_master_records, sign_in
from test_ingredient_image_lightbox import run_browser


@pytest.mark.parametrize('account', ['user-a', 'admin-user'])
@pytest.mark.parametrize('query', ['', '?scope=all', '?scope=user&user_id=user-b'])
def test_equipment_controls_are_permanently_workspace_scoped(monkeypatch, tmp_path, account, query):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    if account == 'admin-user':
        md.sync_recipe_master_records('https://example.com/admin-pan', recipe_data={
            'equipment': [{'equipment': 'Admin pan'}],
        }, user_id=account)
    monkeypatch.setenv('RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED', 'true')
    monkeypatch.setenv('RECIPE_EQUIPMENT_STRUCTURED_UI_TENANTS', account)
    with app.test_client() as client:
        sign_in(client, account)
        response = client.get('/admin/master-data/equipment' + query)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    page = BeautifulSoup(html, 'html.parser')
    equipment = page.select_one('.equipment-master-page')
    assert not page.select('[data-equipment-master-admin-view], [data-master-scope-filter], [data-master-target-user-filter]')
    assert not equipment.select('input[name="scope"], select[name="scope"], input[name="user_id"], input[name="viewer_user_id"]')
    assert not page.select('[data-equipment-normalization-review], [data-master-backfill-form]')
    assert not page.select('.master-data-user-data-cell, .equipment-col-user')
    assert 'Admin view' not in html and 'Viewing my data' not in html
    assert 'Structured migration preview' not in html
    assert 'Whisk' not in html and 'user-b@example.com' not in html
    names = [node['value'] for node in page.select('[data-equipment-row-name]')]
    assert names == (['Admin pan'] if account == 'admin-user' else ['Large pot'])
    assert [node.get_text(strip=True) for node in page.select('.master-data-equipment-table thead th')] == [
        'Order', 'Item', 'Aliases', 'Equipment Type', 'Used In', 'Action',
    ]
    assert not page.select('.master-data-updated-cell, .equipment-col-updated')
    for row in page.select('[data-equipment-master-row]'):
        assert len(row.select(':scope > td')) == 6
        assert row.select_one('[data-equipment-order-handle]')
        assert row.select_one('[data-equipment-order-number]')
        assert row.select_one('[data-equipment-row-type]')
        assert row.select_one('[data-equipment-row-alias]')['aria-controls'] == 'equipmentAliasManager'
        assert row.select_one('[data-equipment-row-save]').has_attr('hidden')
        assert row.select_one('[data-equipment-row-cancel]').has_attr('hidden')
        assert not row.select('[data-equipment-row-delete], [popover], [popovertarget]')
        assert row.select_one('[data-master-merge-open]').get_text(strip=True) == 'Merge duplicate'
    for usage in page.select('[data-equipment-master-usage-button]'):
        assert not urlsplit(usage['data-reference-url']).query


@pytest.mark.parametrize('width,dark', [(1440, False), (1181, False), (390, False), (320, False), (1440, True), (390, True)])
def test_equipment_inline_browser(monkeypatch, tmp_path, width, dark):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    md.sync_recipe_master_records('https://example.com/equipment-browser', recipe_data={
        'equipment': [{'equipment': f'Pan {index:02d}', 'equipment_section': 'COOKWARE'} for index in range(24)],
    }, user_id='user-a')
    record = md.master_record_for_name('equipment', 'user-a', 'large pot')
    with md.recipe_master_connection() as connection:
        connection.execute("UPDATE equipment SET image_url = '/static/test-pot.svg', equipment_section = 'COOKWARE' WHERE id = ?", (record['id'],))
        unused_id = md.upsert_master_record(connection, 'equipment', 'user-a', 'Spare pot', equipment_section='COOKWARE')['id']
    md.sync_recipe_master_records('https://example.com/equipment-duplicate', recipe_data={
        'equipment': [{'equipment': 'Pan duplicate', 'equipment_section': 'COOKWARE'}],
    }, user_id='user-a')
    duplicate = md.master_record_for_name('equipment', 'user-a', 'pan duplicate')
    target = md.master_record_for_name('equipment', 'user-a', 'pan 00')
    with app.test_client() as client:
        sign_in(client, 'user-a')
        cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
        options = {'cookie': {'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'},
                   'id': record['id'], 'unusedId': unused_id, 'duplicateId': duplicate['id'],
                   'targetId': target['id'], 'width': width, 'dark': dark}
    if artifacts := os.environ.get('AI_PANTRY_BROWSER_ARTIFACTS'):
        folder = Path(artifacts).resolve()
        assert folder != Path(__file__).resolve().parents[1] and Path(__file__).resolve().parents[1] not in folder.parents
        folder.mkdir(parents=True, exist_ok=True)
        options['screenshots'] = str(folder)
    result = run_browser(app, SCENARIO, options)
    assert result['saves'] == 2 and result['errors'] == []
    saved = md.master_record_for_name('equipment', 'user-a', 'large pot')
    assert saved['id'] == record['id']
    assert saved['name'] == record['name']
    assert saved['display_name_override'] == 'Family stockpot'
    assert saved['equipment_section'] == 'BAKEWARE'
    assert md.count_equipment_usage(record['id'], user_id='user-a') == 1
    assert md.master_record_for_name('equipment', 'user-a', 'spare pot') is None
    assert md.master_record_for_name('equipment', 'user-a', 'pan duplicate') is None
    assert md.count_equipment_usage(target['id'], user_id='user-a') == 2
    listed = next(item for item in md.list_equipment(user_id='user-a') if item['id'] == record['id'])
    assert set(listed['aliases']) >= {'stock pot', 'soup pot'}


def test_equipment_alias_display_does_not_enable_or_mutate_structured_schema(monkeypatch, tmp_path):
    app, db, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    pot = md.master_record_for_name('equipment', 'user-a', 'large pot')
    # A legacy workspace must continue to work without creating the optional schema.
    md.list_equipment(user_id='user-a')
    with md.existing_recipe_master_read_connection() as connection:
        assert not md.recipe_master_table_exists(connection, 'equipment_aliases')
    with md.recipe_master_connection() as connection:
        connection.execute('CREATE TABLE equipment_aliases (user_id TEXT, equipment_id INTEGER, alias_name TEXT, alias_key TEXT, status TEXT)')
        connection.executemany('INSERT INTO equipment_aliases VALUES (?, ?, ?, ?, ?)', [
            ('user-a', pot['id'], 'Stock pot', 'stock pot', 'active'),
            ('user-a', pot['id'], 'Soup pot', 'soup pot', 'active'),
            ('user-a', pot['id'], 'Old pot', 'old pot', 'retired'),
            ('user-b', pot['id'], 'Other workspace', 'other workspace', 'active'),
        ])
    before = db.read_bytes()
    with app.test_client() as client:
        sign_in(client, 'user-a')
        html = client.get('/admin/master-data/equipment').get_data(as_text=True)
    assert 'title="Stock pot"' in html and 'title="Soup pot"' in html
    assert 'Other workspace' not in html and 'Old pot' not in html
    assert db.read_bytes() == before
    page = BeautifulSoup(html, 'html.parser')
    row = page.select_one('[data-equipment-master-row]')
    assert not row.select('[data-equipment-row-delete]')
    assert row.select_one('[data-master-merge-open]')
    assert row.select_one('[data-equipment-row-alias]')


SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = process.argv[2];
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const viewport = {width: options.width, height: options.width === 320 ? 568 : options.width === 390 ? 844 : 900};
        const context = await browser.newContext({viewport, colorScheme: options.dark ? 'dark' : 'light'});
        await context.addCookies([options.cookie]);
        await context.route('**/static/test-pot.svg', route => route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect x="30" y="60" width="140" height="100" rx="20" fill="#72878b"/></svg>'}));
        await context.route('**/static/generated/tomato.png', route => route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="24" fill="tomato"/></svg>'}));
        const reference = await context.newPage();
        await reference.goto(base + '/admin/master-data/ingredients?sort=name_asc&limit=500');
        const referenceColumns = await reference.locator('table thead th').evaluateAll(es => es.map(e => e.getBoundingClientRect().width));
        const referenceHeight = (await reference.locator('[data-ingredient-master-row]').first().boundingBox()).height;
        if (options.screenshots && !options.dark) await reference.screenshot({path: require('node:path').join(options.screenshots, `ingredient-reference-${options.width}.png`)});
        await reference.close();
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], writes = [];
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => {if (['error', 'warning'].includes(m.type()) && !m.text().includes('503')) errors.push(m.text());});
        page.on('request', request => {if (request.method() === 'PATCH') writes.push(request.postDataJSON());});
        await page.goto(base + '/admin/master-data/equipment?sort=name_asc&limit=500');
        assert.equal(await page.title(), 'Equipment');
        assert.match(page.url(), /\/admin\/master-data\/equipment/);
        assert(await page.getByRole('heading', {name: 'Equipment', exact: true}).isVisible());
        assert.equal(await page.locator('.equipment-master-page').locator('[data-equipment-master-admin-view], [data-master-scope-filter], [name="scope"], [name="user_id"], [name="viewer_user_id"], [data-equipment-normalization-review]').count(), 0);
        assert.equal(await page.getByText('Admin view', {exact: true}).count(), 0);
        assert.equal(await page.getByText('Viewing my data', {exact: true}).count(), 0);
        assert.equal(await page.locator('[data-equipment-group] table thead').count(), await page.locator('[data-equipment-group]').count());
        for (const table of await page.locator('.master-data-equipment-table').all()) {
            assert.deepEqual(await table.locator('thead th').allTextContents(), ['Order', 'Item', 'Aliases', 'Equipment Type', 'Used In', 'Action']);
        }
        assert.equal(await page.locator('[data-equipment-master-row]').count(), 27);
        assert.equal(await page.locator('.master-data-updated-cell, .equipment-col-updated, .equipment-row-more, [data-equipment-master-row] [popover], [popovertarget]').count(), 0);
        const byId = id => page.locator(`[data-equipment-master-row][data-master-record-id="${id}"]`);
        const row = byId(options.id);
        const name = row.locator('[data-equipment-row-name]'), save = row.locator('[data-equipment-row-save]');
        const cancel = row.locator('[data-equipment-row-cancel]'), toggle = row.locator('[data-equipment-mobile-toggle]');
        const type = row.locator('[data-equipment-row-type]');
        const typeTrigger = row.locator('[data-equipment-type-trigger]');
        const order = row.locator('[data-equipment-order-number]'), handle = row.locator('[data-equipment-order-handle]');
        const aliasTrigger = row.locator('[data-equipment-row-alias]'), aliases = page.locator('#equipmentAliasManager');
        const aliasInput = aliases.locator('[data-equipment-editor-alias-input]');
        const merge = row.locator('[data-master-merge-open]');
        const screenshot = async state => {
            if (options.width <= 760 && ['dirty', 'saving', 'saved', 'save-error'].includes(state)) {
                await row.locator('.ingredient-action-cell').scrollIntoViewIfNeeded();
            }
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal page overflow');
            assert(await page.locator('.app-content').evaluate(e => e.scrollWidth <= e.clientWidth), 'No clipped horizontal content');
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `equipment-${options.width}-${options.dark ? 'dark-' : ''}${state}.png`)});
        };
        const expand = async target => {
            const control = target.locator('[data-equipment-mobile-toggle]');
            if (await control.isVisible() && await control.getAttribute('aria-expanded') === 'false') await control.click();
        };
        const saved = () => page.waitForFunction(id => {
            const target = document.querySelector(`[data-equipment-master-row][data-master-record-id="${id}"]`);
            return target.getAttribute('aria-busy') !== 'true' && !target.classList.contains('is-dirty') && target.querySelector('[data-equipment-row-save]').hidden;
        }, options.id);
        await screenshot('initial');
        await row.scrollIntoViewIfNeeded(); await page.mouse.move(0, 0);
        assert(await save.isHidden() && await cancel.isHidden());
        assert.equal(await row.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
        assert.equal(await row.locator('[data-equipment-row-delete]').count(), 0, 'Referenced equipment cannot be deleted');
        if (options.width <= 760) {
            assert(await toggle.isVisible() && await name.isHidden());
            assert(await row.locator('.master-data-usage-cell').isVisible());
            await toggle.focus(); await page.keyboard.press('Enter');
            assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
        } else {
            const columns = await row.locator('xpath=ancestor::table').locator('thead th').evaluateAll(es => es.map(e => e.getBoundingClientRect().width));
            assert(columns.every((width, i) => Math.abs(width - referenceColumns[i]) < 2), `Ingredient column widths ${referenceColumns} match Equipment ${columns}`);
            assert(Math.abs((await row.boundingBox()).height - referenceHeight) < 2, 'Ingredient row height matches');
            assert(await toggle.isHidden());
            await row.locator('.master-data-usage-cell').hover();
            assert.notEqual(await row.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
            assert(await row.locator(':scope > td').evaluateAll(es => es.every(e => getComputedStyle(e).backgroundColor === 'rgba(0, 0, 0, 0)')), 'All cells reveal the full-width row hover');
            assert.equal(await name.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
            assert.equal(await typeTrigger.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
            await screenshot('hover');
            await typeTrigger.hover();
            assert.notEqual(await typeTrigger.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
            await name.hover();
            assert.notEqual(await name.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
        }
        assert.equal(await name.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
        assert.equal(await typeTrigger.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
        const restingMerge = await merge.boundingBox();
        await name.focus(); await page.mouse.move(0, 0);
        assert(await row.evaluate(e => e.classList.contains('is-selected')));
        assert.notEqual(await row.evaluate(e => getComputedStyle(e).boxShadow), 'none', 'Selected rows retain Ingredient’s subtle accent');
        assert.notEqual(await name.evaluate(e => getComputedStyle(e).outlineStyle), 'none');
        await screenshot('focus');
        await name.fill('Cancel this');
        assert(await save.isVisible() && await save.isEnabled() && await cancel.isVisible());
        assert(await merge.isDisabled(), 'Merge cannot discard a dirty row');
        assert(Math.abs((await merge.boundingBox()).x - restingMerge.x) < 1, 'Merge remains in the final fixed action slot');
        const saveBox = await save.boundingBox(), cancelBox = await cancel.boundingBox();
        await screenshot('dirty');
        if (options.width <= 760) {
            assert.equal(await toggle.getAttribute('aria-disabled'), 'true');
            await toggle.press('Enter');
            assert(await name.isVisible(), 'Dirty phone rows retain their editing controls until Save or Cancel');
            assert.equal(await name.inputValue(), 'Cancel this');
        }
        await name.fill('   ');
        assert.equal(await name.getAttribute('aria-invalid'), 'true');
        assert(await cancel.isVisible());
        assert(await save.isHidden() || await save.isDisabled());
        assert.equal((await cancel.boundingBox()).x, cancelBox.x, 'Cancel stays in its slot');
        await name.press('Enter'); assert.equal(writes.length, 0);
        await name.press('Escape');
        assert.equal(await name.inputValue(), 'Large pot');
        assert(await save.isHidden() && await cancel.isHidden());

        // Both ordering methods create drafts; Cancel restores the saved order.
        assert.equal(await handle.getAttribute('aria-disabled'), 'true', 'Alphabetical mode matches Ingredient’s read-only order controls');
        await page.goto(base + '/admin/master-data/equipment?sort=manual_order&limit=500');
        await expand(row);
        const initialOrder = Number(await order.innerText());
        await handle.press('ArrowDown');
        assert.equal(Number(await order.innerText()), initialOrder + 1);
        assert(await save.isEnabled() && await cancel.isVisible());
        assert.equal(writes.length, 0);
        await cancel.click();
        assert.equal(Number(await order.innerText()), initialOrder);
        if (options.width > 760) {
            const target = byId(options.targetId);
            await handle.dragTo(target, {targetPosition: {x: 30, y: (await target.boundingBox()).height - 3}});
            assert(Number(await order.innerText()) > initialOrder, 'Mouse dragging updates the displayed order');
            await cancel.click();
            assert.equal(Number(await order.innerText()), initialOrder);
        }
        await name.fill('Family stockpot');
        await handle.press('ArrowDown');
        await aliasTrigger.click();
        await aliases.waitFor({state: 'visible'});
        await aliasInput.fill('temporary pot'); await aliasInput.press('Enter');
        await aliases.getByRole('button', {name: 'Remove alias temporary pot', exact: true}).click();
        await aliasInput.fill('stock pot'); await aliasInput.press(',');
        await aliasInput.fill('soup pot'); await aliasInput.press('Enter');
        await screenshot('aliases');
        await aliasInput.press('Escape');
        assert(await aliases.isHidden());
        assert(await aliasTrigger.evaluate(e => e === document.activeElement));
        assert.equal(writes.length, 0, 'Name, aliases and order remain pending until Save');
        assert(await row.getByText('stock pot', {exact: true}).isVisible());
        assert(await row.getByText('soup pot', {exact: true}).isVisible());

        // Gate a real request to inspect saving without substituting persistence.
        let release;
        const gate = new Promise(resolve => release = resolve);
        const updateURL = await row.getAttribute('data-update-url');
        await page.route('**' + updateURL, async route => {await gate; await route.continue();});
        await save.click();
        await page.waitForFunction(id => document.querySelector(`[data-equipment-master-row][data-master-record-id="${id}"]`).getAttribute('aria-busy') === 'true', options.id);
        assert(await name.isDisabled() && await type.isDisabled() && await save.isDisabled());
        assert.match(await save.innerText(), /Saving/);
        assert.equal((await save.boundingBox()).x, saveBox.x);
        assert.equal((await cancel.boundingBox()).x, cancelBox.x);
        await screenshot('saving');
        release(); await saved();
        await page.unroute('**' + updateURL);
        assert.equal(await name.inputValue(), 'Family stockpot');
        assert.equal(writes.length, 1);
        assert.deepEqual(writes[0].aliases.sort(), ['soup pot', 'stock pot']);
        assert.equal(writes[0].order.position, initialOrder + 1);
        await screenshot('saved');

        // The icon picker preserves the select value and supports keyboard changes.
        await typeTrigger.focus();
        const beforeType = await type.inputValue();
        await typeTrigger.press('Home'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
        assert.notEqual(await type.inputValue(), beforeType);
        assert(await save.isVisible());
        await aliasTrigger.click();
        await aliasInput.fill('cancel pot'); await aliasInput.press('Enter'); await aliasInput.press('Escape');
        await cancel.click();
        assert.equal(await type.inputValue(), beforeType);
        assert.equal(await row.getByText('cancel pot', {exact: true}).count(), 0, 'Cancel restores aliases and Equipment Type together');
        await typeTrigger.click(); await page.getByRole('option', {name: 'Bakeware', exact: true}).click(); await save.click(); await saved();
        assert.equal(await type.inputValue(), 'BAKEWARE');
        assert.equal(writes.length, 2);
        await page.route('**' + updateURL, route => route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({ok: false, error: 'Temporary test failure'})}));
        await name.fill('Retry name'); await save.click();
        await row.getByText('Temporary test failure', {exact: true}).waitFor();
        assert.equal(await name.inputValue(), 'Retry name');
        assert(await save.isEnabled());
        await screenshot('save-error');
        await cancel.click(); assert.equal(await name.inputValue(), 'Family stockpot');
        await page.unroute('**' + updateURL); writes.pop();

        // Image and usage use the same keyboard-operable shared dialogs as Ingredient.
        const image = row.locator('[data-equipment-image-trigger]');
        await image.focus(); await image.press('Enter');
        const lightbox = page.locator('#recipeImageLightbox');
        assert(await lightbox.isVisible());
        assert(await lightbox.locator('[data-master-image-actions]').isVisible());
        const preview = await lightbox.locator('#recipeImageLightboxImage').boundingBox();
        assert(preview && preview.x >= 0 && preview.y >= 0 && preview.x + preview.width <= viewport.width + 1 && preview.y + preview.height <= viewport.height + 1, 'Image preview fits the viewport');
        await screenshot('image');
        await page.keyboard.press('Escape');
        assert(await image.evaluate(e => e === document.activeElement));
        await row.locator('[data-master-usage-button]').press('Enter');
        await page.locator('#masterDataUsageDialog').waitFor({state: 'visible'});
        await page.locator('[data-master-usage-results] a').first().waitFor();
        assert.equal(new URL(await row.locator('[data-master-usage-button]').getAttribute('data-reference-url'), base).search, '');
        assert(!(await page.locator('#masterDataUsageDialog').innerText()).includes('user-b'));
        await screenshot('usage');
        await page.keyboard.press('Escape');
        assert(await row.locator('[data-master-usage-button]').evaluate(e => e === document.activeElement));
        if (options.width >= 1280) {
            const cookwareTable = byId(options.unusedId).locator('xpath=ancestor::table');
            await cookwareTable.locator('[data-equipment-master-row]').nth(12).scrollIntoViewIfNeeded();
            const heading = await cookwareTable.locator('thead').boundingBox();
            const toolbar = await page.locator('.app-topbar').boundingBox();
            assert(Math.abs(heading.y - toolbar.y - toolbar.height) < 2, 'Whole header sticks flush below application header');
            const headers = await cookwareTable.locator('thead th').evaluateAll(es => es.map(e => e.getBoundingClientRect().top));
            assert(headers.every(y => Math.abs(y - heading.y) < 1));
            await screenshot('sticky');
        }

        // Unused equipment exposes explicit deletion, with a cancelable confirmation.
        const unused = byId(options.unusedId); await expand(unused);
        const deleteButton = unused.locator('[data-equipment-row-delete]');
        await deleteButton.click();
        assert(await unused.locator('[data-equipment-row-confirm-delete]').isVisible());
        await unused.locator('[data-equipment-row-cancel]').click();
        assert(await deleteButton.isVisible());
        await deleteButton.click();
        await screenshot('delete-confirmation');
        await unused.locator('[data-equipment-row-confirm-delete]').click();
        await unused.waitFor({state: 'detached'});

        // Merge options and submission stay in this workspace and preserve references.
        const duplicate = byId(options.duplicateId); await expand(duplicate);
        const duplicateMerge = duplicate.locator('[data-master-merge-open]');
        await duplicateMerge.click();
        const mergeDialog = page.locator('[data-master-merge-dialog]');
        await mergeDialog.waitFor({state: 'visible'});
        await page.locator('[data-master-merge-results] [role="option"]').first().waitFor();
        assert(!(await mergeDialog.innerText()).includes('Whisk'));
        await page.keyboard.press('Escape');
        assert(await duplicateMerge.evaluate(e => e === document.activeElement));
        await duplicateMerge.click();
        await page.locator('[data-master-merge-search]').fill('Pan 00');
        const mergeTarget = page.locator('[data-master-merge-results] [role="option"]').filter({has: page.getByText('Pan 00', {exact: true})});
        await mergeTarget.click();
        assert(await page.locator('[data-master-merge-submit]').isEnabled());
        await screenshot('merge');
        const mergeResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/merge'));
        await page.locator('[data-master-merge-submit]').click();
        const mergeResult = await mergeResponse;
        const mergeBody = await mergeResult.json();
        assert(mergeResult.ok() && mergeBody.ok, `Merge succeeded: ${JSON.stringify(mergeBody)}`);
        await page.waitForFunction(id => !document.querySelector(`[data-equipment-master-row][data-master-record-id="${id}"]`), options.duplicateId);
        assert.equal(await byId(options.targetId).locator('[data-master-usage-button]').innerText().then(text => text.trim()), '2 recipes');
        assert.equal(await row.locator('[data-equipment-row-name]').inputValue(), 'Family stockpot', 'Inline edits survive the merge reload');
        assert.equal(await row.locator('[data-equipment-row-type]').inputValue(), 'BAKEWARE');

        // Equipment-specific filtering remains available in the compact toolbar.
        await page.locator('input[name="search"]').fill('Pan 03');
        await page.locator('.master-data-equipment-filter-field [data-equipment-type-trigger]').click();
        await page.getByRole('option', {name: 'Cookware', exact: true}).click();
        await page.locator('select[name="sort"]').selectOption('usage_count_desc');
        await page.locator('select[name="limit"]').selectOption('50');
        await page.locator('.master-data-filter-form button[type="submit"]').click();
        await page.waitForURL(/search=Pan/);
        assert.equal(await page.locator('[data-equipment-master-row]').count(), 1);
        assert.match(page.url(), /sort=usage_count_desc/);
        assert.equal(await page.locator('[data-equipment-row-name]').inputValue(), 'Pan 03');
        assert.equal(await page.locator('[data-equipment-order-handle]').getAttribute('aria-disabled'), 'true', 'Partial filtered lists cannot accidentally reorder hidden equipment');
        await screenshot('filtered');
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({saves: writes.length, errors}));
    } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
