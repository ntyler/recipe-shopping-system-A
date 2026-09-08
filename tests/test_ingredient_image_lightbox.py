"""Real-browser regression coverage for the Ingredient image draft workflow."""
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
    with editor_app.test_client() as client:
        sign_in(client, "user-a")
        cookie = client.get_cookie(editor_app.config["SESSION_COOKIE_NAME"])
        options = {
            "cookie": {"name": cookie.key, "value": cookie.value, "domain": "127.0.0.1", "path": "/"},
            "recordId": original["id"],
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
        const pageErrors = [], consoleErrors = [], saveRequests = [];
        const expectedResourceErrors = new Set();
        page.on('pageerror', error => pageErrors.push(error.message));
        page.on('console', message => {
            if (['warning', 'error'].includes(message.type())) consoleErrors.push({text: message.text(), url: message.location().url});
        });
        page.on('request', request => {
            if (request.method() === 'POST' && new URL(request.url()).pathname === `/admin/master-data/ingredients/${options.recordId}`)
                saveRequests.push(request.postDataJSON());
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
        const capture = async name => {
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `${name}.png`)});
        };
        const upload = async (name, buffer, expectedStatus = 200, waitForPixels = true) => {
            await waitEnabled(replace);
            const response = page.waitForResponse(response => response.request().method() === 'POST'
                && new URL(response.url()).pathname === `/api/master-data/ingredients/${options.recordId}/image-preview`);
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
                await waitEnabled(save);
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
        assert(await page.locator('[data-ingredient-editor-form]').isHidden());
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
        assert.deepEqual(pageErrors, []);
        assert.deepEqual(consoleErrors.filter(message => !(expectedResourceErrors.has(message.url)
            && /Failed to load resource.*\b(?:400|404)\b/.test(message.text))), []);
        console.log(JSON.stringify({saveRequests: saveRequests.length, savedImage: generatedImage}));
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
