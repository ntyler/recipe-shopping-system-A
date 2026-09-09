"""Equipment presentation edits stay scoped and preserve recipe-derived identity."""
import os
from pathlib import Path

import pytest

from PushShoppingList.services import recipe_master_data_service as md
from test_recipe_master_data_routes import configure_master_data_app, seed_master_records, sign_in
from test_ingredient_image_lightbox import run_browser


@pytest.mark.parametrize('width,dark', [(1440, False), (1181, False), (390, False), (320, False), (1440, True), (390, True)])
def test_equipment_inline_browser(monkeypatch, tmp_path, width, dark):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    md.sync_recipe_master_records('https://example.com/equipment-browser', recipe_data={
        'equipment': [{'equipment': f'Pan {index:02d}', 'equipment_section': 'COOKWARE'} for index in range(24)],
    }, user_id='user-a')
    record = md.master_record_for_name('equipment', 'user-a', 'large pot')
    with md.recipe_master_connection() as connection:
        connection.execute("UPDATE equipment SET image_url = '/static/test-pot.svg' WHERE id = ?", (record['id'],))
    with app.test_client() as client:
        sign_in(client, 'user-a')
        cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
        options = {'cookie': {'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'},
                   'id': record['id'], 'width': width, 'dark': dark}
    if artifacts := os.environ.get('AI_PANTRY_BROWSER_ARTIFACTS'):
        folder = Path(artifacts).resolve()
        assert Path(__file__).resolve().parents[1] not in folder.parents
        folder.mkdir(parents=True, exist_ok=True)
        options['screenshots'] = str(folder)
    result = run_browser(app, SCENARIO, options)
    assert result == {'saves': 2, 'errors': []}
    saved = md.master_record_for_name('equipment', 'user-a', 'large pot')
    assert saved['id'] == record['id']
    assert saved['name'] == record['name']
    assert saved['display_name_override'] == ''
    assert md.count_equipment_usage(record['id'], user_id='user-a') == 1


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
    assert not any(hook in html for hook in ('data-equipment-row-delete', 'data-master-merge-open', 'data-equipment-row-alias-add'))


SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = process.argv[2];
(async () => {
    const browser = await chromium.launch({channel: 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: options.width, height: 900}, colorScheme: options.dark ? 'dark' : 'light'});
        await context.addCookies([options.cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], writes = [];
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => {if (['error', 'warning'].includes(m.type()) && !m.text().includes('503')) errors.push(m.text());});
        page.on('request', request => {if (request.method() === 'PATCH') writes.push(request.postDataJSON());});
        await page.route('**/static/test-pot.svg', route => route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect x="30" y="60" width="140" height="100" rx="20" fill="#72878b"/></svg>'}));
        if (options.screenshots && [1440, 390].includes(options.width) && !options.dark) {
            const reference = await context.newPage();
            await reference.route('**/static/generated/tomato.png', route => route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="24" fill="tomato"/></svg>'}));
            await reference.goto(base + '/admin/master-data/ingredients?sort=name_asc&limit=500');
            await reference.locator('[data-ingredient-master-row]').first().scrollIntoViewIfNeeded();
            await reference.screenshot({path: require('node:path').join(options.screenshots, `ingredient-reference-${options.width}.png`)});
            await reference.close();
        }
        await page.goto(base + '/admin/master-data/equipment?sort=name_asc&limit=500');
        assert.equal(await page.title(), 'Equipment');
        assert.match(page.url(), /\/admin\/master-data\/equipment/);
        assert(await page.getByRole('heading', {name: 'Equipment', exact: true}).isVisible());
        assert.equal(await page.locator('table thead').count(), 1);
        assert.deepEqual(await page.locator('.master-data-equipment-table thead th').allTextContents(), ['Item', 'Aliases', 'Used In', 'Updated', 'Action']);
        assert.equal(await page.locator('[data-equipment-master-row]').count(), 25);
        const row = page.locator(`[data-equipment-master-row][data-master-record-id="${options.id}"]`);
        const name = row.locator('[data-equipment-row-name]'), save = row.locator('[data-equipment-row-save]');
        const cancel = row.locator('[data-equipment-row-cancel]'), toggle = row.locator('[data-equipment-mobile-toggle]');
        const screenshot = async state => {
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal page overflow');
            assert(await page.locator('.app-content').evaluate(e => e.scrollWidth <= e.clientWidth), 'No clipped horizontal content');
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `equipment-${options.width}-${options.dark ? 'dark-' : ''}${state}.png`)});
        };
        await screenshot('initial');
        await row.scrollIntoViewIfNeeded();
        await page.mouse.move(0, 0);
        assert(await save.isHidden() && await cancel.isHidden());
        assert.equal(await row.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
        await screenshot('rest');
        if (options.width <= 760) {
            assert(await toggle.isVisible() && await name.isHidden());
            assert(await row.locator('.master-data-usage-cell').isVisible());
            assert(await row.locator('.equipment-master-action-cell').isHidden());
            await toggle.focus(); await page.keyboard.press('Enter');
            assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
        } else {
            assert(await toggle.isHidden());
            assert.equal(await name.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
            assert.equal(await name.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
            await row.locator('.master-data-updated-cell').hover();
            assert.notEqual(await row.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
            assert.equal(await name.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
            await screenshot('hover');
            await name.hover();
            assert.notEqual(await name.evaluate(e => getComputedStyle(e).borderTopColor), 'rgba(0, 0, 0, 0)');
        }
        await name.focus(); await page.mouse.move(0, 0);
        assert(await row.evaluate(e => e.classList.contains('is-selected')));
        assert.notEqual(await name.evaluate(e => getComputedStyle(e).outlineStyle), 'none');
        await screenshot('focus');
        await name.fill('Family stockpot');
        assert(await save.isVisible() && await save.isEnabled() && await cancel.isVisible());
        const saveBox = await save.boundingBox(), cancelBox = await cancel.boundingBox();
        await screenshot('dirty');
        if (options.width <= 760) {
            await toggle.click(); assert(await name.isHidden());
            await toggle.click(); assert.equal(await name.inputValue(), 'Family stockpot');
        }
        await name.fill('   ');
        assert.equal(await name.getAttribute('aria-invalid'), 'true');
        assert(await save.isHidden() && await cancel.isVisible());
        assert.equal((await cancel.boundingBox()).x, cancelBox.x, 'Cancel stays in its slot');
        await screenshot('invalid');
        await name.press('Enter'); assert.equal(writes.length, 0);
        await name.press('Escape');
        assert.equal(await name.inputValue(), 'Large pot');
        assert(await save.isHidden() && await cancel.isHidden());
        await name.fill('Cancel this'); await cancel.click();
        assert.equal(await name.inputValue(), 'Large pot');
        assert.equal(writes.length, 0);
        await screenshot('canceled');

        // Gate a real request to inspect saving, then let the server persist it.
        let release;
        const gate = new Promise(resolve => release = resolve);
        await page.route('**/equipment/*/display-name', async route => {await gate; await route.continue();});
        await name.fill('Family stockpot'); await name.press('Enter');
        await page.waitForFunction(id => document.querySelector(`[data-master-record-id="${id}"]`).getAttribute('aria-busy') === 'true', options.id);
        assert(await name.isDisabled() && await save.isDisabled());
        assert.equal(await save.innerText(), 'Saving…');
        assert.equal((await save.boundingBox()).x, saveBox.x);
        assert.equal((await cancel.boundingBox()).x, cancelBox.x);
        await screenshot('saving');
        release();
        await page.waitForFunction(id => document.querySelector(`[data-master-record-id="${id}"] [data-equipment-row-status]`).textContent === 'Saved.', options.id);
        assert(await save.isHidden() && await cancel.isHidden());
        assert.equal(await name.inputValue(), 'Family stockpot');
        assert(await row.locator('[data-equipment-row-reset]').isVisible());
        await screenshot('saved');
        await page.unroute('**/equipment/*/display-name');
        await row.locator('[data-equipment-row-reset]').click();
        assert.equal(await name.inputValue(), 'Large pot');
        assert.equal(writes.length, 1, 'Reset is a draft until Save');
        await cancel.click(); assert.equal(await name.inputValue(), 'Family stockpot');
        await row.locator('[data-equipment-row-reset]').click(); await save.click();
        await page.waitForFunction(id => document.querySelector(`[data-master-record-id="${id}"] [data-equipment-row-status]`).textContent === 'Saved.', options.id);

        // Failure preserves the draft and Cancel restores the last saved name.
        await page.route('**/equipment/*/display-name', route => route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({ok: false, error: 'Temporary test failure'})}));
        await name.fill('Retry name'); await save.click();
        await page.getByText('Temporary test failure', {exact: true}).waitFor();
        assert.equal(await name.inputValue(), 'Retry name');
        assert(await save.isEnabled());
        await cancel.click();
        await page.unroute('**/equipment/*/display-name');
        writes.pop();

        // Existing image overlay and usage references remain keyboard operable.
        const image = row.locator('.master-data-thumbnail');
        await image.focus(); await image.press('Enter');
        const lightbox = page.locator('#recipeImageLightbox');
        assert(await lightbox.isVisible());
        assert(await lightbox.locator('[data-master-image-actions]').isHidden());
        await page.keyboard.press('Escape');
        assert(await image.evaluate(e => e === document.activeElement));
        await row.locator('[data-master-usage-button]').click();
        await page.locator('#masterDataUsageDialog').waitFor({state: 'visible'});
        await page.locator('[data-master-usage-results] a').first().waitFor();
        await page.keyboard.press('Escape');
        assert(await row.locator('[data-master-usage-button]').evaluate(e => e === document.activeElement));
        if (options.width > 760) {
            await page.locator('.app-content').evaluate(e => e.scrollTop += 900);
            const heading = await page.locator('table thead').boundingBox();
            const toolbar = await page.locator('.app-topbar').boundingBox();
            assert(Math.abs(heading.y - toolbar.y - toolbar.height) < 2, 'Whole header sticks flush below application header');
            const headers = await page.locator('table thead th').evaluateAll(es => es.map(e => e.getBoundingClientRect().top));
            assert(headers.every(y => Math.abs(y - heading.y) < 1));
            await screenshot('sticky');
        }
        assert.equal(await page.locator('[data-equipment-row-delete], [data-master-merge-open], [data-equipment-master-display-dialog], .master-data-equipment-details').count(), 0);
        // Existing GET controls must still filter and sort the recipe-derived registry.
        await page.locator('input[name="search"]').fill('Pan 03');
        await page.locator('select[name="sort"]').selectOption('usage_count_desc');
        await page.locator('select[name="limit"]').selectOption('50');
        await page.locator('.master-data-filter-form button[type="submit"]').click();
        await page.waitForURL(/search=Pan/);
        assert.equal(await page.locator('[data-equipment-master-row]').count(), 1);
        assert.match(page.url(), /sort=usage_count_desc/);
        assert.equal(await page.locator('[data-equipment-row-name]').inputValue(), 'Pan 03');
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({saves: writes.length, errors}));
    } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
