from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recipe_task_text_toggles_equipment_and_instruction_checkboxes():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    items_template = (ROOT / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")

    assert 'data-task-key="equipment|' in items_template
    assert 'data-task-key="instruction|' in items_template
    assert "function toggleRecipeTaskCheckbox" in script
    assert "syncRecipeTaskCheckedState(checkbox, text)" in script
    assert 'text.addEventListener("click"' in script
    assert 'text.addEventListener("keydown"' in script
    assert 'localStorage.setItem(`recipe-task-checked:${key}`' in script
    assert ".recipe-task-text" in css
    assert ".recipe-task-text:focus-visible" in css
