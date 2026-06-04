from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_recipe_pdf_section_is_wired_into_main_page():
    index_template = read_text("PushShoppingList/templates/index.html")
    section_template = read_text("PushShoppingList/templates/sections/shared_recipe_pdfs.html")
    css = read_text("PushShoppingList/static/css/app.css")
    js = read_text("PushShoppingList/static/js/app.js")

    assert '{% include "sections/enter_recipe_links.html" %}' in index_template
    assert '{% include "sections/shared_recipe_pdfs.html" %}' in index_template
    assert index_template.index('sections/enter_recipe_links.html') < index_template.index('sections/shared_recipe_pdfs.html')
    assert "Shared Recipe PDFs" in section_template
    assert "Open PDF" in section_template
    assert "Copy PDF Link" in section_template
    assert "Upload to Cloudflare" in section_template
    assert "Create Share Link" not in section_template
    assert "Copy Link" in section_template
    assert "Revoke Link" in section_template
    assert "data-pdf-share-row" in section_template
    assert "data-pdf-public-url" in section_template
    assert "pdf-cloudflare-url" in section_template
    assert ".pdf-share-card" in css
    assert ".pdf-cloudflare-active" in css
    assert ".pdf-cloudflare-url" in css
    assert "Upload to Cloudflare" in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "Copy PDF Link" in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "R2_PUBLIC_BASE_URL" in read_text("PushShoppingList/services/cloudflare_r2_storage.py")
    assert "function createPdfShareLink" in js
    assert "function copyPdfShareLink" in js
    assert "function revokePdfShareLink" in js
    assert "function uploadPdfToCloudflare" in js
    assert "function copyPdfCloudflareLink" in js
    assert "function uploadRecipeEditorPdfToCloudflare" in js
    assert "function copyRecipeEditorPdfLink" in js


def test_recipe_entry_divider_and_ai_pantry_centering_are_wired():
    enter_template = read_text("PushShoppingList/templates/sections/enter_recipe_links.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "recipe-entry-section-divider" in enter_template
    assert ".app-section-divider" in css
    assert ".recipe-entry-section-divider" in css
    assert "#aiPantrySection .ai-pantry-toggle" in css
    assert "justify-content: center;" in css
    assert "text-align: center;" in css
