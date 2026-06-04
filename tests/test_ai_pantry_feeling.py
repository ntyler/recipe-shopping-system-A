from pathlib import Path

from app import app


ROOT = Path(__file__).resolve().parents[1]


def test_ai_pantry_cook_feeling_section_is_rendered():
    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "#aiPantryCookWhatImFeeling" in html
    assert "Cook What I'm Feeling" in html
    assert "pantryFeelingInput" in html
    assert "pantryFeelingPromptOutput" in html


def test_ai_pantry_cook_feeling_assets_are_wired():
    template = (ROOT / "PushShoppingList/templates/sections/ai_pantry.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    js = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "data-pantry-ingredient" in template
    assert "onsubmit=\"return buildPantryFeelingPrompt(this);\"" in template
    assert ".ai-pantry-feeling-form" in css
    assert ".ai-pantry-feeling-grid" in css
    assert "function buildPantryFeelingPrompt" in js
    assert "function copyPantryFeelingPrompt" in js
