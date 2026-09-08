"""Real-browser regression coverage for the Ingredient image draft workflow."""
import base64
from io import BytesIO
import json
import os
import shutil
import subprocess
import threading

from PIL import Image
import pytest
from werkzeug.serving import make_server

from PushShoppingList.services import recipe_master_image_service as images
from test_ingredient_inline_editor import editor_app, tomato
from test_recipe_master_data_routes import sign_in


def test_ingredient_lightbox_reuses_pending_image_actions(editor_app, monkeypatch):
    node = shutil.which("node")
    module = os.environ.get("AI_PANTRY_PLAYWRIGHT_MODULE", "playwright")
    if not node or subprocess.run(
        [node, "-e", "require.resolve(process.argv[1])", module], capture_output=True
    ).returncode:
        pytest.skip("Install Playwright for Node or set AI_PANTRY_PLAYWRIGHT_MODULE")

    picture = BytesIO()
    Image.new("RGB", (800, 600), "#b95b32").save(picture, format="PNG")
    image_bytes = picture.getvalue()
    monkeypatch.setattr(images, "request_master_ingredient_image_bytes", lambda *_: image_bytes)
    original = tomato()
    with editor_app.test_client() as client:
        sign_in(client, "user-a")
        cookie = client.get_cookie(editor_app.config["SESSION_COOKIE_NAME"])
        options = {
            "cookie": {"name": cookie.key, "value": cookie.value, "domain": "127.0.0.1", "path": "/"},
            "recordId": original["id"],
            "image": base64.b64encode(image_bytes).decode("ascii"),
        }
    server = make_server("127.0.0.1", 0, editor_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [node, "-e", _BROWSER_SCENARIO, module, f"http://127.0.0.1:{server.server_port}"],
            input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        result_data = json.loads(result.stdout)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result_data["saveRequests"] == 1
    assert tomato()["image_url"] == result_data["savedImage"]
    assert tomato()["image_url"] != original["image_url"]
    assert tomato()["name"] == original["name"]
    assert tomato()["store_section"] == original["store_section"]


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
        const pageErrors = [], saveRequests = [];
        page.on('pageerror', error => pageErrors.push(error.message));
        page.on('request', request => {
            if (request.method() === 'POST' && new URL(request.url()).pathname === `/admin/master-data/ingredients/${options.recordId}`)
                saveRequests.push(request.postDataJSON());
        });
        // The seeded image URL is a fixture reference, so serve its pixels locally.
        await page.route('**/static/generated/tomato.png', route => route.fulfill({contentType: 'image/png', body: Buffer.from(options.image, 'base64')}));
        // Preview files belong to pytest's temporary folder, outside Flask static.
        await page.route('**/static/generated/recipe_steps/master_ingredient_*.png', route => route.fulfill({contentType: 'image/png', body: Buffer.from(options.image, 'base64')}));
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
        const savedUrl = () => page.request.get(`${base}/api/master-data/ingredients/${options.recordId}/editor`).then(response => response.json()).then(data => data.record.image_url);
        const originalImage = await savedUrl();
        const focused = locator => locator.evaluate(element => document.activeElement === element);
        const waitEnabled = async locator => {
            const deadline = Date.now() + 10000;
            while (await locator.isDisabled()) {
                assert(Date.now() < deadline, 'Image action or row Save did not become enabled');
                await new Promise(resolve => setTimeout(resolve, 10));
            }
        };
        const cancel = async () => {
            await row.getByRole('button', {name: /More actions/}).click();
            await row.locator('[data-ingredient-row-cancel]').click();
            assert(await save.isDisabled());
        };

        await thumbnail.click();
        await box.waitFor({state: 'visible'});
        await waitEnabled(generate);
        assert(await focused(close));
        assert.equal(await preview.getAttribute('src'), originalImage);
        assert(await page.locator('[data-ingredient-editor-form]').isHidden());
        assert(await save.isDisabled());
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

        // Narrow screens retain the overlay inside the displayed image frame.
        await page.setViewportSize({width: 390, height: 844});
        await thumbnail.click();
        await waitEnabled(generate);
        const frame = await box.locator('.recipe-image-lightbox-media').boundingBox();
        const toolbar = await box.locator('[data-master-image-actions]').boundingBox();
        assert(toolbar.x >= frame.x - 1 && toolbar.y >= frame.y - 1);
        assert(toolbar.x + toolbar.width <= frame.x + frame.width + 1);
        assert(toolbar.y + toolbar.height <= frame.y + frame.height + 1);
        assert(toolbar.height < frame.height / 2, 'Toolbar leaves most of the image visible');
        await close.press('Escape');
        assert(await focused(thumbnail));
        assert.deepEqual(pageErrors, []);
        console.log(JSON.stringify({saveRequests: saveRequests.length, savedImage: generatedImage}));
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
