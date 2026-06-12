from pathlib import Path


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


def test_recipe_edit_menu_links_open_modal_in_current_tab():
    for relative_path in (
        "PushShoppingList/templates/sections/items.html",
        "PushShoppingList/templates/sections/current_recipe_url_log.html",
        "PushShoppingList/templates/sections/cookbooks.html",
    ):
        template = read_text(relative_path)
        blocks = edit_recipe_blocks(template)

        assert blocks, f"{relative_path} should include an Edit recipe action"
        assert any("openRecipeEditorFromMenu(this, {}, event)" in block for block in blocks)

        for block in blocks:
            assert 'target="_blank"' not in block


def test_recipe_editor_close_restores_portaled_menu_return_target():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "let recipeEditReturnState = null;" in script
    assert "triggerMenu.recipeEditAnchorButton" in script
    assert "restoreRecipeEditorReturnState();" in script
    assert "window.location.reload();" not in script[
        script.index("function closeRecipeEditor()"):
        script.index("function populateRecipeEditor")
    ]
