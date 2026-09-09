"""Every stored Equipment Type keeps its shape and accessible accent across the registry."""
import os
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from PushShoppingList.services import recipe_master_data_service as md
from test_equipment_inline_editor import configure_master_data_app, sign_in, run_browser


def seed_types():
    with md.recipe_master_connection() as connection:
        for section in md.equipment_section_options():
            md.upsert_master_record(connection, 'equipment', 'user-a', section.title(), equipment_section=section)


def test_all_equipment_types_have_distinct_server_rendered_icons(monkeypatch, tmp_path):
    app, db, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_types()
    before = db.read_bytes()
    with app.test_client() as client:
        sign_in(client, 'user-a')
        page = BeautifulSoup(client.get('/admin/master-data/equipment').data, 'html.parser')
    assert db.read_bytes() == before
    rows = page.select('[data-equipment-master-row]')
    assert {row['data-equipment-type'] for row in rows} == set(md.equipment_section_options())
    icons = []
    for row in rows:
        section = row['data-equipment-type']
        label = row.select_one('.equipment-type-label')
        icon = label.select_one('[data-equipment-type-icon]')
        assert label.get_text(strip=True) == section.title()
        assert icon['data-equipment-type-icon'] != 'package'
        assert icon['aria-hidden'] == 'true'
        svg = icon.select_one('svg')
        assert svg['aria-hidden'] == 'true' and svg['focusable'] == 'false'
        icons.append(svg.decode_contents().strip())
        template = page.select_one(f'template[data-equipment-type-template="{section}"]')
        heading = page.select_one(f'[data-equipment-group] > header [data-equipment-type-label="{section}"]')
        assert template.select_one('svg') == svg == heading.select_one('svg')
    assert len(set(icons)) == len(rows)
    controls = app.jinja_env.get_template('includes/master_data_controls.html').module
    unknown = BeautifulSoup(controls.equipment_type_label('NEW TYPE'), 'html.parser')
    assert unknown.select_one('[data-equipment-type-icon]')['data-equipment-type-icon'] == 'package'
    assert unknown.get_text(strip=True) == 'New Type'


@pytest.mark.parametrize('width,dark', [(1440, False), (390, False), (320, False), (1440, True), (390, True), (320, True)])
def test_all_equipment_type_icons_in_browser(monkeypatch, tmp_path, width, dark):
    app, _, _ = configure_master_data_app(monkeypatch, tmp_path)
    seed_types()
    with app.test_client() as client:
        sign_in(client, 'user-a')
        cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
        options = {'cookie': {'name': cookie.key, 'value': cookie.value, 'domain': '127.0.0.1', 'path': '/'},
                   'width': width, 'dark': dark, 'types': md.equipment_section_options()}
    if artifacts := os.environ.get('AI_PANTRY_BROWSER_ARTIFACTS'):
        folder = Path(artifacts).resolve()
        repository = Path(__file__).resolve().parents[1]
        assert folder != repository and repository not in folder.parents
        folder.mkdir(parents=True, exist_ok=True)
        options['screenshots'] = str(folder)
    result = run_browser(app, SCENARIO, options)
    assert result['errors'] == [] and result['types'] == len(options['types'])


