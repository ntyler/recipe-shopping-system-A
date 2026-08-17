import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_appearance_bootstrap_is_loaded_before_css_on_every_app_layout_page():
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")
    theme_head = read_text("PushShoppingList/templates/includes/public_theme_head.html")
    public_auth = read_text("PushShoppingList/templates/public_auth.html")
    legal_page = read_text("PushShoppingList/templates/legal_page.html")

    include = '{% include "includes/public_theme_head.html" %}'
    assert layout.count(include) == 1
    assert layout.index(include) < layout.index('filename=\'css/app.css\'')
    assert include not in public_auth
    assert include not in legal_page
    assert 'var STORAGE_KEY = "ai-pantry-public-theme";' in theme_head
    assert "root.dataset.publicAuthTheme = selectedTheme;" in theme_head
    assert "delete root.dataset.publicAuthTheme;" in theme_head
    assert 'systemQuery.addEventListener("change", handleSystemThemeChange);' in theme_head
    assert 'window.addEventListener("storage"' in theme_head


def test_sign_out_cleanup_preserves_the_shared_appearance_preference():
    firebase_auth = read_text("PushShoppingList/static/js/firebase-auth.js")
    cleanup_start = firebase_auth.index("function clearPostSignOutClientState")
    cleanup_end = firebase_auth.index("function navigateToCanonicalSignInAfterSignOut", cleanup_start)
    cleanup = firebase_auth[cleanup_start:cleanup_end]

    assert '"ai-pantry-public-theme"' not in cleanup
    assert "localStorage.clear()" not in cleanup


def test_settings_display_panel_has_one_accessible_three_choice_appearance_group():
    template = read_text("PushShoppingList/templates/sections/settings_workspace.html")
    css = read_text("PushShoppingList/static/css/app.css")
    panel_start = template.index('id="settingsDisplayPanel"')
    panel_end = template.index('data-settings-panel="rules-automation"', panel_start)
    panel = template[panel_start:panel_end]

    assert '<fieldset class="settings-appearance"' in panel
    assert "<legend>Appearance</legend>" in panel
    assert 'aria-describedby="settingsAppearanceHelp"' in panel
    assert panel.count('type="radio"') == 3
    assert panel.count("data-app-theme-choice") == 3
    for value, label in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
        assert f'value="{value}"' in panel
        assert f"<strong>{label}</strong>" in panel

    assert ".settings-appearance-option:has(input:checked)" in css
    assert ".settings-appearance-option:has(input:focus-visible)" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css


def test_shared_appearance_controller_initializes_persists_and_tracks_system_changes():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the shared appearance regression")

    source = read_text("PushShoppingList/templates/includes/public_theme_head.html")
    source = source.replace("<script>", "", 1).rsplit("</script>", 1)[0]
    harness = f"""
const stored = new Map([["ai-pantry-public-theme", "dark"]]);
const dispatched = [];
const windowListeners = {{}};
const systemQuery = {{
    matches: false,
    listener: null,
    addEventListener(type, callback) {{ if (type === "change") this.listener = callback; }},
}};
function control(value) {{
    return {{
        value,
        checked: false,
        dataset: {{}},
        listeners: {{}},
        addEventListener(type, callback) {{ this.listeners[type] = callback; }},
    }};
}}
const choices = [control("system"), control("light"), control("dark")];
const root = {{ dataset: {{}}, style: {{}} }};
globalThis.CustomEvent = class CustomEvent {{
    constructor(type, options) {{ this.type = type; this.detail = options.detail; }}
}};
globalThis.localStorage = {{
    getItem(key) {{ return stored.has(key) ? stored.get(key) : null; }},
    setItem(key, value) {{ stored.set(key, value); }},
}};
globalThis.document = {{
    documentElement: root,
    readyState: "complete",
    querySelectorAll(selector) {{
        return selector === "[data-app-theme-choice]" ? choices : [];
    }},
}};
globalThis.window = {{
    matchMedia() {{ return systemQuery; }},
    addEventListener(type, callback) {{ windowListeners[type] = callback; }},
    dispatchEvent(event) {{ dispatched.push(event.detail); }},
}};
{source}
const initial = {{
    preference: window.aiPantryTheme.getPreference(),
    attribute: root.dataset.publicAuthTheme,
    scheme: root.style.colorScheme,
    darkChecked: choices[2].checked,
}};
window.aiPantryTheme.setPreference("light");
const light = {{
    stored: stored.get("ai-pantry-public-theme"),
    attribute: root.dataset.publicAuthTheme,
    scheme: root.style.colorScheme,
    lightChecked: choices[1].checked,
}};
window.aiPantryTheme.setPreference("system");
systemQuery.matches = true;
systemQuery.listener({{ matches: true }});
const system = {{
    stored: stored.get("ai-pantry-public-theme"),
    hasAttribute: Object.prototype.hasOwnProperty.call(root.dataset, "publicAuthTheme"),
    scheme: root.style.colorScheme,
    systemChecked: choices[0].checked,
    resolved: window.aiPantryTheme.getResolvedTheme(),
}};
choices[2].checked = true;
choices[2].listeners.change();
const darkEventCount = dispatched.length;
systemQuery.matches = false;
systemQuery.listener({{ matches: false }});
const dark = {{
    stored: stored.get("ai-pantry-public-theme"),
    preference: window.aiPantryTheme.getPreference(),
    attribute: root.dataset.publicAuthTheme,
    scheme: root.style.colorScheme,
    darkChecked: choices[2].checked,
    ignoredSystemEvent: dispatched.length === darkEventCount,
}};
process.stdout.write(JSON.stringify({{ initial, light, system, dark }}));
"""
    result = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    state = json.loads(result.stdout)

    assert state["initial"] == {
        "preference": "dark",
        "attribute": "dark",
        "scheme": "dark",
        "darkChecked": True,
    }
    assert state["light"] == {
        "stored": "light",
        "attribute": "light",
        "scheme": "light",
        "lightChecked": True,
    }
    assert state["system"] == {
        "stored": "system",
        "hasAttribute": False,
        "scheme": "dark",
        "systemChecked": True,
        "resolved": "dark",
    }
    assert state["dark"] == {
        "stored": "dark",
        "preference": "dark",
        "attribute": "dark",
        "scheme": "dark",
        "darkChecked": True,
        "ignoredSystemEvent": True,
    }


def test_recipe_editor_theme_tokens_follow_the_shared_root_preference():
    css = read_text("PushShoppingList/static/css/app.css")
    v15_start = css.index("/* Recipe workspace v15: accepted two-column Edit Recipe mockup. */")
    v16_start = css.index("/* Recipe workspace v16: native-zoom readability and container-aware context rail. */")
    workspace = css[v15_start:v16_start]

    assert "Keep editor content color-locked" not in css
    assert "--recipe-editor-bg: #f8faf9;" in workspace
    assert "--recipe-editor-surface: #ffffff;" in workspace
    assert "--recipe-editor-border: #dfe6e2;" in workspace
    assert "--recipe-editor-border-soft: #e8eeeb;" in workspace
    assert 'html[data-public-auth-theme="dark"] body.recipe-edit-standalone-page' in workspace
    assert 'html:not([data-public-auth-theme="light"]) body.recipe-edit-standalone-page' in workspace
    assert "--recipe-editor-bg: #101415;" in workspace
    assert "--recipe-editor-surface: #171c1e;" in workspace
    assert "color-scheme: inherit;" in workspace
