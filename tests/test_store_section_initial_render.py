from pathlib import Path


def test_store_section_page_stays_hidden_until_enhancement_is_complete():
    template = Path("PushShoppingList/templates/store_sections.html").read_text(
        encoding="utf-8"
    )
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert (
        '{% set app_html_class = "store-section-master-initializing" %}' in template
    )
    assert "html.store-section-master-initializing body" in template
    assert "visibility: hidden;" in template
    assert "<noscript>" in template
    assert 'data-store-section-master-state="initializing"' in template
    assert 'aria-busy="true"' in template

    initializer = script.split("function initStoreSectionMasterPage()", 1)[1].split(
        "const RECIPE_INGREDIENT_CUSTOM_STORE_SECTIONS_KEY", 1
    )[0]
    assert initializer.index("initStoreSectionMasterTable();") < initializer.index(
        "initStoreSectionMasterIconPickers();"
    )
    assert initializer.index(
        "initStoreSectionMasterIconPickers();"
    ) < initializer.index("initStoreSectionMasterUsageDialog();")
    assert 'picker.classList.contains("is-enhanced")' in initializer
    assert 'select?.getAttribute("aria-hidden") === "true"' in initializer
    assert 'trigger?.hidden === false' in initializer
    assert 'getPropertyValue("--store-section-master-styles-ready")' in initializer
    assert 'page.dataset.storeSectionMasterState = "ready";' in initializer
    assert 'page.setAttribute("aria-busy", "false");' in initializer
    assert (
        'document.documentElement.classList.remove("store-section-master-initializing");'
        in initializer
    )
    assert "setTimeout" not in initializer
    assert '["initStoreSectionMasterPage", initStoreSectionMasterPage]' in script
    assert "--store-section-master-styles-ready: 1;" in css
