"""Equipment thumbnails share the lightbox while image drafts save with the row."""
import base64
from io import BytesIO
import os
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from PushShoppingList.services import recipe_master_data_service as md
from PushShoppingList.services import recipe_master_image_service as images
from test_equipment_registry_editing import equipment
from test_ingredient_inline_editor import image_file
from test_ingredient_image_lightbox import run_browser
from test_recipe_master_data_routes import sign_in


@pytest.fixture
def image_equipment(equipment, monkeypatch, tmp_path):
    app, database, ids = equipment
    monkeypatch.setattr(images, 'STEP_IMAGE_FOLDER', tmp_path / 'images')
    monkeypatch.setattr(images, 'ensure_webp_variants', lambda *args, **kwargs: None)
    monkeypatch.setattr(images, 'request_master_image_bytes', lambda *args, **kwargs: image_file().getvalue())
    with md.recipe_master_connection() as connection:
        connection.execute("UPDATE equipment SET image_url = '/static/test-pot.png' WHERE id = ?", (ids['Pan'],))
    return app, database, ids


def test_preview_and_save_are_separate_and_atomic(image_equipment):
    app, database, ids = image_equipment
    with app.test_client() as client:
        sign_in(client, 'user-a')
        before = database.read_bytes()
        preview = client.post(f'/api/master-data/equipment/{ids["Pot"]}/image-preview', data={'image': (image_file(), 'pot.png')})
        assert preview.status_code == 200 and database.read_bytes() == before
        change = {'action': 'replace', 'token': preview.json['token']}
        rejected = client.patch(f'/api/master-data/equipment/{ids["Pot"]}', json={
            'display_name': 'Family pot', 'equipment_type': 'BAKEWARE', 'aliases': ['Pan'], 'image': change,
        })
        assert rejected.status_code == 409 and database.read_bytes() == before
        saved = client.patch(f'/api/master-data/equipment/{ids["Pot"]}', json={
            'display_name': 'Family pot', 'equipment_type': 'BAKEWARE', 'aliases': ['Soup pot'], 'image': change,
        })
        record = saved.json['record']
        assert saved.status_code == 200 and record['changed']
        assert record['name'] == 'Family pot' and record['detected_name'] == 'Pot'
        assert record['equipment_type'] == 'BAKEWARE' and record['aliases'] == ['Soup pot']
        assert record['image_url'] == preview.json['image_url'] and Path(record['image_path']).is_file()
        removed = client.patch(f'/api/master-data/equipment/{ids["Pot"]}', json={'image': {'action': 'remove'}})
        assert removed.status_code == 200
        assert removed.json['record']['image_url'] == removed.json['record']['image_path'] == ''


def test_image_tokens_are_bound_to_record_owner_and_record_type(image_equipment):
    app, database, ids = image_equipment
    with md.recipe_master_connection() as connection:
        ingredient = md.upsert_master_record(connection, 'ingredients', 'user-a', 'Carrot', store_section='PRODUCE')
    with app.test_client() as client:
        sign_in(client, 'user-a')
        preview = client.post(f'/api/master-data/equipment/{ids["Pot"]}/image-preview', data={'image': (image_file(), 'pot.png')}).json
        foreign_type = client.post(f'/api/master-data/ingredients/{ingredient["id"]}/image-preview', data={'image': (image_file(), 'carrot.png')}).json
        before = database.read_bytes()
        for target, token in [(ids['Pan'], preview['token']), (ids['Pot'], 'forged'), (ids['Pot'], foreign_type['token'])]:
            response = client.patch(f'/api/master-data/equipment/{target}', json={'display_name': 'Should not save', 'image': {'action': 'replace', 'token': token}})
            assert response.status_code == 400 and response.json['errors']['image']
            assert database.read_bytes() == before
        sign_in(client, 'user-b')
        assert client.post(f'/api/master-data/equipment/{ids["Pot"]}/image-preview?user_id=user-a', json={'action': 'generate'}).status_code == 404
        response = client.patch(f'/api/master-data/equipment/{ids["Secret pot"]}', json={'image': {'action': 'replace', 'token': preview['token']}})
        assert response.status_code == 400 and database.read_bytes() == before


