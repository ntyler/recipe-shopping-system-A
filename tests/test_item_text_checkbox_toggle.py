from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_item_text_toggles_checkbox_behavior_is_wired():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "function toggleItemCheckbox" in script
    assert "syncItemCheckedState(row, checkbox, itemText)" in script
    assert 'itemText.addEventListener("click"' in script
    assert 'itemText.addEventListener("keydown"' in script
    assert 'localStorage.setItem(`item-checked:${key}`' in script
    assert ".item-text" in css
    assert "cursor: pointer;" in css
    assert ".item-text:focus-visible" in css
