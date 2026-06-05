from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shopping_list_has_global_collapse_controls():
    index_template = read_text("PushShoppingList/templates/index.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "data-global-collapse-controls" in index_template
    assert "Collapse All" in index_template
    assert "Expand All" in index_template
    assert "onclick=\"return collapseAllShoppingListPage()\"" in index_template
    assert "onclick=\"return expandAllShoppingListPage()\"" in index_template
    assert "data-global-collapse-status" in index_template
    assert "aria-live=\"polite\"" in index_template
    assert ".shopping-global-collapse-controls" in css
    assert ".shopping-global-collapse-btn" in css
    assert ".shopping-global-collapse-status" in css
    assert "@media (max-width: 650px)" in css


def test_global_collapse_action_targets_page_sections_and_nested_panels():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "function collapseAllShoppingListPage()" in script
    assert "function expandAllShoppingListPage()" in script
    assert "function setAllCardCollapseContentCollapsed(collapsed)" in script
    assert "function setShoppingListViewRowsCollapsed(collapsed)" in script
    assert "function setAllRecipeViewNestedPanelsCollapsed(collapsed)" in script
    assert "function setAllCookbookPanelsCollapsed(collapsed)" in script
    assert "function closeShoppingListExpandedPanels()" in script
    assert "setAllCardCollapseContentCollapsed(true)" in script
    assert "setShoppingListViewRowsCollapsed(true)" in script
    assert "setAllRecipeViewNestedPanelsCollapsed(true)" in script
    assert "setAllCookbookPanelsCollapsed(true)" in script
    assert "setAllShoppingListRecipeImagesVisible(false)" in script
    assert 'setShoppingGlobalCollapseStatus("Everything collapsed.")' in script
    assert "setAllShoppingListRecipeImagesVisible(recipeImagesShownByDefault())" in script
    assert ".recipe-global-image-hidden" in css
