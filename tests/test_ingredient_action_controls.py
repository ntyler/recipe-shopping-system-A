"""Browser regressions for Ingredient row action state and safe deletion."""
import base64
import os
from pathlib import Path

import pytest

from PushShoppingList.services import recipe_master_data_service as md
from PushShoppingList.services import recipe_master_image_service as images
from test_ingredient_image_lightbox import playwright_runtime, run_browser
from test_ingredient_inline_editor import editor_app, image_file, tomato
from test_recipe_master_data_routes import sign_in


@pytest.mark.parametrize("viewport", [
    {"width": 1280, "height": 900}, {"width": 1181, "height": 900}, {"width": 390, "height": 844},
    {"width": 320, "height": 568},
], ids=["desktop", "tablet", "phone", "small-phone"])
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
            "imageFolder": str(images.STEP_IMAGE_FOLDER),
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
        await page.route('**/static/generated/recipe_steps/master_ingredient_*.png', route => route.fulfill({
            contentType: 'image/png', path: require('node:path').join(options.imageFolder,
                require('node:path').basename(new URL(route.request().url()).pathname)),
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
        const confirmDelete = row.locator('[data-ingredient-row-confirm-delete]');
        const actionCell = row.locator('.ingredient-action-cell');
        const mergeButton = actionCell.locator('[data-master-merge-open]');
        const mobileToggle = row.locator('[data-ingredient-mobile-toggle]');
        const state = async ({dirty, valid = true}) => {
            await page.waitForFunction(({id, dirty, valid}) => {
                const row = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
                const save = row.querySelector('[data-ingredient-row-save]');
                const cancel = row.querySelector('[data-ingredient-row-cancel]');
                const remove = row.querySelector('[data-ingredient-row-delete]');
                const merge = row.querySelector('[data-master-merge-open]');
                return save.hidden === !dirty && save.disabled === !(dirty && valid) && cancel.hidden === !dirty
                    && merge.hidden === (dirty && !valid)
                    && (dirty ? remove.hidden : !remove.disabled && !remove.hidden);
            }, {id: options.recordId, dirty, valid});
        };
        const capture = async label => {
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
                `${label}: page has no horizontal overflow`);
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots,
                `ingredient-actions-${options.viewport.width}-${label}.png`)});
        };
        const visibleActions = () => actionCell.locator('.ingredient-row-actions button:visible').allTextContents();
        let originalCell, originalMerge, originalActions;
        const alignedActions = async () => {
            const buttons = actionCell.locator('.ingredient-row-actions button:visible');
            const bounds = await buttons.evaluateAll(elements => elements.map(element => {
                const rect = element.getBoundingClientRect();
                return {left: rect.left, right: rect.right, top: rect.top, height: rect.height};
            }));
            assert(bounds.length >= 2);
            assert(bounds.every((box, index) => Math.abs(box.top - bounds[0].top) <= 1
                && Math.abs(box.height - bounds[0].height) <= 1
                && (!index || box.left >= bounds[index - 1].right)),
                'Visible actions stay in one compact horizontal row');
            const cell = await actionCell.boundingBox();
            assert(bounds[0].left >= cell.x && bounds.at(-1).right <= cell.x + cell.width + 1,
                'The compact actions fit inside their Action cell');
            const actions = await actionCell.locator('.ingredient-row-actions').boundingBox();
            if (originalCell) {
                assert(Math.abs(cell.x - originalCell.x) <= 1 && Math.abs(cell.width - originalCell.width) <= 1,
                    'Action column stays fixed across action states');
                assert(Math.abs(actions.height - originalActions.height) <= 1, 'Changing actions keeps the same height');
            } else { originalCell = cell; originalActions = actions; }
            if (await mergeButton.isVisible()) {
                const merge = await mergeButton.boundingBox();
                assert(Math.abs(merge.x + merge.width - actions.x - actions.width) <= 1, 'Merge stays right-aligned');
                if (originalMerge) assert(Math.abs(merge.x - originalMerge.x) <= 1, 'Merge does not shift when actions change');
                else originalMerge = merge;
            }
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
        if (options.viewport.width <= 760) {
            assert(await mobileToggle.isVisible());
            assert.equal(await mobileToggle.getAttribute('aria-expanded'), 'false');
            assert(await actionCell.isHidden(), 'Collapsed phone summary does not show actions');
            assert(await mobileToggle.locator('[data-ingredient-mobile-name]').isVisible());
            assert(await row.locator('.master-data-usage-cell').isVisible());
            await capture('collapsed');
            await mobileToggle.click();
            assert.equal(await mobileToggle.getAttribute('aria-expanded'), 'true');
            assert(await actionCell.isVisible(), 'Expanding the phone row reveals its actions');
            await mobileToggle.click();
            assert(await actionCell.isHidden(), 'Collapsing the phone row hides its actions again');
            await mobileToggle.click();
        } else {
            assert(await mobileToggle.isHidden());
            const aliasHeading = page.locator('table[aria-label="Ingredient"] th').filter({hasText: /^Aliases$/});
            if (await aliasHeading.isVisible()) assert(await aliasHeading
                .evaluate(element => element.scrollWidth <= element.clientWidth + 1),
                'The desktop Aliases heading fits its column');
        }
        await alignedActions();
        assert.deepEqual(await visibleActions(), ['Delete', 'Merge duplicate']);
        assert.equal(await actionCell.getByRole('button', {name: /^Save /}).count(), 0);
        await mergeButton.hover();
        await mergeButton.focus();
        await state({dirty: false});
        await capture('resting');
        await name.click();
        await state({dirty: false});
        await name.fill(' Disposable celery ');
        await state({dirty: false});
        await name.fill('Disposable celery');
        assert.equal(await row.locator('.ingredient-row-more, [popover], [popovertarget]').count(), 0);
        assert(await mergeButton.isEnabled());
        assert(await mergeButton.isVisible());
        assert.equal(await mergeButton.innerText(), 'Merge duplicate');
        assert(!/Manage Image/i.test(await actionCell.innerText()));
        await state({dirty: false});

        await name.fill('Fresh celery');
        await state({dirty: true});
        assert.deepEqual(await visibleActions(), ['Save', 'Cancel', 'Merge duplicate']);
        assert(await mergeButton.isDisabled());
        assert.match(await mergeButton.getAttribute('title'), /save|cancel|changes/i,
            'A disabled merge action explains how to make it available');
        await state({dirty: true});
        await alignedActions();
        await capture('dirty');
        await cancel.click();
        await state({dirty: false});
        assert.equal(await name.inputValue(), 'Disposable celery');
        assert.equal(saves.length, 0);

        // Each field can create a draft independently of the ingredient name.
        const aliasTrigger = row.locator('[data-ingredient-row-alias]');
        const aliases = page.locator('#ingredientAliasManager');
        const aliasInput = aliases.getByRole('textbox', {name: 'New accepted alias'});
        await aliasTrigger.click();
        await aliasInput.fill('Carrot');
        await state({dirty: true, valid: false});
        assert.equal(await aliasInput.getAttribute('aria-invalid'), 'true');
        assert.match(await aliases.locator('[data-ingredient-editor-alias-error]').innerText(), /Carrot/);
        await aliasInput.fill('celery stalk');
        await state({dirty: true});
        await aliasInput.press('Enter');
        await aliasInput.press('Escape');
        assert.deepEqual(await visibleActions(), ['Save', 'Cancel', 'Merge duplicate']);
        await alignedActions();
        await cancel.click();
        await state({dirty: false});
        assert.equal(await row.locator('[data-ingredient-alias]').count(), 0);

        await row.locator('button.master-data-store-section-trigger').click();
        await page.locator('.recipe-edit-store-section-menu [role="option"][data-store-section-value="DAIRY & EGGS"]').click();
        await state({dirty: true});
        assert.equal(await name.inputValue(), 'Disposable celery');
        await alignedActions();
        await cancel.click();
        await state({dirty: false});
        assert.equal(await row.locator('[data-ingredient-row-section]').inputValue(), 'PRODUCE');

        await row.locator('[data-master-image-empty]').click();
        const lightbox = page.locator('#recipeImageLightbox');
        const chooser = page.waitForEvent('filechooser');
        await lightbox.getByRole('button', {name: 'Replace Image', exact: true}).click();
        await (await chooser).setFiles({name: 'celery-preview.png', mimeType: 'image/png', buffer: Buffer.from(options.image, 'base64')});
        await state({dirty: true});
        await lightbox.getByRole('button', {name: 'Close', exact: true}).click();
        assert.deepEqual(await visibleActions(), ['Save', 'Cancel', 'Merge duplicate']);
        await alignedActions();
        await cancel.click();
        await state({dirty: false});
        assert(await row.locator('[data-master-image-empty]').isVisible());
        assert.equal(saves.length, 0, 'Alias, section and image previews do not save implicitly');

        await name.fill('');
        await state({dirty: true, valid: false});
        assert.deepEqual(await visibleActions(), ['Save', 'Cancel']);
        assert.equal(await name.getAttribute('aria-invalid'), 'true');
        assert.match(await row.locator('[data-ingredient-row-name-error]').innerText(), /ingredient name/);
        await alignedActions();
        await capture('invalid');
        await cancel.click();
        await state({dirty: false});
        assert.equal(await name.inputValue(), 'Disposable celery');
        await name.fill('Carrot');
        await state({dirty: true, valid: false});
        await name.fill('Fresh celery');
        await state({dirty: true});
        let releaseSave;
        const saveGate = new Promise(resolve => { releaseSave = resolve; });
        await page.route(`**/admin/master-data/ingredients/${options.recordId}`, async route => {
            await saveGate;
            await route.continue();
        });
        await save.click();
        assert.deepEqual(await visibleActions(), ['Saving…', 'Cancel', 'Merge duplicate']);
        assert(await save.isDisabled() && await cancel.isDisabled());
        await alignedActions();
        releaseSave();
        await state({dirty: false});
        assert.equal(await name.inputValue(), 'Fresh celery');
        assert.equal(saves.length, 1);
        assert.equal(saves[0].name, 'Fresh celery');

        await alignedActions();
        await remove.click();
        assert.deepEqual(await visibleActions(), ['Confirm delete', 'Cancel']);
        assert.equal(await confirmDelete.getAttribute('aria-label'), 'Confirm delete Fresh celery');
        assert(await save.isHidden());
        assert(await cancel.evaluate(element => element === document.activeElement));
        if (options.viewport.width <= 760) {
            assert.equal(await mobileToggle.getAttribute('aria-disabled'), 'true');
            assert.match(await mobileToggle.getAttribute('aria-label'), /Confirm or cancel deletion/);
        }
        assert.equal(deletes.length, 0, 'Opening confirmation sends no deletion');
        await alignedActions();
        await capture('delete-confirmation');
        await cancel.click();
        assert.equal(deletes.length, 0, 'Canceling confirmation sends no deletion');
        assert.equal(saves.length, 1, 'Deletion confirmation never sends a save');
        assert(await row.isVisible());
        await state({dirty: false});
        assert(await remove.evaluate(element => element === document.activeElement));
        await remove.click();
        await cancel.press('Escape');
        await state({dirty: false});
        await alignedActions();
        const response = page.waitForResponse(response => response.request().method() === 'POST'
            && new URL(response.url()).pathname === `/admin/master-data/ingredients/${options.recordId}/delete`);
        let releaseDelete;
        const deleteGate = new Promise(resolve => { releaseDelete = resolve; });
        await page.route(`**/admin/master-data/ingredients/${options.recordId}/delete`, async route => {
            await deleteGate;
            await route.continue();
        });
        await remove.click();
        await confirmDelete.click();
        assert.deepEqual(await visibleActions(), ['Deleting…', 'Cancel']);
        assert(await confirmDelete.isDisabled() && await cancel.isDisabled());
        assert(await save.isHidden());
        await alignedActions();
        releaseDelete();
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
