const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const base = process.argv[3], cookie = JSON.parse(fs.readFileSync(0, 'utf8'));
const artifacts = process.env.AI_PANTRY_BROWSER_ARTIFACTS;

(async () => {
    // A temporary extension sets actual tab zoom, including layout viewport and DPR.
    // CSS zoom, deviceScaleFactor and pinch zoom do not exercise browser zoom reflow.
    const extension = fs.mkdtempSync(path.join(os.tmpdir(), 'units-alias-zoom-'));
    fs.writeFileSync(path.join(extension, 'manifest.json'), JSON.stringify({manifest_version:3,
        name:'Units alias zoom QA', version:'1.0', permissions:['tabs'], background:{service_worker:'zoom.js'}}));
    fs.writeFileSync(path.join(extension, 'zoom.js'), 'chrome.runtime.onInstalled.addListener(() => {});');
    const context = await chromium.launchPersistentContext('', {
        executablePath: process.env.AI_PANTRY_ZOOM_BROWSER || chromium.executablePath(), headless:true,
        viewport:{width:1920,height:1080}, colorScheme:'dark',
        args:[`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
    });
    try {
        await context.addCookies([cookie]);
        const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
        const page = await context.newPage(); page.setDefaultTimeout(10000);
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => { if (['error','warning'].includes(m.type())) errors.push(m.text()); });
        const fixtures = [
            ['zero', []], ['one', ['single spoonful']],
            ['short', ['as1','as2','as3','as4','as5','as6']],
            ['long', ['generous tablespoon measurement', 'small rounded tablespoon measure', 'level serving spoon measurement', 'large serving spoon measurement', 'small measuring spoon quantity']],
            ['unbroken', ['a'.repeat(60), 'b'.repeat(60), 'c'.repeat(60)]],
            ['many', Array.from({length:50}, (_, index) => `spoon measure variant ${index}`)],
        ];
        for (const fixture of fixtures) {
            const response = await context.request.post(base + '/api/master-data/units', {
                data:{canonical_name:`layout ${fixture[0]}`, category:'volume', aliases:fixture[1]},
            });
            assert(response.ok()); fixture.push((await response.json()).unit_id);
        }
        await page.route('**/api/master-data/units/suggest', route => route.fulfill({json:{ok:true,suggestion:{aliases:[]}}}));
        await page.goto(base + '/admin/master-data/units');
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.title(), 'Units'); assert(page.url().endsWith('/admin/master-data/units'));
        assert.equal(await page.locator('[data-unit-master-row]').count(), 35 + fixtures.length);
        assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
        const form = page.locator('[data-unit-master-form]');
        const input = form.locator('[data-unit-master-alias-input]');
        const shot = async filename => { if (artifacts) { fs.mkdirSync(artifacts, {recursive:true}); await page.screenshot({path:path.join(artifacts, filename)}); } };
        // Every row opens aliases directly from rest, without activating an edit field.
        for (const width of [1440,390]) {
            await page.setViewportSize({width,height:900});
            for (const row of await page.locator('[data-unit-master-row]').all()) {
                const manage = row.getByRole('button', {name:'Manage aliases',exact:true});
                await manage.evaluate(e => e.scrollIntoView({block:'center'}));
                await page.mouse.move(0,0);
                assert(await manage.isVisible()); assert(await manage.isEnabled());
                assert.equal(await row.locator('[data-unit-row-name]').count(),0);
                assert.equal(await row.locator('[data-unit-row-alias]').count(),1);
                await manage.click(); assert(await form.isVisible());
                assert(await form.getByRole('button', {name:'Suggest aliases',exact:true}).isVisible());
                await input.press('Escape');
                await row.locator('[data-unit-row-cancel]').click();
                assert(await manage.isVisible()); assert(await manage.isEnabled());
            }
        }
        let cases = 0;
        for (const zoom of [1, 1.25, 1.5]) {
            await worker.evaluate(async ({base,zoom}) => {
                const [tab] = await chrome.tabs.query({url:base+'/*'});
                await chrome.tabs.setZoom(tab.id, zoom);
            }, {base,zoom});
            for (const width of [1920,1440,1180,1100,900,390,320]) {
                await page.setViewportSize({width,height:1080});
                await page.waitForFunction(zoom => Math.abs(devicePixelRatio - zoom) < .01, zoom);
                assert(Math.abs(await page.evaluate(() => innerWidth) - width / zoom) <= 1);
                for (const [kind, aliases, id] of fixtures) {
                    const row = page.locator(`[data-unit-master-row][data-unit-id="${id}"]`);
                    const restingHeight = (await row.boundingBox()).height;
                    assert(await row.locator('[data-unit-row-alias="add"]').isVisible());
                    assert(await row.locator('[data-unit-row-alias="add"]').isEnabled());
                    if (!aliases.length) assert.equal(await row.locator('.unit-master-no-aliases').innerText(),'No aliases');
                    const actions = row.locator('.unit-master-alias-actions');
                    await actions.evaluate(e => e.scrollIntoView({block:'center',inline:'nearest'}));
                    await page.mouse.move(0,0); // Controls stay visible without hover, focus, or editing.
                    const metrics = await row.locator('.unit-master-aliases').evaluate(cell => {
                        const box = e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}; };
                        const group = cell.querySelector('.unit-master-alias-actions');
                        const buttons = [...group.querySelectorAll('button')];
                        return {cell:box(cell), group:box(group), opacity:getComputedStyle(group).opacity,
                            shrink:getComputedStyle(group).flexShrink, children:[...cell.children].map(e=>e.className),
                            chips:[...cell.querySelectorAll('code')].map(box),
                            buttons:buttons.map(button => {
                                const r=button.getBoundingClientRect(), style=getComputedStyle(button);
                                const range=document.createRange(); range.selectNodeContents(button); const glyph=range.getBoundingClientRect();
                                return {...box(button),minWidth:style.minWidth,minHeight:style.minHeight,
                                    label:button.getAttribute('aria-label'),title:button.title,
                                    centered:Math.abs((glyph.left+glyph.right-r.left-r.right)/2)<1,
                                    hit:[[2,2],[r.width-2,2],[2,r.height-2],[r.width-2,r.height-2],[r.width/2,r.height/2]]
                                        .every(([x,y])=>button.contains(document.elementFromPoint(r.left+x,r.top+y)))};
                            }), viewport:innerWidth};
                    });
                    const detail = JSON.stringify({zoom,width,kind,...metrics});
                    assert.equal(metrics.opacity,'1',detail); assert.equal(metrics.shrink,'0',detail);
                    assert.deepEqual(metrics.children,['unit-master-alias-chip-list','unit-master-alias-actions']);
                    assert.equal(metrics.chips.length,aliases.length);
                    assert.equal(metrics.buttons.length,1);
                    const [add] = metrics.buttons;
                    assert.equal(add.width,add.height,detail); assert(add.width>=32,detail);
                    assert.equal(add.minWidth,add.minHeight,detail);
                    assert.equal(metrics.group.width,add.width,detail);
                    assert.equal(add.label,'Manage aliases');
                    assert(metrics.group.x>=metrics.cell.x-.5 && metrics.group.right<=metrics.cell.right+.5,detail);
                    assert(metrics.group.bottom<=metrics.cell.bottom+.5,detail);
                    for (const button of metrics.buttons) {
                        assert(button.hit && button.centered,detail);
                        assert(button.x>=0 && button.right<=metrics.viewport,detail);
                        assert.equal(button.label,button.title);
                        for (const chip of metrics.chips) {
                            assert(chip.right<=button.x-5.5 || chip.bottom<=button.y-5.5 || chip.y>=button.bottom+5.5,detail);
                        }
                    }
                    const lastChip = metrics.chips.at(-1);
                    if (lastChip && metrics.cell.right - lastChip.right >= add.width + 6) {
                        assert(Math.abs(add.x - lastChip.right - 6) < 1, `Manage follows the last chip when it fits: ${detail}`);
                        assert(add.y < lastChip.bottom && add.bottom > lastChip.y, detail);
                    }
                    if (zoom===1 && [1440,390].includes(width) && ['zero','short','long'].includes(kind)) {
                        await shot(`units-alias-visible-${kind}-${width}.png`);
                    }
                    const addControl = row.locator('[data-unit-row-alias="add"]');
                    await addControl.click(); assert(await form.isVisible());
                    const panel = await form.boundingBox();
                    const viewport = await page.evaluate(() => ({width:innerWidth,height:innerHeight}));
                    assert(panel.x >= 11 && panel.y >= 11
                        && panel.x + panel.width <= viewport.width - 11
                        && panel.y + panel.height <= viewport.height - 11, detail);
                    assert(await form.evaluate(e => e.scrollWidth <= e.clientWidth + 1), `${kind} at ${width}/${zoom}: popover content fits without horizontal scrolling`);
                    if (await page.evaluate(() => innerWidth > 600)) {
                        assert(Math.abs((await row.boundingBox()).height - restingHeight) < .1);
                    } else {
                        assert(await row.locator('[data-unit-row-cancel]').isVisible());
                        assert((await row.boundingBox()).height >= restingHeight);
                    }
                    assert.match(await form.locator('[data-unit-master-editor-title]').innerText(), new RegExp(`layout ${kind}`));
                    if (kind==='zero' && zoom===1 && width===1440) {
                        await input.fill('temporary alias'); await input.press('Enter');
                        assert.equal(await row.locator('.unit-master-no-aliases').count(),0);
                        await form.getByRole('button', {name:'Remove alias temporary alias',exact:true}).click();
                        assert.equal(await row.locator('.unit-master-no-aliases').innerText(),'No aliases');
                        assert(await row.locator('[data-unit-row-save]').isDisabled());
                    }
                    await input.press('Escape'); assert(await addControl.evaluate(e=>e===document.activeElement));
                    if (kind==='long' && [1440,390].includes(width)) {
                        await shot(`units-alias-controls-${width}-${zoom*100}.png`);
                        assert.equal(await row.locator('[data-unit-row-alias="suggest"]').count(),0);
                        await addControl.click();
                        const suggest = form.getByRole('button',{name:'Suggest aliases',exact:true});
                        assert.match(await suggest.getAttribute('class'),/secondary/);
                        await suggest.click();
                        await form.getByText('No new aliases to suggest.',{exact:true}).waitFor();
                        await input.press('Escape');
                    }
                    await row.locator('[data-unit-row-cancel]').click(); cases++;
                }
            }
        }
        assert.deepEqual(errors,[]);
        console.log(`PASS ${cases} alias-layout cases at actual 100%, 125%, 150% browser zoom: zero/one/short/long/unbroken/50 aliases; desktop/narrow widths; single Manage control, stable heights, full hit testing, chip separation, popover bounds and content, Suggest, Escape/focus, console.`);
    } finally {
        await context.close();
        const resolved = fs.realpathSync(extension);
        assert.equal(path.dirname(resolved), fs.realpathSync(os.tmpdir()));
        assert(path.basename(resolved).startsWith('units-alias-zoom-'));
        fs.rmSync(resolved, {recursive:true});
    }
})().catch(error => { console.error(error); process.exitCode=1; });