@pytest.mark.parametrize('content', [b'not an image', b'x' * (10 * 1024 * 1024 + 1)], ids=['invalid', 'oversized'])
def test_invalid_image_never_creates_a_draft_or_changes_the_record(image_equipment, content):
    app, database, ids = image_equipment
    with app.test_client() as client:
        sign_in(client, 'user-a')
        before = database.read_bytes()
        result = client.post(f'/api/master-data/equipment/{ids["Pot"]}/image-preview', data={'image': (BytesIO(content), 'bad.png')})
        assert result.status_code == 400 and 'token' not in result.json
        assert database.read_bytes() == before


def test_equipment_generation_uses_equipment_prompt_and_keeps_the_record_unchanged(image_equipment, monkeypatch):
    app, database, ids = image_equipment
    calls = []
    def generate(prompt, row, record_type):
        calls.append((prompt, row['name'], record_type))
        return image_file().getvalue()
    monkeypatch.setattr(images, 'request_master_image_bytes', generate)
    with app.test_client() as client:
        sign_in(client, 'user-a')
        before = database.read_bytes()
        result = client.post(f'/api/master-data/equipment/{ids["Pot"]}/image-preview', json={'action': 'generate', 'name': 'Spider strainer'})
        assert result.status_code == 200 and result.json['token']
        assert database.read_bytes() == before
    assert calls[0][1:] == ('Spider strainer', 'equipment') and 'Spider strainer' in calls[0][0]


def test_both_thumbnail_states_use_one_accessible_button(image_equipment):
    app, _, ids = image_equipment
    with app.test_client() as client:
        sign_in(client, 'user-a')
        page = BeautifulSoup(client.get('/admin/master-data/equipment').data, 'html.parser')
    for name in ['Pot', 'Pan']:
        row = page.select_one(f'[data-equipment-master-row][data-master-record-id="{ids[name]}"]')
        trigger, = row.select('[data-master-image-trigger]')
        assert trigger.name == 'button' and trigger['type'] == 'button'
        assert trigger['aria-label'] == f'{"Add" if name == "Pot" else "Manage"} image for {name}'
        assert trigger['aria-controls'] == 'recipeImageLightbox' and trigger['aria-haspopup'] == 'dialog'
        assert trigger.select_one('.master-data-no-image' if name == 'Pot' else 'img.master-data-thumbnail')


@pytest.mark.parametrize('width,dark', [(1440, False), (1440, True), (390, True), (320, False)])
def test_equipment_image_browser(image_equipment, width, dark):
    app, _, ids = image_equipment
    with app.test_client() as client:
        sign_in(client, 'user-a')
        cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
    options = {'cookie': {'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'},
               'emptyId': ids['Pot'], 'existingId': ids['Pan'], 'width': width, 'dark': dark,
               'image': base64.b64encode(image_file().getvalue()).decode('ascii'), 'imageFolder': str(images.STEP_IMAGE_FOLDER)}
    if artifacts := os.environ.get('AI_PANTRY_BROWSER_ARTIFACTS'):
        folder = Path(artifacts).resolve()
        repository = Path(__file__).resolve().parents[1]
        assert folder != repository and repository not in folder.parents
        folder.mkdir(parents=True, exist_ok=True)
        options['screenshots'] = str(folder)
    result = run_browser(app, SCENARIO, options)
    assert result['errors'] == [] and result['saves'] == 3
    assert md.master_record_for_id('equipment', ids['Pot'], user_id='user-a')['image_url'] == ''
    assert md.master_record_for_id('equipment', ids['Pan'], user_id='user-a')['image_url'] != '/static/test-pot.png'


SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = process.argv[2];
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: options.width, height: 900}, colorScheme: options.dark ? 'dark' : 'light'});
        await context.addCookies([options.cookie]);
        const page = await context.newPage(), errors = [], saves = [];
        page.setDefaultTimeout(10000);
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {
            if (['error', 'warning'].includes(message.type()) && !message.text().includes('400 (BAD REQUEST)')) errors.push(message.text());
        });
        page.on('request', request => {if (request.method() === 'PATCH') saves.push(request.postDataJSON());});
        await page.route('**/static/test-pot.png', route => route.fulfill({contentType: 'image/png', body: Buffer.from(options.image, 'base64')}));
        await page.route('**/static/generated/recipe_steps/master_equipment_*.png', route => route.fulfill({contentType: 'image/png',
            path: require('node:path').join(options.imageFolder, require('node:path').basename(new URL(route.request().url()).pathname))}));
        await page.goto(base + '/admin/master-data/equipment');
        assert.equal(await page.title(), 'Equipment');
        assert.match(page.url(), /\/admin\/master-data\/equipment/);
        assert(await page.getByRole('heading', {name: 'Equipment', exact: true}).isVisible());
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        const row = id => page.locator(`[data-equipment-master-row][data-master-record-id="${id}"]`);
        const trigger = id => row(id).locator('[data-master-image-trigger]');
        const save = id => row(id).locator('[data-equipment-row-save]');
        const stored = async id => (await (await page.request.get(`${base}/api/master-data/equipment/${id}/editor`)).json()).record.image_url;
        const box = page.locator('#recipeImageLightbox'), preview = box.locator('#recipeImageLightboxImage');
        const close = box.getByRole('button', {name: 'Close', exact: true});
        const upload = box.getByRole('button', {name: 'Replace Image', exact: true});
        const generate = box.getByRole('button', {name: 'Generate Image', exact: true});
        const remove = box.getByRole('button', {name: 'Remove Image', exact: true});
        const shot = async state => {
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `equipment-images-${options.width}-${options.dark ? 'dark' : 'light'}-${state}.png`)});
        };
        const focused = locator => locator.evaluate(e => document.activeElement === e);
        const layout = async () => {
            const frame = await box.locator('.recipe-image-lightbox-media').boundingBox();
            assert(frame && frame.width > 0 && frame.height > 0 && frame.x >= 0 && frame.y >= 0
                && frame.x + frame.width <= options.width + 1 && frame.y + frame.height <= 901);
            for (const button of [upload, generate, remove]) {
                const rect = await button.boundingBox();
                assert(rect.x >= frame.x - 1 && rect.y >= frame.y - 1 && rect.x + rect.width <= frame.x + frame.width + 1
                    && rect.y + rect.height <= frame.y + frame.height + 1, 'Image actions stay inside the preview canvas');
            }
        };
        const empty = async id => {
            assert(await box.getByText('No image', {exact: true}).isVisible());
            assert(await preview.isHidden() && await remove.isDisabled() && await upload.isEnabled() && await generate.isEnabled());
            assert(await save(id).isDisabled(), 'Opening or canceling is not an image change');
        };
        const prepare = async (id, action, valid = true) => {
            const response = page.waitForResponse(r => r.url().endsWith(`/equipment/${id}/image-preview`));
            if (action === 'upload') {
                const chooser = page.waitForEvent('filechooser'); await upload.click();
                await (await chooser).setFiles({name: 'image.png', mimeType: 'image/png', buffer: valid ? Buffer.from(options.image, 'base64') : Buffer.from('not an image')});
            } else await generate.click();
            const result = await response, data = await result.json();
            assert.equal(result.status(), valid ? 200 : 400);
            await page.waitForFunction(() => document.querySelector('#recipeImageLightbox [data-master-image-actions]').getAttribute('aria-busy') === 'false');
            if (!valid) {assert(await save(id).isDisabled()); return;}
            await page.waitForFunction(src => {
                const img = document.querySelector('#recipeImageLightboxImage'); return img.getAttribute('src') === src && img.complete && img.naturalWidth > 0;
            }, data.image_url);
            assert(await save(id).isEnabled() && await remove.isEnabled());
            return data.image_url;
        };
        const cancel = async id => {
            await close.click(); await row(id).locator('[data-equipment-row-cancel]').click();
            assert(await save(id).isDisabled());
            await trigger(id).click();
        };
        const persist = async (id, url) => {
            await close.click(); await save(id).click();
            await page.waitForFunction(({id, url}) => {
                const row = document.querySelector(`[data-equipment-master-row][data-master-record-id="${id}"]`);
                return row?.dataset.imageSrc === url && row.querySelector('[data-equipment-row-save]').disabled && !row.classList.contains('is-dirty');
            }, {id, url});
            assert.equal(await stored(id), url);
        };
        const id = options.emptyId;
        await shot('initial');
        assert.equal(await trigger(id).getAttribute('aria-label'), 'Add image for Pot');
        await trigger(id).locator('.master-data-no-image').click();
        await empty(id); await layout(); await shot('empty');
        await close.press('Shift+Tab'); assert(await focused(generate));
        await generate.press('Tab'); assert(await focused(close));
        await close.click(); assert(await focused(trigger(id)));
        await trigger(id).press('Enter'); await empty(id);
        await page.keyboard.press('Escape'); assert(await focused(trigger(id)));
        await trigger(id).press('Space'); await empty(id);
        await box.click({position: {x: 1, y: 1}}); assert(await focused(trigger(id)));
        await trigger(id).click();
        await prepare(id, 'upload', false); await empty(id);
        const generated = await prepare(id, 'generate'); await layout(); await shot('generated-pending');
        assert.equal(await stored(id), '');
        await close.click(); await trigger(id).click();
        assert.equal(await preview.getAttribute('src'), generated, 'Reopening retains the draft');
        await cancel(id); await empty(id); assert.equal(await stored(id), '');
        await prepare(id, 'upload'); assert.equal(await stored(id), '');
        await cancel(id); await empty(id); assert.equal(saves.length, 0);
        const uploaded = await prepare(id, 'upload'); await shot('upload-pending');
        await persist(id, uploaded);
        assert.equal(await trigger(id).getAttribute('aria-label'), 'Manage image for Pot');
        assert.equal(await trigger(id).locator('img[tabindex], img[role="button"]').count(), 0, 'One thumbnail focus target');
        await trigger(id).press('Enter');
        page.once('dialog', d => d.dismiss()); await remove.click(); assert(await save(id).isDisabled());
        page.once('dialog', d => d.accept()); await remove.click();
        assert(await save(id).isEnabled() && await remove.isDisabled());
        assert.equal(await stored(id), uploaded);
        await cancel(id); assert.equal(await preview.getAttribute('src'), uploaded);
        page.once('dialog', d => d.accept()); await remove.click(); await shot('removal-pending');
        await persist(id, ''); await trigger(id).click(); await empty(id);
        // Cancel an in-flight generation; its eventual response must never resurrect a draft.
        let release, started;
        const gate = new Promise(resolve => release = resolve), waiting = new Promise(resolve => started = resolve);
        await page.route(`**/equipment/${id}/image-preview`, async route => {const response = await route.fetch(); started(); await gate; await route.fulfill({response});});
        await generate.click(); await waiting;
        assert(await save(id).isDisabled() && await generate.isDisabled());
        await cancel(id); await empty(id);
        const late = page.waitForResponse(r => r.url().endsWith(`/equipment/${id}/image-preview`)); release(); await late;
        await page.waitForLoadState('networkidle'); await empty(id);
        await page.unroute(`**/equipment/${id}/image-preview`); await close.click();
        const existing = options.existingId;
        await trigger(existing).locator('img').click();
        assert(await preview.isVisible() && await remove.isEnabled()); await layout(); await shot('existing');
        await close.click(); await trigger(existing).press('Space');
        const replacement = await prepare(existing, 'generate');
        assert.equal(await stored(existing), '/static/test-pot.png');
        await persist(existing, replacement);
        assert.equal(saves.length, 3);
        assert.deepEqual(saves.map(s => s.image.action), ['replace', 'remove', 'replace']);
        console.log(JSON.stringify({errors, saves: saves.length}));
    } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
