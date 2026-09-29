from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def edit_recipe_blocks(template):
    blocks = []
    marker = "Edit recipe"
    start = 0

    while True:
        index = template.find(marker, start)
        if index == -1:
            return blocks
        blocks.append(template[max(0, index - 420):index + len(marker) + 80])
        start = index + len(marker)


def test_recipe_edit_menu_links_use_same_tab_page_navigation():
    for relative_path in (
        "PushShoppingList/templates/sections/items.html",
        "PushShoppingList/templates/sections/current_recipe_url_log.html",
        "PushShoppingList/templates/sections/cookbooks.html",
    ):
        template = read_text(relative_path)
        blocks = edit_recipe_blocks(template)

        assert blocks, f"{relative_path} should include an Edit recipe action"
        assert any("openRecipeEditPageFromMenu(this, event)" in block for block in blocks)

        for block in blocks:
            assert 'target="_blank"' not in block


def test_recipe_editor_page_navigation_remembers_return_target():
    script = read_text("PushShoppingList/static/js/app.js")

    assert 'const RECIPE_EDIT_PAGE_RETURN_STATE_KEY = "recipe-edit-page-return-state";' in script
    assert "function openRecipeEditPageFromMenu" in script
    assert "rememberRecipeEditPageReturnState(link);" in script
    assert "return true;" in script[
        script.index("function openRecipeEditPageFromMenu"):
        script.index("function shouldLetRecipeEditorLinkNavigate")
    ]
    assert "triggerMenu.recipeEditAnchorButton" in script
    assert "restoreRecipeEditPageReturnState" in script
    assert '["initLazySections", initLazySections]' in script
    assert '["restoreRecipeEditPageReturnState", restoreRecipeEditPageReturnState]' in script
    assert script.index('["initLazySections", initLazySections]') < script.index(
        '["restoreRecipeEditPageReturnState", restoreRecipeEditPageReturnState]'
    )
    assert "function expandRecipeEditorReturnSurface" in script
    assert '"current-recipes": "recipe-url-log"' in script
    assert "toggleCardCollapse(collapseKey);" in script


def test_recipe_editor_pending_action_preserves_infer_details_options():
    script = read_text("PushShoppingList/static/js/app.js")
    pending_block = script[
        script.index("function recipeEditPendingActionFromOptions"):
        script.index("function openRecipeEditPageFallback")
    ]

    assert "action.inferMissingDetails = true;" in pending_block
    assert "action.cookbookId = String(optionObject.cookbookId || optionObject.cookbook_id || \"\").trim();" in pending_block
    assert "action.cookbookName = String(optionObject.cookbookName || optionObject.cookbook_name || \"\").trim();" in pending_block
    assert "action.overwriteAiFields = Boolean(optionObject.overwriteAiFields);" in pending_block
    assert "action.previewOnly = Boolean(optionObject.previewOnly);" in pending_block
    assert "inferMissingDetails: Boolean(action.inferMissingDetails)" in pending_block
    assert "cookbookId: String(action.cookbookId || \"\").trim()" in pending_block
    assert "cookbookName: String(action.cookbookName || \"\").trim()" in pending_block
    assert "overwriteAiFields: Boolean(action.overwriteAiFields)" in pending_block
    assert "previewOnly: Boolean(action.previewOnly)" in pending_block


def test_recipe_editor_modal_close_does_not_reload_current_page():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "triggerMenu.recipeEditAnchorButton" in script
    assert "restoreRecipeEditorReturnState();" in script
    assert "window.location.reload();" not in script[
        script.index("function closeRecipeEditor(options = {})"):
        script.index("function populateRecipeEditor")
    ]


def test_recipe_editor_return_scroll_offsets_current_recipe_sticky_header():
    script = read_text("PushShoppingList/static/js/app.js")
    jump_block = script[
        script.index("function scrollRecipeJumpTargetIntoView"):
        script.index("function updateViewSwitcherStickyOffset")
    ]

    assert "scrollRecipeJumpTargetBelowStickyHeader(target);" in jump_block
    assert "function currentRecipesStickyHeaderOffset" in jump_block
    assert '#currentRecipeUrlLogCard:not(.card-collapsed)' in jump_block
    assert ":scope > .recipe-url-log-header" in jump_block
    assert '[data-current-recipe-row]' in jump_block
    assert "scrollAppMainBy({" in jump_block
    assert "top: -offset" in jump_block


def test_recipe_editor_return_scroll_offsets_cookbook_sticky_header():
    script = read_text("PushShoppingList/static/js/app.js")
    jump_block = script[
        script.index("function scrollRecipeJumpTargetIntoView"):
        script.index("function updateViewSwitcherStickyOffset")
    ]

    assert "function cookbooksStickyHeaderOffset" in jump_block
    assert '#cookbooksCard:not(.card-collapsed)' in jump_block
    assert ":scope > .cookbooks-toggle" in jump_block
    assert "[data-cookbook-recipe-card]" in jump_block
    assert "currentRecipesStickyHeaderOffset(target) || cookbooksStickyHeaderOffset(target)" in jump_block


def test_recipe_editor_cancel_uses_stored_page_return_before_history():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    close_block = script[
        script.index("function closeRecipeEditor(options = {})"):
        script.index("function populateRecipeEditor")
    ]

    assert 'class="recipe-edit-cancel" onclick="closeRecipeEditor()"' in template
    assert "function recipeEditPageReturnUrlFromState" in script
    assert "const returnUrl = recipeEditPageReturnUrlFromState();" in close_block
    assert close_block.index("window.location.assign(returnUrl);") < close_block.index("window.history.back();")


