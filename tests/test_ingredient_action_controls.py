"""Browser regressions for Ingredient row action state and safe deletion."""
import base64
import os
from pathlib import Path

import pytest

from PushShoppingList.services import recipe_master_data_service as md
from test_ingredient_image_lightbox import playwright_runtime, run_browser
from test_ingredient_inline_editor import editor_app, image_file, tomato
from test_recipe_master_data_routes import sign_in


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "phone"])
def test_ingredient_actions_track_valid_changes_and_confirm_eligible_deletion(editor_app, viewport):
    playwright_runtime()
    fixture_url = "https://example.com/unused-action-fixtures"
    md.sync_recipe_master_records(fixture_url, recipe_data={"ingredients": [
        {"ingredient": "Disposable celery", "store_section": "Produce"},
        {"ingredient": "Protected parsley", "store_section": "Produce"},
    ]}, user_id="user-a")
    md.remove_recipe_master_records_for_recipe(fixture_url, user_id="user-a")
    unused = md.master_record_for_name("ingredients", "user-a", "disposable celery")
    seeded = md.master_record_for_name("ingredients", "user-a", "protected parsley")
    # The current ingredient registry has no seeds. Exercise persisted seed
    # metadata so a future or imported seeded record cannot expose Delete.
    with md.recipe_master_connection() as connection:
        if "is_seeded" not in md.recipe_master_column_names(connection, "ingredients"):
            connection.execute("ALTER TABLE ingredients ADD COLUMN is_seeded INTEGER NOT NULL DEFAULT 0")
        connection.execute("UPDATE ingredients SET is_seeded = 1 WHERE id = ?", (seeded["id"],))
    with editor_app.test_client() as client:
        sign_in(client, "user-a")
        cookie = client.get_cookie(editor_app.config["SESSION_COOKIE_NAME"])
        options = {
            "cookie": {"name": cookie.key, "value": cookie.value, "domain": "127.0.0.1", "path": "/"},
            "recordId": unused["id"], "seededId": seeded["id"], "referencedId": tomato()["id"],
            "viewport": viewport,
            "image": base64.b64encode(image_file().getvalue()).decode("ascii"),
        }
    if screenshot_folder := os.environ.get("AI_PANTRY_LIGHTBOX_SCREENSHOTS"):
        screenshot_path = Path(screenshot_folder).resolve()
        repository_path = Path(__file__).resolve().parents[1]
        assert screenshot_path != repository_path and repository_path not in screenshot_path.parents
        screenshot_path.mkdir(parents=True, exist_ok=True)
        options["screenshots"] = str(screenshot_path)
    result = run_browser(editor_app, _ACTION_BROWSER_SCENARIO, options)
    assert result == {"saveRequests": 1, "deleteRequests": 1}
    assert md.master_record_for_id("ingredients", unused["id"], user_id="user-a") is None
    assert md.master_record_for_id("ingredients", seeded["id"], user_id="user-a")
    assert tomato()


