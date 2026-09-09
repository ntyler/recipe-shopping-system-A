"""Conflict resolutions are explicit and use the server's stable Equipment IDs."""
import os
from pathlib import Path

import pytest

from PushShoppingList.services import equipment_registry_service as registry
from PushShoppingList.services import recipe_master_data_service as md
from test_ingredient_image_lightbox import playwright_runtime, run_browser
from test_recipe_master_data_routes import configure_master_data_app, sign_in


@pytest.mark.parametrize('width', [1440, 390])
def test_alias_conflict_remove_and_confirmed_merge(monkeypatch, tmp_path, width):
    playwright_runtime()
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    md.sync_recipe_master_records('https://example.com/cake', recipe_data={
        'equipment': [{'equipment': 'Cake pan', 'equipment_section': 'BAKEWARE'}],
    }, user_id='user-a')
    current = md.master_record_for_name('equipment', 'user-a', 'Cake pan')
    with md.recipe_master_connection(user_id='user-a') as connection:
        target = md.upsert_master_record(connection, 'equipment', 'user-a', '9-inch cake pan', equipment_section='BAKEWARE')
        other = md.upsert_master_record(connection, 'equipment', 'user-a', 'Another round pan', equipment_section='BAKEWARE')
        # Identical presentation labels must never select the wrong merge owner.
        connection.execute('UPDATE equipment SET display_name_override = ? WHERE id = ?', ('9-inch cake pan', other['id']))
    assert registry.update_equipment_master_record(current['id'], {'aliases': ['Baking pan']}, user_id='user-a')['ok']
    with app.test_client() as client:
        sign_in(client, 'user-a')
        cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
        options = {
            'cookie': {'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'},
            'id': current['id'], 'targetId': target['id'], 'otherId': other['id'], 'width': width,
        }
    if artifacts := os.environ.get('AI_PANTRY_BROWSER_ARTIFACTS'):
        folder = Path(artifacts).resolve()
        repository = Path(__file__).resolve().parents[1]
        assert folder != repository and repository not in folder.parents
        folder.mkdir(parents=True, exist_ok=True)
        options['screenshots'] = str(folder)
    result = run_browser(app, SCENARIO, options)
    assert result['errors'] == []
    assert result['patches'] == 2 and result['merges'] == 1
    assert registry.equipment_editor_record(current['id'], user_id='user-a') is None
    saved = registry.equipment_editor_record(target['id'], user_id='user-a')
    assert {alias.casefold() for alias in saved['aliases']} >= {'cake pan', 'baking pan'}
    assert md.count_equipment_usage(target['id'], user_id='user-a') == 1
    assert md.count_equipment_usage(other['id'], user_id='user-a') == 0


SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = process.argv[2];
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: options.width, height: 900}});
        await context.addCookies([options.cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], patches = [], merges = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {
            if (['error', 'warning'].includes(message.type()) && !message.text().includes('409')) errors.push(message.text());
        });
        page.on('request', request => {
            if (request.method() === 'PATCH') patches.push(request.postDataJSON());
            if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/merge')) merges.push(request.postData());
        });
        await page.goto(base + '/admin/master-data/equipment?sort=name_asc&limit=500');
        assert.equal(await page.title(), 'Equipment');
        assert.match(page.url(), /\/admin\/master-data\/equipment/);
        assert(await page.getByRole('heading', {name: 'Equipment', exact: true}).isVisible());
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        const row = page.locator(`[data-equipment-master-row][data-master-record-id="${options.id}"]`);
        if (options.width < 760) await row.locator('[data-equipment-mobile-toggle]').click();
        const conflicts = row.locator('[data-equipment-alias-conflicts]');
        const snapshot = async name => {
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `equipment-conflict-${name}-${options.width}.png`)});
        };
        const readCurrent = async () => {
            const response = await context.request.get(base + `/api/master-data/equipment/${options.id}/editor`);
            assert(response.ok()); return (await response.json()).record;
        };
        const addConflict = async () => {
            await row.locator('[data-equipment-row-alias]').click();
            await page.locator('[data-equipment-editor-alias-input]').fill('9-inch cake pan');
            await page.locator('[data-equipment-editor-alias-add]').click();
            await page.locator('[data-equipment-editor-close-aliases]').click();
            const response = page.waitForResponse(response => response.request().method() === 'PATCH');
            await row.locator('[data-equipment-row-save]').click();
            const result = await response;
            assert.equal(result.status(), 409);
            const error = await result.json();
            assert.equal(error.alias_conflicts[0].equipment_id, options.targetId);
            await conflicts.waitFor({state: 'visible'});
            assert((await conflicts.innerText()).includes('“9-inch cake pan” is currently assigned to “9-inch cake pan”.'));
            assert(await conflicts.getByRole('button', {name: 'Remove alias', exact: true}).isEnabled());
            assert(await conflicts.getByRole('button', {name: 'Merge duplicate', exact: true}).isEnabled());
        };
        await row.locator('[data-equipment-row-name]').fill('Family cake pan');
        await addConflict();
        assert.equal((await readCurrent()).name, 'Cake pan', 'Failed save does not persist other fields');
        await conflicts.locator('summary').click();
        assert((await conflicts.innerText()).includes(`Editing Equipment #${options.id}; assigned Equipment #${options.targetId}.`));
        assert((await conflicts.innerText()).includes('Normalized alias: 9 inch cake pan.'));
        await conflicts.evaluate(node => node.scrollIntoView({block: 'center'}));
        await snapshot('reported');
        await conflicts.getByRole('button', {name: 'Remove alias', exact: true}).click();
        assert.equal(await row.locator('[data-equipment-alias="9-inch cake pan"]').count(), 0);
        assert(await conflicts.isHidden());
        assert.deepEqual((await readCurrent()).aliases, ['Baking pan']);
        assert.equal((await readCurrent()).name, 'Cake pan');
        assert.equal(patches.length, 1, 'Remove alias only edits the local draft');
        assert.equal(merges.length, 0);
        await row.locator('[data-equipment-row-cancel]').click();
        await addConflict();

        // Canceling the explicit draft-discard prompt preserves the draft and makes no merge request.
        page.once('dialog', dialog => dialog.dismiss());
        await conflicts.getByRole('button', {name: 'Merge duplicate', exact: true}).click();
        assert(await conflicts.isVisible());
        assert.equal(await row.locator('[data-equipment-alias="9-inch cake pan"]').count(), 1);
        assert.equal(merges.length, 0);
        page.once('dialog', async dialog => {
            assert(dialog.message().includes('Discard unsaved changes'));
            assert(dialog.message().includes('No records change until you confirm Merge equipment'));
            await dialog.accept();
        });
        const optionsRequest = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/merge-options'));
        await conflicts.getByRole('button', {name: 'Merge duplicate', exact: true}).click();
        const dialog = page.locator('[data-master-merge-dialog]');
        await dialog.waitFor({state: 'visible'});
        assert.equal(new URL((await optionsRequest).url()).searchParams.get('target_equipment_id'), String(options.targetId));
        await page.waitForFunction(id => document.querySelector('[data-master-merge-target-id]').value === String(id), options.targetId);
        assert.equal(await dialog.locator('[data-master-merge-target-id]').inputValue(), String(options.targetId));
        const selected = dialog.locator('[role="option"][aria-selected="true"]');
        assert.equal(await selected.getAttribute('data-ingredient-id'), String(options.targetId));
        assert.equal(await dialog.locator(`[role="option"][data-ingredient-id="${options.otherId}"]`).getAttribute('aria-selected'), 'false');
        assert((await dialog.innerText()).includes('Recipe references will move'));
        assert.equal(merges.length, 0, 'Opening and preselecting the merge dialog does not merge records');
        assert.equal((await readCurrent()).id, options.id);
        await snapshot('merge-review');
        const response = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/merge'));
        await dialog.locator('[data-master-merge-submit]').click();
        const result = await response;
        assert(result.ok(), JSON.stringify(await result.json()));
        await row.waitFor({state: 'detached'});
        assert.equal(merges.length, 1);
        assert(merges[0].includes(String(options.targetId)));
        await snapshot('merged');
        console.log(JSON.stringify({errors, patches: patches.length, merges: merges.length}));
    } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
"""
