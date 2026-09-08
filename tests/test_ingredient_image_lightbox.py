"""Real-browser regressions for Ingredient inline editing and image drafts."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

from PIL import Image
import pytest
from werkzeug.serving import make_server

from PushShoppingList.services import recipe_master_image_service as images
from PushShoppingList.services import recipe_master_data_service as md
from test_ingredient_inline_editor import editor_app, tomato
from test_recipe_master_data_routes import sign_in


def playwright_runtime():
    node = shutil.which("node")
    module = os.environ.get("AI_PANTRY_PLAYWRIGHT_MODULE", "playwright")
    if not node or subprocess.run(
        [node, "-e", "require.resolve(process.argv[1])", module], capture_output=True
    ).returncode:
        pytest.skip("Install Playwright for Node or set AI_PANTRY_PLAYWRIGHT_MODULE")
    return node, module


def run_browser(editor_app, scenario, options):
    node, module = playwright_runtime()
    server = make_server("127.0.0.1", 0, editor_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [node, "-e", scenario, module, f"http://127.0.0.1:{server.server_port}"],
            input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ingredient_lightbox_reuses_pending_image_actions(editor_app, monkeypatch):
    playwright_runtime()

    picture = BytesIO()
    Image.new("RGB", (800, 600), "#b95b32").save(picture, format="PNG")
    image_bytes = picture.getvalue()
    responsive_images = []
    for label, size in [("wide", (1600, 900)), ("panorama", (1600, 400)), ("portrait", (900, 1600))]:
        picture = BytesIO()
        Image.new("RGB", size, "#b95b32").save(picture, format="PNG")
        responsive_images.append({
            "label": label, "width": size[0], "height": size[1],
            "image": base64.b64encode(picture.getvalue()).decode("ascii"),
        })
    monkeypatch.setattr(images, "request_master_ingredient_image_bytes", lambda *_: image_bytes)
    original = tomato()
    original_empty = md.master_record_for_name("ingredients", "user-a", "carrot")
    assert not original_empty["image_url"]
    with editor_app.test_client() as client:
        sign_in(client, "user-a")
        cookie = client.get_cookie(editor_app.config["SESSION_COOKIE_NAME"])
        options = {
            "cookie": {"name": cookie.key, "value": cookie.value, "domain": "127.0.0.1", "path": "/"},
            "recordId": original["id"],
            "emptyRecordId": original_empty["id"],
            "image": base64.b64encode(image_bytes).decode("ascii"),
            "imageFolder": str(images.STEP_IMAGE_FOLDER),
            "responsiveImages": responsive_images,
        }
    if screenshot_folder := os.environ.get("AI_PANTRY_LIGHTBOX_SCREENSHOTS"):
        screenshot_path = Path(screenshot_folder).resolve()
        repository_path = Path(__file__).resolve().parents[1]
        assert screenshot_path != repository_path and repository_path not in screenshot_path.parents, \
            "Keep optional browser screenshots outside the repository"
        screenshot_path.mkdir(parents=True, exist_ok=True)
        options["screenshots"] = str(screenshot_path)
    result_data = run_browser(editor_app, _BROWSER_SCENARIO, options)
    assert result_data["saveRequests"] == 1
    assert tomato()["image_url"] == result_data["savedImage"]
    assert tomato()["image_url"] != original["image_url"]
    assert tomato()["name"] == original["name"]
    assert tomato()["store_section"] == original["store_section"]
    assert result_data["emptySaveRequests"] == 2
    assert md.master_record_for_name("ingredients", "user-a", "carrot")["image_url"] == ""


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "phone"])
def test_ingredient_edits_stay_in_row_and_save_together(editor_app, monkeypatch, viewport):
    playwright_runtime()
    md.sync_recipe_master_records(
        "https://example.com/inline-scroll-fixture",
        recipe_data={"ingredients": [
            {"ingredient": f"Apple {index:02}", "store_section": "Produce"} for index in range(12)
        ] + [
            {"ingredient": f"Zucchini {index:02}", "store_section": "Produce"} for index in range(12)
        ]}, user_id="user-a",
    )
    picture = BytesIO()
    Image.new("RGB", (800, 600), "#b95b32").save(picture, format="PNG")
    image_bytes = picture.getvalue()
    monkeypatch.setattr(images, "request_master_ingredient_image_bytes", lambda *_: image_bytes)
    record = tomato()
    moved = md.move_ingredient_master_record(
        record["id"], 14,
        [item["id"] for item in sorted(md.list_ingredients(user_id="user-a"), key=lambda item: item["sort_order"])
         if item["store_section"] == "PRODUCE"],
        user_id="user-a",
    )
    assert moved["ok"]
    with editor_app.test_client() as client:
        sign_in(client, "user-a")
        cookie = client.get_cookie(editor_app.config["SESSION_COOKIE_NAME"])
        options = {
            "cookie": {"name": cookie.key, "value": cookie.value, "domain": "127.0.0.1", "path": "/"},
            "recordId": record["id"], "viewport": viewport,
            "image": base64.b64encode(image_bytes).decode("ascii"),
            "imageFolder": str(images.STEP_IMAGE_FOLDER),
        }
    if screenshot_folder := os.environ.get("AI_PANTRY_LIGHTBOX_SCREENSHOTS"):
        screenshot_path = Path(screenshot_folder).resolve()
        repository_path = Path(__file__).resolve().parents[1]
        assert screenshot_path != repository_path and repository_path not in screenshot_path.parents
        screenshot_path.mkdir(parents=True, exist_ok=True)
        options["screenshots"] = str(screenshot_path)
    result = run_browser(editor_app, _INLINE_BROWSER_SCENARIO, options)
    with editor_app.test_client() as client:
        sign_in(client, "user-a")
        saved = client.get(f'/api/master-data/ingredients/{record["id"]}/editor').json["record"]
    assert saved["name"] == "Roma tomato"
    assert saved["store_section"] == "DAIRY & EGGS"
    assert set(saved["aliases"]) >= {"salad tomato", "plum tomato"}
    assert saved["image_url"] == result["savedImage"] != record["image_url"]
    assert result["saveRequests"] == 1


_INLINE_BROWSER_SCENARIO = r"""
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
        const errors = [], saves = [], orderWrites = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (['warning', 'error'].includes(message.type())) errors.push(message.text()); });
        page.on('request', request => {
            if (request.method() === 'POST' && new URL(request.url()).pathname === `/admin/master-data/ingredients/${options.recordId}`)
                saves.push(request.postDataJSON());
            if (request.method() === 'PATCH' && new URL(request.url()).pathname.includes('/order')) orderWrites.push(request.url());
        });
        await page.route('**/static/generated/tomato.png', route => route.fulfill({contentType: 'image/png', body: Buffer.from(options.image, 'base64')}));
        await page.route('**/static/generated/recipe_steps/master_ingredient_*.png', route => route.fulfill({
            contentType: 'image/png', path: require('node:path').join(options.imageFolder, require('node:path').basename(new URL(route.request().url()).pathname)),
        }));
        await page.goto(`${base}/admin/master-data/ingredients?sort=manual_order`);
        assert.equal(await page.title(), 'Ingredient');
        assert.match(page.url(), /\/admin\/master-data\/ingredients/);
        const row = page.locator(`[data-ingredient-master-row][data-master-record-id="${options.recordId}"]`);
        if (options.viewport.width <= 760) await row.locator('[data-ingredient-mobile-toggle]').click();
        const name = row.locator('[data-ingredient-row-name]');
        const section = row.locator('[data-ingredient-row-section]');
        const sectionTrigger = row.locator('button.master-data-store-section-trigger');
        const save = row.locator('[data-ingredient-row-save]');
        const cancel = row.locator('[data-ingredient-row-cancel]');
        const aliasTrigger = row.locator('[data-ingredient-row-alias]');
        const aliases = page.locator('#ingredientAliasManager');
        const aliasInput = aliases.getByRole('textbox', {name: 'New accepted alias'});
        const mergeButton = row.locator('.ingredient-action-cell [data-master-merge-open]');
        const lightbox = page.locator('#recipeImageLightbox');
        const imageClose = lightbox.getByRole('button', {name: 'Close', exact: true});
        const focused = locator => locator.evaluate(element => document.activeElement === element);
        const persisted = () => page.request.get(`${base}/api/master-data/ingredients/${options.recordId}/editor`).then(response => response.json()).then(data => data.record);
        const waitEnabled = async locator => {
            const deadline = Date.now() + 10000;
            while (await locator.isDisabled()) {
                assert(Date.now() < deadline, 'Row action did not become enabled');
                await new Promise(resolve => setTimeout(resolve, 10));
            }
        };
        const noExpansion = async () => {
            assert.equal(await page.locator('[data-ingredient-editor-form], .ingredient-editor-row').count(), 0);
            assert.equal(await page.getByRole('heading', {name: /^Edit /}).count(), 0);
        };
        const scroll = () => row.evaluate(element => {
            const positions = [{x: window.scrollX, y: window.scrollY,
                maxY: document.documentElement.scrollHeight - document.documentElement.clientHeight}];
            for (let parent = element.parentElement; parent; parent = parent.parentElement)
                if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) positions.push({x: parent.scrollLeft, y: parent.scrollTop,
                    maxY: parent.scrollHeight - parent.clientHeight});
            return positions;
        });
        const unchangedScroll = async (before, label) => {
            await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
            const after = await scroll();
            assert(before.length === after.length && before.every((position, index) =>
                Math.abs(position.x - after[index].x) <= 1
                && Math.abs(Math.min(position.y, after[index].maxY) - after[index].y) <= 1),
                `${label} preserves scroll: ${JSON.stringify(before)} -> ${JSON.stringify(after)}`);
            // Removing a wrapped alias can shorten content at the bottom. The
            // browser clamps scrollTop to the new maximum; keep subsequent
            // checks anchored to that reachable position.
            before.forEach((position, index) => { position.y = Math.min(position.y, after[index].maxY); });
        };
        const capture = async label => {
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `ingredient-inline-${options.viewport.width}-${label}.png`)});
        };
        await row.evaluate(element => element.scrollIntoView({block: 'center'}));
        const initialScroll = await scroll();
        assert(initialScroll.some(position => position.y > 0), 'Regression exercises an already scrolled table');
        assert(await cancel.isHidden());
        assert(await save.isDisabled());
        await noExpansion();
        await capture('initial');

        // Row clicks keep the compact action controls in their resting state.
        await row.locator('[data-ingredient-order-number]').click();
        await noExpansion();
        assert.equal(await row.locator('.ingredient-row-more, [popover], [popovertarget]').count(), 0);
        assert(await mergeButton.isVisible());
        assert.match(await mergeButton.getAttribute('title'), /Deleting this ingredient would break recipe references/);
        assert(await cancel.isHidden());
        await unchangedScroll(initialScroll, 'Resting row actions');

        // Focusing a clean row keeps its resting action state.
        await name.click();
        assert(await focused(name));
        assert(await cancel.isHidden());
        assert(await save.isDisabled());
        await name.press('Escape');
        assert(await cancel.isHidden());
        await unchangedScroll(initialScroll, 'Name activation and Escape');
        await name.fill('Unwanted tomato');
        await waitEnabled(save);
        await cancel.click();
        assert.equal(await name.inputValue(), 'Tomato');
        assert(await cancel.isHidden());
        assert(await save.isDisabled());
        await unchangedScroll(initialScroll, 'Name Cancel');

        // Keyboard ordering stays pending and Cancel restores the former order.
        const orderHandle = row.locator('[data-ingredient-order-handle]');
        const orderNumber = row.locator('[data-ingredient-order-number]');
        const originalOrder = Number(await orderNumber.innerText());
        const originalRecord = await persisted();
        await orderHandle.press('ArrowDown');
        await waitEnabled(save);
        assert.equal(Number(await orderNumber.innerText()), originalOrder + 1);
        assert.equal((await persisted()).sort_order, originalRecord.sort_order);
        assert.equal(orderWrites.length, 0, 'Ordering creates a draft instead of a separate write');
        await cancel.click();
        assert.equal(Number(await orderNumber.innerText()), originalOrder);
        assert(await save.isDisabled());
        assert(await cancel.isHidden());
        await unchangedScroll(initialScroll, 'Order Cancel');

        // One row draft combines the inline fields, aliases and lightbox image.
        await name.fill('Roma tomato');
        await waitEnabled(save);
        await orderHandle.press('ArrowDown');
        const draftScroll = await scroll();
        await sectionTrigger.click();
        const dairy = page.locator('.recipe-edit-store-section-menu [role="option"][data-store-section-value="DAIRY & EGGS"]');
        await dairy.click();
        assert.equal(await section.inputValue(), 'DAIRY & EGGS');
        await noExpansion();
        await aliasTrigger.click();
        await aliases.waitFor({state: 'visible'});
        await aliasInput.fill('temporary tomato');
        await aliasInput.press('Enter');
        await aliases.getByRole('button', {name: 'Remove alias temporary tomato', exact: true}).click();
        await aliasInput.fill('salad tomato');
        await aliasInput.press(',');
        await aliasInput.fill('plum tomato');
        await capture('aliases');
        await aliasInput.press('Escape');
        assert(await aliases.isHidden());
        assert(await focused(aliasTrigger), 'Escape closes aliases and restores + focus');
        await unchangedScroll(draftScroll, 'Inline fields and aliases');
        await noExpansion();
        if (options.viewport.width >= 1000) {
            const previousId = await row.evaluate(element => element.previousElementSibling.dataset.masterRecordId);
            const otherName = page.locator(`[data-ingredient-master-row][data-master-record-id="${previousId}"] [data-ingredient-row-name]`);
            const otherOriginalName = await otherName.inputValue();
            page.once('dialog', dialog => dialog.dismiss());
            await otherName.click();
            assert(await focused(name), 'Declining a row switch restores the active name input');
            assert.equal(await otherName.inputValue(), otherOriginalName);
            assert.equal(await name.inputValue(), 'Roma tomato');
            assert(await cancel.isVisible());
            await unchangedScroll(draftScroll, 'Declined switch to another row');
        }
        assert(await mergeButton.isDisabled(), 'Merge cannot discard the current draft');
        assert.equal(await name.inputValue(), 'Roma tomato');
        assert.equal(await section.inputValue(), 'DAIRY & EGGS');
        assert(await cancel.isVisible());
        assert(await save.isEnabled());
        assert.equal(await row.locator('[data-ingredient-row-image]').count(), 0);
        await row.locator('.master-data-thumbnail').click();
        await lightbox.waitFor({state: 'visible'});
        const generate = lightbox.getByRole('button', {name: 'Generate Image', exact: true});
        await waitEnabled(generate);
        await generate.click();
        await waitEnabled(save);
        const savedImage = await lightbox.locator('#recipeImageLightboxImage').getAttribute('src');
        await imageClose.press('Escape');
        assert(await lightbox.isHidden());
        await unchangedScroll(draftScroll, 'Image management');
        const before = await persisted();
        assert.equal(before.name, 'Tomato');
        assert.equal(before.store_section, 'PRODUCE');
        assert.notEqual(before.image_url, savedImage);
        assert(!before.aliases.includes('salad tomato'));
        assert.equal(saves.length, 0, 'No field or image action saves implicitly');
        await capture('pending');
        await save.click();
        await page.waitForFunction(id => {
            const row = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
            return row?.dataset.recordName === 'Roma tomato' && !row.classList.contains('is-saving')
                && row.querySelector('[data-ingredient-row-save]').disabled && row.querySelector('[data-ingredient-row-cancel]').hidden;
        }, options.recordId);
        await unchangedScroll(draftScroll, 'Joint Save');
        assert(await cancel.isHidden());
        assert.equal(saves.length, 1);
        assert.equal(saves[0].name, 'Roma tomato');
        assert.equal(saves[0].store_section, 'DAIRY & EGGS');
        assert.deepEqual(saves[0].aliases.sort(), ['plum tomato', 'salad tomato']);
        assert.equal(saves[0].image.action, 'replace');
        assert.equal(saves[0].order.position, originalOrder + 1);
        assert(saves[0].order.expected_ids.includes(options.recordId));
        assert.equal(orderWrites.length, 0);
        await noExpansion();

        // Section keyboard controls, aliases and image removal all roll back.
        await row.evaluate(element => element.scrollIntoView({block: 'center'}));
        const savedScroll = await scroll();
        await capture('saved-before-keyboard');
        await sectionTrigger.focus();
        await unchangedScroll(savedScroll, 'Focusing section for keyboard editing');
        await sectionTrigger.press('Enter');
        await capture('section-keyboard');
        await unchangedScroll(savedScroll, 'Opening section with keyboard');
        await page.locator('.recipe-edit-store-section-menu [role="option"][data-store-section-value="PRODUCE"]').press('Enter');
        assert.equal(await section.inputValue(), 'PRODUCE');
        await unchangedScroll(savedScroll, 'Section keyboard editing');
        await aliasTrigger.click();
        await aliases.getByRole('button', {name: 'Remove alias salad tomato', exact: true}).click();
        await aliasInput.press('Escape');
        await unchangedScroll(savedScroll, 'Alias removal');
        await row.locator('.master-data-thumbnail').press('Enter');
        await lightbox.waitFor({state: 'visible'});
        page.once('dialog', dialog => dialog.accept());
        await lightbox.getByRole('button', {name: 'Remove Image', exact: true}).click();
        await imageClose.click();
        await unchangedScroll(savedScroll, 'Pending image removal');
        await cancel.click();
        assert.equal(await section.inputValue(), 'DAIRY & EGGS');
        assert(await row.locator('[data-ingredient-alias="salad tomato"]').isVisible());
        assert.equal(await row.locator('.master-data-thumbnail').getAttribute('src'), savedImage);
        assert(await save.isDisabled());
        assert(await cancel.isHidden());
        await unchangedScroll(savedScroll, 'Cancel fields, aliases and image together');

        // Recipe usage and Merge Duplicate remain available from compact UI.
        await row.locator('[data-master-usage-button]').click();
        const usage = page.locator('#masterDataUsageDialog');
        await usage.waitFor({state: 'visible'});
        await usage.locator('[data-master-usage-results] .master-data-reference-item').first().waitFor({state: 'visible'});
        assert.match(await usage.innerText(), /Ingredient Name/);
        await usage.getByRole('button', {name: 'Close', exact: true}).click();
        await unchangedScroll(savedScroll, 'Recipe usage');
        const mergePreview = await page.request.get(`${base}/api/master-data/ingredients/${options.recordId}/merge-options?search=Carrot`)
            .then(response => response.json());
        const target = mergePreview.ingredients.find(candidate => candidate.name === 'Carrot');
        assert(target, 'Existing target selector includes the canonical Carrot record');
        const affectedLabel = `${mergePreview.source.reference_count} recipe reference${mergePreview.source.reference_count === 1 ? '' : 's'} affected`;
        await mergeButton.click();
        const merge = page.locator('#masterDataIngredientMergeDialog');
        await merge.waitFor({state: 'visible'});
        await merge.locator('[data-master-merge-search]').fill('Carrot');
        await merge.getByRole('option').filter({hasText: 'Carrot'}).click();
        assert(await merge.locator('[data-master-merge-submit]').isEnabled());
        assert.match(await merge.locator('[data-master-merge-target-name]').innerText(), /Carrot/);
        assert.equal(await merge.locator('[data-master-merge-target-id]').inputValue(), String(target.ingredient_id));
        assert.equal(await merge.locator('[data-master-merge-source-usage]').innerText(), affectedLabel);
        assert((await merge.locator('[data-master-merge-combined-usage]').innerText()).includes(affectedLabel));
        assert.match(await merge.locator('[data-master-merge-combined-usage]').innerText(), /selected canonical ingredient will be kept/);
        await capture('merge');
        await merge.getByRole('button', {name: 'Cancel', exact: true}).click();
        assert(await focused(mergeButton), 'Merge returns focus to its Action-column button');
        await unchangedScroll(savedScroll, 'Merge Duplicate dialog');
        await noExpansion();
        await capture('saved');
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({saveRequests: saves.length, savedImage}));
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