_ACTION_BROWSER_SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = process.argv[2];
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: options.viewport});
        await context.addCookies([options.cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], saves = [], deletes = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {
            if (['warning', 'error'].includes(message.type())) errors.push(message.text());
        });
        page.on('request', request => {
            const path = new URL(request.url()).pathname;
            if (request.method() !== 'POST') return;
            if (path === `/admin/master-data/ingredients/${options.recordId}`) saves.push(request.postDataJSON());
            if (path === `/admin/master-data/ingredients/${options.recordId}/delete`) deletes.push(request.postDataJSON());
        });
        await page.route('**/static/generated/tomato.png', route => route.fulfill({
            contentType: 'image/png', body: Buffer.from(options.image, 'base64'),
        }));
        await page.goto(`${base}/admin/master-data/ingredients?sort=name_asc`);
        assert.equal(await page.title(), 'Ingredient');
        assert.match(page.url(), /\/admin\/master-data\/ingredients/);
        assert(await page.getByRole('heading', {name: 'Ingredient', exact: true}).isVisible());
        const recordRow = id => page.locator(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
        const row = recordRow(options.recordId);
        const name = row.locator('[data-ingredient-row-name]');
        const save = row.locator('[data-ingredient-row-save]');
        const cancel = row.locator('[data-ingredient-row-cancel]');
        const remove = row.locator('[data-ingredient-row-delete]');
        const actionCell = row.locator('.ingredient-action-cell');
        const mergeButton = actionCell.locator('[data-master-merge-open]');
        const state = async ({dirty, valid = true}) => {
            await page.waitForFunction(({id, dirty, valid}) => {
                const row = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
                const save = row.querySelector('[data-ingredient-row-save]');
                const cancel = row.querySelector('[data-ingredient-row-cancel]');
                const remove = row.querySelector('[data-ingredient-row-delete]');
                return save.disabled === !(dirty && valid) && cancel.hidden === !dirty
                    && (dirty ? remove.disabled || remove.hidden : !remove.disabled && !remove.hidden);
            }, {id: options.recordId, dirty, valid});
        };
        const capture = async label => {
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
                `${label}: page has no horizontal overflow`);
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots,
                `ingredient-actions-${options.viewport.width}-${label}.png`)});
        };
        assert.deepEqual(await page.locator('table[aria-label="Ingredient"] thead th').allTextContents(),
            ['Order', 'Item', 'Aliases', 'Store Section', 'Used In', 'Action']);
        assert.equal(await row.locator(':scope > td').count(), 6);
        assert.equal(await actionCell.locator('[data-ingredient-row-save]').count(), 1);
        assert.equal(await actionCell.locator('[data-ingredient-row-delete]').count(), 1);
        assert.equal(await page.locator('[data-ingredient-row-image]').count(), 0);
        assert.equal(await recordRow(options.seededId).locator('[data-ingredient-row-delete]').count(), 0);
        assert.equal(await recordRow(options.referencedId).locator('[data-ingredient-row-delete]').count(), 0);
        await state({dirty: false});
        await row.scrollIntoViewIfNeeded();
        await capture('resting');
        await name.click();
        await state({dirty: false});
        await name.fill(' Disposable celery ');
        await state({dirty: false});
        await name.fill('Disposable celery');
        assert.equal(await row.locator('.ingredient-row-more, [popover], [popovertarget]').count(), 0);
        assert(await mergeButton.isEnabled());
        assert(await mergeButton.isVisible());
        assert.equal(await mergeButton.innerText(), 'Merge duplicate…');
        assert(!/Manage Image/i.test(await actionCell.innerText()));
        await state({dirty: false});

        await name.fill('Fresh celery');
        await state({dirty: true});
        assert(await mergeButton.isDisabled());
        await state({dirty: true});
        await capture('dirty');
        await cancel.click();
        await state({dirty: false});
        assert.equal(await name.inputValue(), 'Disposable celery');
        assert.equal(saves.length, 0);

        await name.fill('');
        await state({dirty: true, valid: false});
        await cancel.click();
        await state({dirty: false});
        assert.equal(await name.inputValue(), 'Disposable celery');
        await name.fill('Carrot');
        await state({dirty: true, valid: false});
        await name.fill('Fresh celery');
        await state({dirty: true});
        await save.click();
        await state({dirty: false});
        assert.equal(await name.inputValue(), 'Fresh celery');
        assert.equal(saves.length, 1);
        assert.equal(saves[0].name, 'Fresh celery');

        let dismissedMessage = '';
        page.once('dialog', async dialog => {
            dismissedMessage = dialog.message();
            await dialog.dismiss();
        });
        await remove.click();
        assert.match(dismissedMessage, /Fresh celery/);
        assert.match(dismissedMessage, /delete/i);
        assert.equal(deletes.length, 0, 'Dismissing confirmation sends no deletion');
        assert(await row.isVisible());
        await state({dirty: false});
        const response = page.waitForResponse(response => response.request().method() === 'POST'
            && new URL(response.url()).pathname === `/admin/master-data/ingredients/${options.recordId}/delete`);
        page.once('dialog', dialog => dialog.accept());
        await remove.click();
        assert.equal((await response).status(), 200);
        await row.waitFor({state: 'detached'});
        assert.equal(deletes.length, 1);
        assert.equal(deletes[0].confirm, true);
        assert(await recordRow(options.seededId).isVisible());
        assert(await recordRow(options.referencedId).isVisible());
        await capture('deleted');
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({saveRequests: saves.length, deleteRequests: deletes.length}));
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
