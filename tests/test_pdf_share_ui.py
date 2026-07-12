from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_recipe_pdf_section_is_wired_into_user_account_menu():
    index_template = read_text("PushShoppingList/templates/index.html")
    app_workspaces_template = read_text("PushShoppingList/templates/sections/app_workspaces.html")
    user_account_template = read_text("PushShoppingList/templates/sections/user_account.html")
    section_template = read_text("PushShoppingList/templates/sections/shared_recipe_pdfs.html")
    admin_support_template = read_text("PushShoppingList/templates/sections/admin_support.html")
    current_recipe_template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")
    js = read_text("PushShoppingList/static/js/app.js")

    assert '{% include "sections/app_workspaces.html" %}' in index_template
    assert '{% include "sections/enter_recipe_links.html" %}' in app_workspaces_template
    assert '{% include "sections/shared_recipe_pdfs.html" %}' not in index_template
    assert "RECIPE SHARING" in user_account_template
    assert "data-shared-recipe-pdfs-open" in user_account_template
    assert "openSharedRecipePdfsPanel()" in user_account_template
    assert 'data-lazy-section="shared-recipe-pdfs"' in user_account_template
    assert "main_bp.shared_recipe_pdfs_section" in user_account_template
    assert user_account_template.index("COMMUNICATIONS") < user_account_template.index("RECIPE SHARING")
    assert user_account_template.index("RECIPE SHARING") < user_account_template.index("SESSION")
    assert "Shared Recipe PDFs" in section_template
    assert "data-shared-recipe-pdfs-panel" in section_template
    assert "data-shared-recipe-pdfs-close" in section_template
    assert "Open PDF" in section_template
    assert "Copy PDF Link" in section_template
    assert "Upload to Cloudflare" in section_template
    assert "Cloudflare Orphan PDFs" not in section_template
    assert "Check Orphaned PDFs" not in section_template
    assert "PDF Maintenance" in admin_support_template
    assert "Check Unlinked PDFs" in admin_support_template
    assert "Check and Delete All Unlinked PDFs" in admin_support_template
    assert "checkAndDeleteAllCloudflareUnlinkedPdfs(this)" in admin_support_template
    assert "Delete Selected Unlinked PDFs" in admin_support_template
    assert "deleteSelectedCloudflareUnlinkedPdfs(this)" in admin_support_template
    assert "data-cloudflare-orphan-pdf-list" in admin_support_template
    assert "data-cloudflare-orphan-pdf-empty" in admin_support_template
    assert "Create Share Link" not in section_template
    assert "Copy PDF Link" in section_template
    assert "data-pdf-share-row" in section_template
    assert "data-pdf-public-url" in section_template
    assert "pdf-cloudflare-url" in section_template
    assert ".pdf-share-card" in css
    assert ".user-shared-recipe-pdfs-panel" in css
    assert ".pdf-cloudflare-active" in css
    assert ".pdf-cloudflare-url" in css
    assert ".pdf-orphan-admin" in css
    assert ".pdf-orphan-table" in css
    assert ".pdf-orphan-select" in css
    assert ".pdf-orphan-reason" in css
    assert "Copy Cloudflare Link" in current_recipe_template
    assert "recipeEditLocalPdfDownloadButton" in current_recipe_template
    assert "Download Local PDF" in current_recipe_template
    assert "{% if current_user and current_user.is_admin %}" in current_recipe_template
    assert "R2_PUBLIC_BASE_URL" in read_text("PushShoppingList/services/cloudflare_r2_storage.py")
    assert "function createPdfShareLink" in js
    assert "function copyPdfShareLink" in js
    assert "function revokePdfShareLink" in js
    assert "function uploadPdfToCloudflare" in js
    assert "function copyPdfCloudflareLink" in js
    assert "function checkCloudflareOrphanPdfs" in js
    assert "function selectedCloudflareUnlinkedPdfKeys" in js
    assert "function cloudflareUnlinkedPdfKeysFromData" in js
    assert "function updateCloudflareUnlinkedDeleteButton" in js
    assert "function deleteSelectedCloudflareUnlinkedPdfs" in js
    assert "function checkAndDeleteAllCloudflareUnlinkedPdfs" in js
    assert "function deleteAllCloudflareOrphanPdfs" in js
    assert "/pdfs/cloudflare_unlinked" in js
    assert "/pdfs/cloudflare_unlinked/delete" in js
    assert "/pdfs/cloudflare_orphans/delete" not in js
    assert "data-cloudflare-unlinked-pdf-key" in js
    assert "Select all unlinked PDFs" in js
    assert "selected unlinked PDF" in js
    assert "Deleting unlinked PDFs is disabled" not in js
    assert "PDF filename" in js
    assert "Suspected type" in js
    assert "function openSharedRecipePdfsPanel" in js
    assert "function closeSharedRecipePdfsPanel" in js
    assert "function uploadRecipeEditorPdfToCloudflare" in js
    assert "function copyRecipeEditorPdfLink" in js
    assert "recipeArchivePdfDownloadUrl" in js