_BROWSER_SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = process.argv[2];
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: 1280, height: 900}});
        await context.addCookies([options.cookie]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const pageErrors = [], consoleErrors = [], saveRequests = [], emptySaveRequests = [];
        const expectedResourceErrors = new Set();
        page.on('pageerror', error => pageErrors.push(error.message));
        page.on('console', message => {
            if (['warning', 'error'].includes(message.type())) consoleErrors.push({text: message.text(), url: message.location().url});
        });
        page.on('request', request => {
            if (request.method() === 'POST' && new URL(request.url()).pathname === `/admin/master-data/ingredients/${options.recordId}`)
                saveRequests.push(request.postDataJSON());
            if (request.method() === 'POST' && new URL(request.url()).pathname === `/admin/master-data/ingredients/${options.emptyRecordId}`)
                emptySaveRequests.push(request.postDataJSON());
        });
        // The seeded image URL is a fixture reference, so serve its pixels locally.
        await page.route('**/static/generated/tomato.png', route => route.fulfill({contentType: 'image/png', body: Buffer.from(options.image, 'base64')}));
        // Serve the real upload/generation output from pytest's isolated folder.
        await page.route('**/static/generated/recipe_steps/master_ingredient_*.png', route => route.fulfill({
            contentType: 'image/png',
            path: require('node:path').join(options.imageFolder, require('node:path').basename(new URL(route.request().url()).pathname)),
        }));
        await page.goto(`${base}/admin/master-data/ingredients?search=Tomato`);
        assert.equal(await page.title(), 'Ingredient');
        const row = page.locator(`[data-ingredient-master-row][data-master-record-id="${options.recordId}"]`);
        const thumbnail = row.locator('.master-data-thumbnail');
        const save = row.locator('[data-ingredient-row-save]');
        const box = page.locator('#recipeImageLightbox');
        const preview = box.locator('#recipeImageLightboxImage');
        const close = box.getByRole('button', {name: 'Close', exact: true});
        const replace = box.getByRole('button', {name: 'Replace Image', exact: true});
        const generate = box.getByRole('button', {name: 'Generate Image', exact: true});
        const remove = box.getByRole('button', {name: 'Remove Image', exact: true});
        const savedUrl = (id = options.recordId) => page.request.get(`${base}/api/master-data/ingredients/${id}/editor`).then(response => response.json()).then(data => data.record.image_url);
        const originalImage = await savedUrl();
        const focused = locator => locator.evaluate(element => document.activeElement === element);
        const waitEnabled = async locator => {
            const deadline = Date.now() + 10000;
            while (await locator.isDisabled()) {
                assert(Date.now() < deadline, 'Image action or row Save did not become enabled');
                await new Promise(resolve => setTimeout(resolve, 10));
            }
        };
        const cancel = async (targetRow = row, targetSave = save) => {
            const action = targetRow.locator('[data-ingredient-row-cancel]');
            assert(await action.isVisible(), 'Active edits expose Cancel beside Save');
            assert.equal(await action.evaluate(element => element.closest('[popover]')), null);
            await action.click();
            assert(await targetSave.isDisabled());
            assert(await action.isHidden());
        };
        const capture = async name => {
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `${name}.png`)});
        };
        const upload = async (name, buffer, expectedStatus = 200, waitForPixels = true, target = {id: options.recordId, save}) => {
            await waitEnabled(replace);
            const response = page.waitForResponse(response => response.request().method() === 'POST'
                && new URL(response.url()).pathname === `/api/master-data/ingredients/${target.id}/image-preview`);
            const chooser = page.waitForEvent('filechooser');
            await replace.click();
            await (await chooser).setFiles({name, mimeType: 'image/png', buffer});
            const result = await response;
            assert.equal(result.status(), expectedStatus);
            await waitEnabled(replace);
            if (expectedStatus === 200) {
                const data = await result.json();
                await page.waitForFunction(({src, waitForPixels}) => {
                    const image = document.querySelector('#recipeImageLightboxImage');
                    return image?.getAttribute('src') === src && (!waitForPixels || (image.complete && image.naturalWidth > 0));
                }, {src: data.image_url, waitForPixels});
                await waitEnabled(target.save);
                return data.image_url;
            }
        };
        const checkImageLayout = async (size, viewport, label) => {
            const frame = await box.locator('.recipe-image-lightbox-media').boundingBox();
            const image = await preview.isVisible() ? await preview.evaluate(image => {
                const rect = image.getBoundingClientRect(), style = getComputedStyle(image);
                const left = parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
                const right = parseFloat(style.borderRightWidth) + parseFloat(style.paddingRight);
                const top = parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop);
                const bottom = parseFloat(style.borderBottomWidth) + parseFloat(style.paddingBottom);
                return {x: rect.x + left, y: rect.y + top, width: rect.width - left - right, height: rect.height - top - bottom};
            }) : frame;
            const toolbar = await box.locator('[data-master-image-actions]').boundingBox();
            const within = (inner, outer, message) => {
                assert(inner && outer && inner.width > 0 && inner.height > 0, `${label}: ${message} is visible`);
                assert(inner.x >= outer.x - 1 && inner.y >= outer.y - 1
                    && inner.x + inner.width <= outer.x + outer.width + 1
                    && inner.y + inner.height <= outer.y + outer.height + 1,
                    `${label}: ${message} (${JSON.stringify(inner)}) stays inside ${JSON.stringify(outer)}`);
            };
            if (size) {
                const dimensions = await preview.evaluate(image => ({width: image.naturalWidth, height: image.naturalHeight}));
                assert.equal(dimensions.width / dimensions.height, size.width / size.height, `${label}: server preserves uploaded ratio`);
                // A thin image border can leave up to two pixels of letterboxing.
                assert(Math.abs(image.height - image.width * size.height / size.width) <= 2,
                    `${label}: displayed image keeps its ${size.width}:${size.height} aspect ratio (${JSON.stringify(image)})`);
            }
            within(frame, {x: 0, y: 0, ...viewport}, 'Image frame fits viewport');
            within(image, frame, 'Image fits frame');
            within(toolbar, image, 'Toolbar stays on image');
            assert(toolbar.height <= image.height / 2 + 1, `${label}: toolbar leaves at least half the image visible (${toolbar.height}/${image.height})`);
            for (const action of [replace, generate, remove]) {
                const bounds = await action.boundingBox();
                within(bounds, image, `${await action.innerText()} button stays on image`);
                within(bounds, toolbar, `${await action.innerText()} button stays in toolbar`);
            }
            within(await close.boundingBox(), {x: 0, y: 0, ...viewport}, 'Close is visible within viewport');
        };

        await thumbnail.click();
        await box.waitFor({state: 'visible'});
        await waitEnabled(generate);
        assert(await focused(close));
        assert.equal(await preview.getAttribute('src'), originalImage);
        assert.equal(await page.locator('[data-ingredient-editor-form]').count(), 0);
        assert(await save.isDisabled());
        await capture('ingredient-lightbox-desktop');
        await close.press('Shift+Tab');
        assert(await focused(remove), 'Shift+Tab wraps to the final image action');
        await remove.press('Tab');
        assert(await focused(close), 'Tab wraps back to Close');
        page.once('dialog', dialog => dialog.dismiss());
        await remove.click();
        assert.equal(await preview.getAttribute('src'), originalImage);
        assert(await save.isDisabled());
        page.once('dialog', dialog => dialog.accept());
        await remove.click();
        assert(await preview.isHidden());
        assert(await box.getByText('No image', {exact: true}).isVisible());
        await waitEnabled(save);
        assert.equal(await savedUrl(), originalImage, 'Removal remains pending');
        await close.click();
        assert(await focused(thumbnail), 'Close returns focus to the thumbnail');
        await thumbnail.click();
        assert(await box.getByText('No image', {exact: true}).isVisible(), 'Reopening uses the pending removal');
        await close.press('Escape');
        assert(await box.isHidden());
        assert(await focused(thumbnail), 'Escape returns focus to the thumbnail');
        await cancel();
        assert.equal(await savedUrl(), originalImage);

        // An invalid real upload reports the server error and permits a retry.
        await thumbnail.click();
        expectedResourceErrors.add(`${base}/api/master-data/ingredients/${options.recordId}/image-preview`);
        await upload('invalid.png', Buffer.from('not an image'), 400);
        await box.locator('[data-master-image-status]').filter({hasText: /valid.*image/i}).waitFor({state: 'visible'});
        assert.equal(await preview.getAttribute('src'), originalImage);
        assert.equal(await savedUrl(), originalImage);
        assert(await save.isDisabled());
        await upload('retry.png', Buffer.from(options.image, 'base64'));
        assert(await box.locator('[data-master-image-status]').filter({hasText: /valid.*image/i}).isHidden());
        assert.equal(await savedUrl(), originalImage, 'A successful retry is still only a draft');
        await close.click();
        await cancel();
        assert.equal(await savedUrl(), originalImage);

        // Missing preview pixels preserve a usable frame and allow Replace recovery.
        const unavailableImage = route => route.fulfill({status: 404, body: 'Image unavailable'});
        await page.route('**/static/generated/recipe_steps/master_ingredient_*.png', unavailableImage);
        await thumbnail.click();
        const unavailableUrl = await upload('unavailable.png', Buffer.from(options.image, 'base64'), 200, false);
        expectedResourceErrors.add(`${base}${unavailableUrl}`);
        await box.getByText('Image unavailable', {exact: true}).waitFor({state: 'visible'});
        assert(await preview.isHidden());
        await checkImageLayout(null, {width: 1280, height: 900}, 'Unavailable image');
        for (const action of [replace, generate, remove]) assert(await action.isEnabled());
        assert.equal(await savedUrl(), originalImage);
        await capture('ingredient-lightbox-unavailable');
        await page.unroute('**/static/generated/recipe_steps/master_ingredient_*.png', unavailableImage);
        await upload('recovered.png', Buffer.from(options.image, 'base64'));
        assert(await box.getByText('Image unavailable', {exact: true}).isHidden());
        assert(await preview.isVisible());
        await close.click();
        await cancel();
        assert.equal(await savedUrl(), originalImage);

        await thumbnail.click();
        await waitEnabled(replace);
        const chooser = page.waitForEvent('filechooser');
        await replace.click();
        await (await chooser).setFiles({name: 'replacement.png', mimeType: 'image/png', buffer: Buffer.from(options.image, 'base64')});
        await waitEnabled(save);
        const replacementImage = await preview.getAttribute('src');
        assert.notEqual(replacementImage, originalImage);
        assert(await focused(replace));
        assert.equal(await savedUrl(), originalImage, 'Upload preview never persists by itself');
        await close.click();
        await thumbnail.click();
        assert.equal(await preview.getAttribute('src'), replacementImage);
        await close.click();
        await cancel();
        assert.equal(await savedUrl(), originalImage);

        // A late successful preview must not reapply an image after row Cancel.
        let releasePreview, previewStarted, previewFinished;
        const started = new Promise(resolve => { previewStarted = resolve; });
        const responseGate = new Promise(resolve => { releasePreview = resolve; });
        const finished = new Promise(resolve => { previewFinished = resolve; });
        const delayedPreview = async route => {
            previewStarted();
            await responseGate;
            await route.fulfill({json: {ok: true, token: 'obsolete', image_url: '/static/generated/obsolete.png'}});
            previewFinished();
        };
        await page.route(`**/api/master-data/ingredients/${options.recordId}/image-preview`, delayedPreview);
        await thumbnail.click();
        await waitEnabled(generate);
        await generate.click();
        await started;
        await close.click();
        // No preview has arrived, so Escape on the active row cancels its pending work.
        await thumbnail.press('Escape');
        releasePreview();
        await finished;
        await page.unroute(`**/api/master-data/ingredients/${options.recordId}/image-preview`, delayedPreview);
        assert(await save.isDisabled());
        assert.equal(await savedUrl(), originalImage);
        assert(await box.isHidden());

        await thumbnail.click();
        await waitEnabled(generate);
        await generate.click();
        await waitEnabled(save);
        const generatedImage = await preview.getAttribute('src');
        assert.notEqual(generatedImage, originalImage);
        assert(await focused(generate));
        assert.equal(await savedUrl(), originalImage, 'Generation remains pending until row Save');
        assert.equal(saveRequests.length, 0);
        await box.click({position: {x: 1, y: 1}});
        assert(await box.isHidden());
        assert(await focused(thumbnail), 'Backdrop returns focus to the thumbnail');
        await save.click();
        await page.waitForFunction(({id, src}) => {
            const row = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
            return row?.querySelector('.master-data-thumbnail')?.getAttribute('src') === src && row.querySelector('[data-ingredient-row-save]').disabled;
        }, {id: options.recordId, src: generatedImage});
        assert.equal(await savedUrl(), generatedImage);
        assert.equal(saveRequests.length, 1);
        assert.equal(saveRequests[0].image.action, 'replace');
        assert.equal(saveRequests[0].image_url, undefined);

        // Real uploads exercise wide, panoramic, and portrait image geometry,
        // including the smaller phone and its landscape orientation.
        for (const viewport of [{width: 390, height: 844}, {width: 320, height: 568}, {width: 844, height: 390}]) {
            await page.setViewportSize(viewport);
            const toggle = row.locator('[data-ingredient-mobile-toggle]');
            if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
            for (const shape of options.responsiveImages) {
                const label = `${viewport.width}x${viewport.height}-${shape.label}`;
                await thumbnail.click();
                await upload(`${shape.label}.png`, Buffer.from(shape.image, 'base64'));
                await capture(`ingredient-lightbox-${label}`);
                await checkImageLayout(shape, viewport, label);
                assert.equal(await savedUrl(), generatedImage, `${label}: replacement remains pending`);
                if (viewport.width === 320 && shape.label === 'panorama') {
                    page.once('dialog', dialog => dialog.accept());
                    await remove.click();
                    await box.getByText('No image', {exact: true}).waitFor({state: 'visible'});
                    assert(await preview.isHidden());
                    await checkImageLayout(null, viewport, `${label}-removed`);
                    await capture(`ingredient-lightbox-${label}-removed`);
                    assert.equal(await savedUrl(), generatedImage, 'Removing a panoramic preview remains pending');
                }
                await close.press('Escape');
                assert(await focused(thumbnail));
                await cancel();
                assert.equal(await savedUrl(), generatedImage, `${label}: cancellation preserves saved image`);
                assert.equal(await thumbnail.getAttribute('src'), generatedImage, `${label}: cancellation restores thumbnail`);
                assert.equal(saveRequests.length, 1, `${label}: no implicit saves`);
            }
        }

        // An ingredient that has never had an image uses the same management
        // lightbox, including keyboard activation and Save-only persistence.
        await page.setViewportSize({width: 1280, height: 900});
        await page.goto(`${base}/admin/master-data/ingredients?search=Carrot`);
        const emptyRow = page.locator(`[data-ingredient-master-row][data-master-record-id="${options.emptyRecordId}"]`);
        const emptyTrigger = emptyRow.locator('[data-master-image-empty]');
        const emptySave = emptyRow.locator('[data-ingredient-row-save]');
        const emptyTarget = {id: options.emptyRecordId, save: emptySave};
        const emptySavedUrl = () => savedUrl(options.emptyRecordId);
        assert.equal(await emptySavedUrl(), '');
        assert.equal(await emptyTrigger.evaluate(element => element.tagName), 'BUTTON');
        assert.match(await emptyTrigger.getAttribute('aria-label'), /Carrot/i);
        assert(await emptySave.isDisabled());
        await emptyTrigger.click();
        await box.waitFor({state: 'visible'});
        await waitEnabled(generate);
        assert(await focused(close));
        assert(await preview.isHidden());
        assert(await box.getByText('No image', {exact: true}).isVisible());
        assert(await replace.isEnabled());
        assert(await remove.isDisabled());
        assert(await emptySave.isDisabled(), 'Opening an initially empty image does not create a draft');
        await checkImageLayout(null, {width: 1280, height: 900}, 'Initially empty image');
        await capture('ingredient-lightbox-initially-empty-desktop');
        await close.press('Shift+Tab');
        assert(await focused(generate), 'Focus skips disabled Remove and wraps to Generate');
        await generate.press('Tab');
        assert(await focused(close));
        await close.click();
        assert(await focused(emptyTrigger), 'Close restores focus to No image');
        await emptyTrigger.press('Enter');
        await box.waitFor({state: 'visible'});
        await close.press('Escape');
        assert(await box.isHidden());
        assert(await focused(emptyTrigger), 'Escape restores focus to No image');
        await emptyTrigger.press('Space');
        await box.waitFor({state: 'visible'});
        await box.click({position: {x: 1, y: 1}});
        assert(await box.isHidden());
        assert(await focused(emptyTrigger), 'Backdrop restores focus to No image');
        assert(await emptySave.isDisabled());

        await emptyTrigger.click();
        await waitEnabled(generate);
        await generate.click();
        await waitEnabled(emptySave);
        const emptyGeneratedImage = await preview.getAttribute('src');
        assert(emptyGeneratedImage, 'Generate previews an image for an initially empty ingredient');
        assert(await remove.isEnabled());
        assert.equal(await emptySavedUrl(), '', 'Generation from No image remains pending');
        await close.click();
        assert(await focused(emptyTrigger));
        assert.equal(await emptySavedUrl(), '', 'Closing the generated preview never saves');
        await emptyTrigger.click();
        assert.equal(await preview.getAttribute('src'), emptyGeneratedImage);
        await close.click();
        await cancel(emptyRow, emptySave);
        assert.equal(await emptySavedUrl(), '');
        assert(await emptyTrigger.isVisible());

        await emptyTrigger.click();
        assert(await box.getByText('No image', {exact: true}).isVisible(), 'Cancel restores the initial empty preview');
        const emptyReplacement = await upload('carrot-replacement.png', Buffer.from(options.image, 'base64'), 200, true, emptyTarget);
        assert.equal(await emptySavedUrl(), '', 'Replacing No image remains pending');
        await close.click();
        assert.equal(await emptySavedUrl(), '', 'Closing the replacement preview never saves');
        await emptyTrigger.click();
        assert.equal(await preview.getAttribute('src'), emptyReplacement);
        await close.click();
        await cancel(emptyRow, emptySave);
        assert.equal(await emptySavedUrl(), '');
        assert.equal(emptySaveRequests.length, 0, 'Neither preview nor Cancel implicitly saves an empty ingredient');

        await page.setViewportSize({width: 320, height: 568});
        await emptyTrigger.click();
        await box.getByText('No image', {exact: true}).waitFor({state: 'visible'});
        await checkImageLayout(null, {width: 320, height: 568}, 'Initially empty phone image');
        await capture('ingredient-lightbox-initially-empty-phone');
        await close.click();
        await page.setViewportSize({width: 1280, height: 900});

        await emptyTrigger.click();
        const firstSavedImage = await upload('carrot-save.png', Buffer.from(options.image, 'base64'), 200, true, emptyTarget);
        await close.click();
        await emptySave.click();
        await page.waitForFunction(({id, src}) => {
            const row = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
            return row?.querySelector('.master-data-thumbnail')?.getAttribute('src') === src && row.querySelector('[data-ingredient-row-save]').disabled;
        }, {id: options.emptyRecordId, src: firstSavedImage});
        assert.equal(await emptySavedUrl(), firstSavedImage, 'Row Save persists the first image');
        assert.equal(await emptyTrigger.count(), 0);
        const newlySavedThumbnail = emptyRow.locator('.master-data-thumbnail');
        await newlySavedThumbnail.click();
        await waitEnabled(remove);
        page.once('dialog', dialog => dialog.dismiss());
        await remove.click();
        assert(await emptySave.isDisabled(), 'Dismissed removal confirmation leaves the new image unchanged');
        page.once('dialog', dialog => dialog.accept());
        await remove.click();
        await box.getByText('No image', {exact: true}).waitFor({state: 'visible'});
        await waitEnabled(emptySave);
        assert.equal(await emptySavedUrl(), firstSavedImage, 'Removal of the first image remains pending');
        await close.click();
        assert(await focused(newlySavedThumbnail));
        await emptySave.click();
        await page.waitForFunction(id => {
            const row = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${id}"]`);
            return row?.querySelector('button[data-master-image-empty]') && row.querySelector('[data-ingredient-row-save]').disabled;
        }, options.emptyRecordId);
        assert.equal(await emptySavedUrl(), '');
        await emptyTrigger.click();
        await box.getByText('No image', {exact: true}).waitFor({state: 'visible'});
        await waitEnabled(generate);
        assert(await replace.isEnabled());
        assert(await remove.isDisabled());
        assert(await emptySave.isDisabled());
        await close.click();
        assert(await focused(emptyTrigger), 'Saved removal restores an actionable No image button');
        assert.equal(emptySaveRequests.length, 2);
        assert.equal(emptySaveRequests[0].image.action, 'replace');
        assert.equal(emptySaveRequests[1].image.action, 'remove');
        assert.equal(saveRequests.length, 1);
        assert.deepEqual(pageErrors, []);
        assert.deepEqual(consoleErrors.filter(message => !(expectedResourceErrors.has(message.url)
            && /Failed to load resource.*\b(?:400|404)\b/.test(message.text))), []);
        console.log(JSON.stringify({saveRequests: saveRequests.length, savedImage: generatedImage, emptySaveRequests: emptySaveRequests.length}));
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
