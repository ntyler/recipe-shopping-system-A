from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recipe_import_modal_renders_backend_percentage_and_accessible_bar():
    template = (ROOT / "PushShoppingList" / "templates" / "sections" / "extraction_overlay.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList" / "static" / "css" / "extraction_overlay_old.css").read_text(encoding="utf-8")

    assert 'id="extractPercentText"' in template
    assert 'id="extractProgressBarLabel"' in template
    assert 'role="progressbar"' in template
    assert 'aria-valuemin="0"' in template
    assert 'aria-valuemax="100"' in template
    assert 'style="width:0%;"' in template

    assert "job.percent_complete" in script
    assert "backendExtractionPercent(progress)" in script
    assert 'track.setAttribute("aria-valuenow", String(value))' in script
    assert 'bar.style.width = `${value}%`' in script
    assert "recoverActiveImportProgress()" in script
    assert 'bar.style.width = "10%"' not in script
    assert 'bar.style.width = "100%"' not in script

    assert ".extract-old-percent" in css
    assert "background: #00cc66;" in css
