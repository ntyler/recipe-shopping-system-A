from pathlib import Path

from app import app


ROOT = Path(__file__).resolve().parents[1]


def test_ai_pantry_inventory_uses_recipe_editor_style_markup():
    template = (ROOT / "PushShoppingList/templates/sections/ai_pantry.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert '<a href="#aiPantryInventory">Inventory</a>' in template
    assert "ai-pantry-inventory-section" in template
    assert "recipe-edit-section-header ai-pantry-inventory-header" in template
    assert "recipe-edit-section-title" in template
    assert "Inventory <span class=\"ai-pantry-inventory-count\"" in template
    assert "ai-pantry-inventory-row" in template
    assert "recipe-edit-row-number ai-pantry-inventory-number" in template
    assert "recipe-edit-row-menu-wrap ai-pantry-inventory-menu-wrap" in template
    assert "Save inventory item" in template
    assert "Delete inventory item" in template
    assert ".ai-pantry-inventory-row" in css
    assert ".ai-pantry-inventory-header .recipe-edit-section-title h3" in css
    assert ".ai-pantry-card {\n    border: 0;" in css
    assert "background: transparent;" in css


def test_ai_pantry_entry_forms_share_panel_layout():
    template = (ROOT / "PushShoppingList/templates/sections/ai_pantry.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'class="ai-pantry-add-form ai-pantry-form-surface"' in template
    assert 'class="ai-pantry-receipt-form ai-pantry-form-surface"' in template
    assert "ai-pantry-form-field-wide" in template
    assert "ai-pantry-submit-btn" in template
    assert ".ai-pantry-form-surface {" in css
    assert ".ai-pantry-form-field {" in css
    assert ".ai-pantry-submit-btn {" in css


def test_ai_pantry_inventory_renders_inventory_heading():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "pantry-user"

        response = client.get("/sections/pantry")

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="#aiPantryInventory">Inventory</a>' in html
    assert "ai-pantry-inventory-section" in html
    assert "ai-pantry-inventory-count" in html