SCENARIO = r"""
const {chromium} = require(process.argv[1]);
const assert = require('node:assert/strict');
const options = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
(async () => {
    const browser = await chromium.launch({channel: process.env.AI_PANTRY_BROWSER_CHANNEL || 'chrome', headless: true});
    try {
        const context = await browser.newContext({viewport: {width: options.width, height: options.width <= 390 ? 844 : 1000}, colorScheme: options.dark ? 'dark' : 'light'});
        await context.addCookies([options.cookie]);
        const page = await context.newPage(), errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => {if (['error', 'warning'].includes(message.type())) errors.push(message.text());});
        await page.goto(process.argv[2] + '/admin/master-data/equipment?limit=500');
        assert.equal(await page.title(), 'Equipment');
        assert.match(page.url(), /\/admin\/master-data\/equipment/);
        assert(await page.getByRole('heading', {name: 'Equipment', exact: true}).isVisible());
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        const rows = page.locator('[data-equipment-master-row]');
        assert.equal(await rows.count(), options.types.length);
        const groups = page.locator('[data-equipment-group]');
        assert.equal(await groups.count(), options.types.length);
        const groupColumns = [];
        for (const group of await groups.all()) {
            const heading = group.locator(':scope > header.equipment-group-header');
            assert.equal(await heading.count(), 1);
            assert.equal(await heading.locator('[data-equipment-group-count]').textContent(), '1 item');
            assert.equal(await group.locator('table').count(), 1);
            assert.deepEqual(await group.locator('thead th').allTextContents(), ['Order', 'Item', 'Aliases', 'Equipment Type', 'Used In', 'Action']);
            const section = await heading.locator('[data-equipment-type-label]').getAttribute('data-equipment-type-label');
            assert.equal(await group.locator('[data-equipment-master-row]').getAttribute('data-equipment-type'), section);
            if (options.width >= 1280) groupColumns.push(await group.locator('thead th').evaluateAll(es => es.map(e => e.getBoundingClientRect().width)));
        }
        assert(groupColumns.every(columns => columns.every((width, index) => Math.abs(width - groupColumns[0][index]) < 1)), 'Equipment groups share identical column widths');
        const shot = async state => {
            if (options.screenshots) await page.screenshot({path: require('node:path').join(options.screenshots, `equipment-types-${options.width}-${options.dark ? 'dark' : 'light'}-${state}.png`), fullPage: state === 'rows'});
        };
        // Composite the real ancestor backgrounds, including transparent row states.
        const accent = async label => {
            const result = await label.evaluate(e => {
                const svg = e.querySelector('svg'), text = e.querySelector('.equipment-type-text');
                const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
                const ctx = canvas.getContext('2d', {willReadFrequently: true});
                ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 1, 1);
                const ancestors = []; for (let p = svg; p; p = p.parentElement) ancestors.unshift(p);
                for (const p of ancestors) {ctx.fillStyle = getComputedStyle(p).backgroundColor; ctx.fillRect(0, 0, 1, 1);}
                const background = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
                const stroke = getComputedStyle(svg).stroke;
                ctx.fillStyle = stroke; ctx.fillRect(0, 0, 1, 1);
                const rgb = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
                const textToken = e.closest('.equipment-group-title') && matchMedia('(max-width: 600px)').matches
                    ? '--app-muted' : '--app-text-strong';
                ctx.fillStyle = getComputedStyle(e).getPropertyValue(textToken); ctx.fillRect(0, 0, 1, 1);
                const normalText = `rgb(${[...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).join(', ')})`;
                const luminance = channels => channels.map(c => {
                    c /= 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
                }).reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
                const a = luminance(rgb), b = luminance(background);
                return {stroke, rgb, contrast: (Math.max(a, b) + .05) / (Math.min(a, b) + .05),
                    text: getComputedStyle(text).color, normalText};
            });
            assert(result.contrast >= 3, `Icon contrast ${result.contrast}: ${JSON.stringify(result)}`);
            assert.equal(result.text, result.normalText, 'Type name retains the normal text color');
            assert.notEqual(result.stroke, result.text, 'Accent belongs only to the icon');
            return result.stroke;
        };
        await shot('initial');
        const styles = [], shapes = [], colors = new Map();
        for (const row of await rows.all()) {
            if (options.width <= 760) await row.locator('[data-equipment-mobile-toggle]').click();
            const trigger = row.locator('[data-equipment-type-trigger]');
            assert(await trigger.isVisible());
            await trigger.scrollIntoViewIfNeeded();
            const icon = trigger.locator('svg');
            const style = await icon.evaluate(e => {
                const css = getComputedStyle(e), rect = e.getBoundingClientRect();
                return [rect.width, rect.height, css.strokeWidth, css.fill, css.stroke, css.strokeLinecap, css.strokeLinejoin];
            });
            assert.deepEqual(style.slice(0, 4), [18, 18, '1.8px', 'none']);
            styles.push(style); shapes.push(await icon.innerHTML());
            assert.equal(await icon.getAttribute('aria-hidden'), 'true');
            assert.equal(await icon.getAttribute('focusable'), 'false');
            assert(await trigger.evaluate(e => {
                const outer = e.getBoundingClientRect(), text = e.querySelector('.equipment-type-text').getBoundingClientRect();
                return text.left >= outer.left && text.right <= outer.right + 1 && text.bottom <= outer.bottom + 1;
            }), 'Full type label fits the inline control');
            const section = await row.getAttribute('data-equipment-type');
            const label = trigger.locator('.equipment-type-label');
            await page.mouse.move(0, 0);
            const color = await accent(label); colors.set(section, color);
            await trigger.hover();
            assert.equal(await accent(label), color, `${section}: hovered row keeps its accent`);
            await trigger.click();
            assert.equal(await accent(label), color, `${section}: selected row keeps its accent`);
            assert.equal(await accent(page.locator('.equipment-type-menu [aria-selected="true"] .equipment-type-label')), color);
            await page.keyboard.press('Escape');
            assert(await trigger.evaluate(e => e.matches(':focus-visible')));
            assert.equal(await accent(label), color, `${section}: keyboard focus keeps its accent`);
        }
        assert.equal(new Set(shapes.map(s => s.trim())).size, options.types.length);
        assert.equal(new Set(colors.values()).size, options.types.length, 'Every stored type has a distinct accent');
        assert(styles.every(s => JSON.stringify(s.filter((_, i) => i !== 4)) === JSON.stringify(styles[0].filter((_, i) => i !== 4))), 'Consistent icon geometry across all rows');
        for (const label of await page.locator('[data-equipment-group] > header .equipment-type-label').all()) {
            assert.equal(await accent(label), colors.get(await label.getAttribute('data-equipment-type-label')));
        }
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No phone overflow');
        await rows.first().scrollIntoViewIfNeeded(); await shot('rows');
        const first = rows.first(), trigger = first.locator('[data-equipment-type-trigger]');
        const select = first.locator('[data-equipment-row-type]'), original = await select.inputValue();
        await trigger.click();
        const menu = page.locator('#equipmentTypeMenu');
        assert.equal(await menu.getAttribute('role'), 'listbox');
        assert.match(await menu.getAttribute('aria-label'), /Equipment Type for/);
        assert(await menu.isVisible());
        assert.equal(await menu.getByRole('option').count(), options.types.length);
        assert.deepEqual((await menu.locator('svg').evaluateAll(es => es.map(e => e.innerHTML.trim()))).sort(), shapes.map(s => s.trim()).sort());
        assert(await menu.locator('svg').evaluateAll(es => es.every(e => {
            const css = getComputedStyle(e); return css.width === '18px' && css.height === '18px' && css.strokeWidth === '1.8px' && css.fill === 'none';
        })));
        for (const option of await menu.getByRole('option').all()) {
            const label = option.locator('.equipment-type-label'), section = await label.getAttribute('data-equipment-type-label');
            assert.equal(await accent(label), colors.get(section), `${section}: dropdown matches heading and row`);
            await option.hover();
            assert.equal(await accent(label), colors.get(section), `${section}: hovered option keeps its accent`);
        }
        const rect = await menu.boundingBox();
        assert(rect.x >= 0 && rect.x + rect.width <= options.width && rect.y >= 0 && rect.y + rect.height <= (options.width <= 390 ? 844 : 1000));
        await shot('menu');
        await page.keyboard.press('End');
        assert(await menu.evaluate(e => e.matches(':focus-visible')));
        assert.equal(await accent(menu.locator('.is-active .equipment-type-label')), colors.get('MISC'));
        await shot('focused-option'); await page.keyboard.press('Enter');
        assert.equal(await select.inputValue(), 'MISC');
        assert.equal(await trigger.locator('[data-equipment-type-icon]').getAttribute('data-equipment-type-icon'), 'misc-grid');
        assert.equal(await accent(trigger.locator('.equipment-type-label')), colors.get('MISC'));
        await trigger.click();
        assert.equal(await accent(menu.locator('[aria-selected="true"] .equipment-type-label')), colors.get('MISC'));
        await shot('selected-option'); await page.keyboard.press('Escape'); await shot('focused-trigger');
        await first.locator('[data-equipment-row-cancel]').click();
        assert.equal(await select.inputValue(), original);
        assert.equal(await trigger.locator('[data-equipment-type-label]').getAttribute('data-equipment-type-label'), original);
        await trigger.click(); await page.keyboard.press('b'); await page.keyboard.press('Enter');
        assert.equal(await select.inputValue(), 'BAKEWARE');
        await trigger.click(); await page.keyboard.press('Escape');
        assert.equal(await select.inputValue(), 'BAKEWARE', 'Escape dismisses menu without canceling row draft');
        assert(await trigger.evaluate(e => document.activeElement === e));
        await first.locator('[data-equipment-row-cancel]').click();
        await trigger.click(); await page.keyboard.press('Tab');
        assert(await menu.isHidden());
        const filter = page.locator('.master-data-equipment-filter-field [data-equipment-type-trigger]');
        const fallback = await accent(filter.locator('.equipment-type-label'));
        assert(![...colors.values()].includes(fallback), 'All types uses neutral fallback');
        // Exercise a newly introduced option through the real picker without a data write.
        const filterSelect = page.locator('[name="equipment_section"]');
        await filterSelect.evaluate(e => e.add(new Option('New Type', 'NEW TYPE')));
        await filter.click(); await page.getByRole('option', {name: 'New Type', exact: true}).click();
        assert.equal(await accent(filter.locator('.equipment-type-label')), fallback);
        assert.equal(await filter.locator('[data-equipment-type-icon]').getAttribute('data-equipment-type-icon'), 'package');
        await filter.click();
        assert.equal(await accent(menu.locator('[aria-selected="true"] .equipment-type-label')), fallback);
        await page.getByRole('option', {name: 'All types', exact: true}).click();
        await filterSelect.evaluate(e => e.querySelector('option[value="NEW TYPE"]').remove());
        // Explicit appearance overrides the OS setting, including portaled menus.
        await page.evaluate(dark => window.aiPantryTheme.setPreference(dark ? 'light' : 'dark'), options.dark);
        const overrideColors = new Map();
        for (const label of await page.locator('[data-equipment-group] > header .equipment-type-label').all()) {
            const section = await label.getAttribute('data-equipment-type-label');
            overrideColors.set(section, await accent(label));
            assert.notEqual(overrideColors.get(section), colors.get(section));
        }
        await filter.click();
        for (const label of await menu.locator('.equipment-type-label').all()) {
            const section = await label.getAttribute('data-equipment-type-label');
            if (section) assert.equal(await accent(label), overrideColors.get(section));
        }
        await page.keyboard.press('Escape');
        await page.evaluate(() => window.aiPantryTheme.setPreference('system'));
        await filter.click();
        await page.getByRole('option', {name: 'Serving & Storage', exact: true}).click();
        assert.equal(await page.locator('[name="equipment_section"]').inputValue(), 'SERVING & STORAGE');
        assert.equal(await filter.locator('[data-equipment-type-icon]').getAttribute('data-equipment-type-icon'), 'storage-container');
        assert.equal(await accent(filter.locator('.equipment-type-label')), colors.get('SERVING & STORAGE'));
        await page.locator('.master-data-filter-form').getByRole('button', {name: 'Apply', exact: true}).click();
        await page.waitForFunction(() => document.querySelectorAll('[data-equipment-master-row]').length === 1);
        assert.equal(await rows.first().getAttribute('data-equipment-type'), 'SERVING & STORAGE');
        if (options.width <= 760) await rows.first().locator('[data-equipment-mobile-toggle]').click();
        await rows.first().locator('[data-equipment-type-trigger]').click();
        assert(await page.getByRole('option', {name: 'Serving & Storage', exact: true}).isVisible(), 'Picker survives AJAX filter refresh');
        assert.equal(await accent(rows.first().locator('[data-equipment-type-trigger] .equipment-type-label')), colors.get('SERVING & STORAGE'));
        assert.equal(await accent(menu.locator('[aria-selected="true"] .equipment-type-label')), colors.get('SERVING & STORAGE'));
        await page.keyboard.press('Escape');
        console.log(JSON.stringify({errors, types: options.types.length}));
    } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