def test_recipe_entry_divider_and_ai_pantry_centering_are_wired():
    enter_template = read_text("PushShoppingList/templates/sections/enter_recipe_links.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "recipe-entry-section-divider" in enter_template
    assert ".app-section-divider" in css
    assert ".recipe-entry-section-divider" in css
    assert "#aiPantrySection .ai-pantry-toggle" in css
    assert "justify-content: center;" in css
    assert "text-align: center;" in css


def test_recipe_editor_uses_split_source_and_generated_pdf_fields():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    js = read_text("PushShoppingList/static/js/app.js")

    assert "recipe-edit-file-groups" in template
    assert "Source URL" in template
    assert "Source PDF Path" in template
    assert "Source Cloudflare PDF Path" in template
    assert "Generated PDF Path" in template
    assert "Generated Cloudflare PDF Path" in template
    assert "SOURCE FILES" not in template
    assert "GENERATED FILES" not in template
    assert "<span>PDF Path</span>" not in template
    assert "Cloudflare PDF URL" not in template
    assert "recipeEditSourcePdfPath" in template
    assert "recipeEditGeneratedPdfPath" in template
    assert '<textarea id="recipeEditSourcePdfPath"' not in template
    assert '<textarea id="recipeEditGeneratedCloudflarePdfUrl"' not in template
    assert template.index("recipeEditGeneratedCloudflarePdfUrl") < template.index("recipeEditServings")
    assert "source_pdf_path" in js
    assert "generated_pdf_path" in js
    assert 'startBackgroundJob("/api/jobs/upload-generated-pdf"' in js
    assert "url: sourceUrlValue" in js
    assert 'kind: "generated_recipe"' in js
    assert "This recipe does not have a generated Recipe PDF yet. Do you want to create one now?" in js
    assert "Save and Create PDF" in js
    assert "Save Without PDF" in js
    assert "const generatedOpenUrl = generatedCloudflareUrl;" in js
    assert "const sourceOpenUrl = sourceCloudflareUrl;" in js
    assert "waitForGeneratedCloudflare: true" in js
    assert "function recipePdfSaveChoiceForPayload" in js


def test_recipe_editor_header_orders_menu_icon_after_source_pdf():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    header_start = template.index('<div class="recipe-edit-header-actions">')
    header_end = template.index('<div class="recipe-edit-section-menu-wrap recipe-edit-header-menu-wrap">', header_start)
    header_actions = template[header_start:header_end]

    assert header_actions.index('id="recipeEditPdfButton"') < header_actions.index('id="recipeEditSourcePdfButton"')
    assert header_actions.index('id="recipeEditSourcePdfButton"') < header_actions.index('id="recipeEditMenuOrderButton"')


def test_recipe_overflow_menus_include_source_pdf_near_recipe_pdf():
    current_recipe_template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    cookbook_template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    items_template = read_text("PushShoppingList/templates/sections/items.html")
    routes = read_text("PushShoppingList/routes/main_routes.py")

    assert "source_pdf_public_url" in routes

    menus = [
        (current_recipe_template, "recipe-url-summary-pdf", "recipe-url-summary-source-pdf"),
        (cookbook_template, "cookbook-recipe-menu-pdf", "cookbook-recipe-menu-source-pdf"),
        (items_template, "recipe-view-menu-pdf", "recipe-view-menu-source-pdf"),
    ]

    for template, recipe_pdf_class, source_pdf_class in menus:
        assert source_pdf_class in template
        assert template.index(recipe_pdf_class) < template.index(source_pdf_class)
        assert "Open recipe PDF" in template
        assert "Open source PDF" in template
        assert "kind='webpage_backup'" in template


def test_recipe_imports_queue_generated_recipe_pdf_creation():
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    assert "def schedule_generated_recipe_pdf_creation" in routes
    assert "run_generated_recipe_pdf_creation(recipe_url, context=context)" in routes
    assert 'schedule_generated_recipe_pdf_creation(url, context="form-url")' in routes
    assert 'schedule_generated_recipe_pdf_creation(recipe_url, context="media-upload")' in routes
    assert 'schedule_generated_recipe_pdf_creation(url, context="api-url")' in routes
    assert "action=auto_generated_failed" in routes
