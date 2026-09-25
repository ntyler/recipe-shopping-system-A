"""Print/download UI contracts, exercised without launching a browser."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required")
def test_preview_print_options_and_direct_download_stay_in_sync():
    script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const elements = new Map(), listeners = {}, storage = new Map();
function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
        dataset:{}, hidden:false, classes:new Set(), setAttribute(){},
        toggleAttribute(name, enabled) { this[name] = Boolean(enabled); },
        classList:{toggle(){}}
    });
    return elements.get(selector);
}
const choices = [{open:false}, {open:true}];
const page = {querySelector:element, querySelectorAll:selector => selector === 'details[data-preview-choice]' ? choices : []};
let printCalls = 0, downloadClicks = 0, request, revoked;
const anchor = {click(){downloadClicks++;}};
const ctx = {
    URL:class extends URL {
        static createObjectURL(){return 'blob:recipe';}
        static revokeObjectURL(url){revoked = url;}
    },
    document:{body:{dataset:{viewerUserId:'person-a'}}, getElementById:element,
        createElement(tag){assert.equal(tag,'a');return anchor;}},
    window:{addEventListener:(name, callback)=>listeners[name]=callback,
        print(){printCalls++;listeners.beforeprint();listeners.afterprint();}},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    setTimeout:callback=>callback(),
    fetch:async(url, init)=>{request={url,...init};return {ok:true,blob:async()=>({})};},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
ctx.state = {page, url:'https://example.com/bread', draft:{display_name:'Corn Spoon Bread'},
    model:{title:'Corn Spoon Bread',saved_recipe_notes:[{heading:'Tip',items:['Saved note']}]},
    selections:{butter:'selected-bundle'}, projectionReady:true};
vm.runInContext('integratedRecipePreview=state', ctx);
const pdfButton = element('[data-preview-action="pdf"]');
pdfButton.dataset.previewAction='pdf';
(async()=>{
    assert.equal(ctx.loadRecipePreviewPreferences().print_notes,false);
    for (const size of ['smaller','normal','larger']) {
        for (let mask=0;mask<16;mask++) {
            const options={scale:2.5,text_size:size,nutrition_mode:'whole_recipe',
                show_image:Boolean(mask&1),show_nutrition:Boolean(mask&2),
                print_bundle_info:Boolean(mask&4),print_notes:Boolean(mask&8)};
            ctx.state.options=options;
            ctx.syncRecipePreviewOptions();
            assert.equal(element('[data-preview-image]').hidden,!options.show_image);
            assert.equal(element('[data-preview-nutrition]').hidden,!options.show_nutrition);
            assert.equal(element('[data-preview-print-notes]').hidden,!options.print_notes);
            assert.equal(element('.recipe-preview-card').dataset.textSize,size);
            assert.equal(element('.recipe-preview-card').dataset.printBundleInfo,options.print_bundle_info);
            ctx.saveRecipePreviewPreferences(options);
            assert.equal(ctx.loadRecipePreviewPreferences().print_notes,options.print_notes);
            await ctx.performRecipePreviewAction(pdfButton);
            assert.equal(request.url,'/api/recipe_preview/pdf');
            const payload=JSON.parse(request.body);
            assert.deepEqual(payload.options,options);
            assert.deepEqual(payload.ingredient_option_selections,{butter:'selected-bundle'});
            assert.deepEqual(Object.keys(payload).sort(),['ingredient_option_selections','options','recipe','url']);
            assert.equal(anchor.download,'Corn Spoon Bread - AI Pantry.pdf');
            assert.equal(pdfButton.disabled,false);
        }
    }
    assert.equal(downloadClicks,48);
    assert.equal(printCalls,0,'Download must remain an actual download');
    assert.equal(revoked,'blob:recipe');
    ctx.document.body.dataset.viewerUserId='person-b';
    assert.equal(ctx.loadRecipePreviewPreferences().print_notes,false,'Print preferences remain per-user');
    ctx.state.model.saved_recipe_notes=[];
    ctx.syncRecipePreviewOptions();
    assert.equal(element('[data-preview-print-notes]').hidden,true,'Do not print an empty notes section');
    listeners.beforeprint();
    assert(choices.every(choice=>choice.open));
    listeners.afterprint();
    assert.deepEqual(choices.map(choice=>choice.open),[false,true]);
    const printButton={dataset:{previewAction:'print'},hasAttribute:()=>false};
    await ctx.handleRecipePreviewClick({target:{closest:()=>printButton}});
    assert.equal(printCalls,1,'Print still uses the native print dialog');
    ctx.fetch=async()=>({ok:false,json:async()=>({error:'PDF rendering unavailable'})});
    await ctx.performRecipePreviewAction(pdfButton);
    assert.equal(element('recipePreviewStatus').textContent,'PDF rendering unavailable');
    assert.equal(pdfButton.disabled,false);
    assert.equal(ctx.state.pdfBusy,false);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", script,
         str(ROOT / "PushShoppingList/static/js/recipe-preview-renderer.js"),
         str(ROOT / "PushShoppingList/static/js/recipe-preview.js")],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