def test_food_review_badges_open_active_review_flow():
    script = read_text("PushShoppingList/static/js/app.js")
    recipe_view = read_text("PushShoppingList/templates/sections/items.html")
    current_recipes = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    cookbooks = read_text("PushShoppingList/templates/sections/cookbooks.html")

    assert "function openRecipeFoodReviewFromRecipeView" in script
    assert "activateFoodReview: true" in script[
        script.index("function openRecipeFoodReviewFromRecipeView"):
        script.index("function openIngredientFoodReviewFromRecipeView")
    ]
    assert "activateFoodReview: true" in script[
        script.index("function openIngredientFoodReviewFromRecipeView"):
        script.index("function closeRecipeEditor")
    ]
    assert "await activateRecipeEditorFoodReviewMarker(marker);" in script
    assert "function recipeEditorFoodReviewMarkerForRow" in script
    assert "function recipeEditorIngredientRowForName" in script
    assert 'const RECIPE_EDIT_PENDING_ACTION_KEY = "recipe-edit-pending-action";' in script
    assert "function openRecipeEditPageFallback" in script
    assert "rememberRecipeEditPendingAction(recipeUrl, options);" in script
    assert "openRecipeEditPageFallback(button, url, options);" in script
    assert "function bindRecipeEditorPrefetch" in script
    assert "bindRecipeEditorPrefetch();" in script
    assert "function prefetchRecipeEditorDataFromTarget" in script
    assert "[data-recipe-url][onclick*='openRecipeFoodReviewFromRecipeView']" in script
    assert "await cached.promise;" in script
    assert "allowCreateIngredient: INGREDIENT_AND_OR_SEPARATOR_PATTERN.test(choiceText)" in script
    assert "|| Boolean(review.allowCreateIngredient)" in script
    assert "createIngredientFromFoodReviewChoice(this, event)" in script

    assert recipe_view.count("openRecipeFoodReviewFromRecipeView(this, event)") == 1
    assert current_recipes.count("openRecipeFoodReviewFromRecipeView(this, event)") >= 1
    assert "recipe-url-summary-status-row" in current_recipes
    assert cookbooks.count("openRecipeFoodReviewFromRecipeView(this, event)") >= 1
    assert "openIngredientFoodReviewFromRecipeView(this, event)" in recipe_view


def test_recipe_edit_page_consumes_pending_editor_action():
    template = read_text("PushShoppingList/templates/recipe_edit_page.html")

    assert "consumeRecipeEditPendingAction(recipeUrl)" in template
    assert "openRecipeEditor({ dataset: { recipeUrl } }, pendingOptions).then(" in template


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for navigation checks")
def test_recipe_preview_direct_link_waits_for_loading_and_preserves_back_navigation():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const inline=fs.readFileSync(process.argv[1],'utf8').split('<script>')[1].split('</script>')[0];
const source='https://example.test/menu/?category=1&menu_item=menu-item-4-Anticucho_Heart_and_Rachi';
const base='http://127.0.0.1:5083/recipe/edit?viewer_user_id=viewer&url='+encodeURIComponent(source);
(async()=>{
 for(const scenario of [
  {hash:'#recipe-preview',loaded:true,existing:false},
  {hash:'#recipe-preview',loaded:true,existing:true},
  {hash:'#recipe-preview',loaded:false,existing:false},
  {hash:'',loaded:true,existing:false},
 ]){
  let boot,resolveLoad;const opened=[],replacements=[];
  const location=new URL(base+scenario.hash);
  const entries=[{url:base,state:null},{url:location.href,state:scenario.existing?{recipePreview:true}:null}];
  const history={state:entries.at(-1).state,
   replaceState(state,unused,url){replacements.push(url);this.state=state;location.href=new URL(url,location).href;entries[entries.length-1]={url:location.href,state};},
   pushState(state,unused,url){this.state=state;location.href=new URL(url,location).href;entries.push({url:location.href,state});},
   back(){entries.pop();this.state=entries.at(-1).state;location.href=entries.at(-1).url;},
  };
  const ctx={window:{location,history,addEventListener(type,handler){boot=handler;}},
   document:{body:{dataset:{recipeEditUrl:source}}},
   organizeRecipeEditCompactSummary(){},organizeRecipeEditCompactSections(){},organizeRecipeEditCoverDialog(){},syncRecipeEditCompactSummary(){},
   consumeRecipeEditPendingAction(url){assert.equal(url,source);return {section:'ingredients'};},
   openRecipeEditor(button,options){assert.equal(button.dataset.recipeUrl,source);assert.equal(options.section,'ingredients');return new Promise(resolve=>resolveLoad=resolve);},
   openIntegratedRecipePreview(options){opened.push(options);if(options.history)history.pushState({recipePreview:true},'','#recipe-preview');},
  };
  vm.createContext(ctx);vm.runInContext(inline,ctx);boot();
  assert.equal(opened.length,0,'Wait for the editor data before opening its preview');
  resolveLoad(scenario.loaded);await new Promise(resolve=>setImmediate(resolve));
  if(!scenario.loaded||!scenario.hash){assert.equal(opened.length,0);assert.equal(replacements.length,0);continue;}
  assert.equal(opened.length,1);assert.equal(opened[0].history,!scenario.existing);
  assert.equal(replacements.length,scenario.existing?0:1);
  assert.equal(location.href,base+'#recipe-preview');
  assert.equal(location.searchParams.get('url'),source);
  assert.equal(location.searchParams.get('viewer_user_id'),'viewer');
  history.back();assert.equal(location.href,base,'Back to Editor stays on this recipe');
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([shutil.which("node"), "-e", script,
                             str(ROOT / "PushShoppingList/templates/recipe_edit_page.html")],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
