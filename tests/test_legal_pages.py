import re
from pathlib import Path

from PushShoppingList.app import PUBLIC_ENDPOINTS
from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service as accounts
from PushShoppingList.services.legal_content import LEGAL_DOCUMENTS


ROOT = Path(__file__).resolve().parents[1]


def seeded_app(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")
    accounts.save_users({
        "users": [{
            "user_id": "legal-page-user",
            "first_name": "Legal",
            "last_name": "Reader",
            "username": "legal-reader",
            "email": "reader@example.com",
            "auth_provider": "firebase",
            "account_status": "active",
        }]
    })
    app = create_app()
    app.config.update(TESTING=True)
    return app


def assert_public_legal_surface(html, slug):
    document = LEGAL_DOCUMENTS[slug]
    assert f'data-public-legal-page="{slug}"' in html
    assert "data-public-legal-layout" in html
    assert "data-public-auth-header" in html
    assert "data-public-auth-footer" in html
    assert "data-app-layout" not in html
    assert "data-app-sidebar" not in html
    assert "data-app-header" not in html
    assert f"<title>{document['title']} | AI Pantry</title>" in html
    assert f'<meta name="description" content="{document["description"]}">' in html
    assert "Effective Date" in html
    assert "Last Updated" in html
    assert html.count("July 13, 2026") == 2
    assert "Table of Contents" in html
    assert 'href="/"' in html
    assert "Back to AI Pantry" in html
    assert 'static/js/public-auth.js' in html
    assert 'static/js/app.js' not in html

    for section in document["sections"]:
        assert f'href="#{section["id"]}"' in html
        assert f'id="{section["id"]}"' in html


def test_terms_and_privacy_routes_are_public_for_signed_out_signed_in_and_guest_sessions(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    assert "main_bp.terms_route" in PUBLIC_ENDPOINTS
    assert "main_bp.privacy_route" in PUBLIC_ENDPOINTS

    with app.test_client() as client:
        for path, slug in (("/terms", "terms"), ("/privacy", "privacy")):
            response = client.get(path)
            assert response.status_code == 200
            assert_public_legal_surface(response.get_data(as_text=True), slug)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "legal-page-user"
        for path, slug in (("/terms", "terms"), ("/privacy", "privacy")):
            response = client.get(path)
            assert response.status_code == 200
            assert_public_legal_surface(response.get_data(as_text=True), slug)

    with app.test_client() as client:
        client.get("/guest/start")
        for path, slug in (("/terms", "terms"), ("/privacy", "privacy")):
            response = client.get(path)
            assert response.status_code == 200
            assert_public_legal_surface(response.get_data(as_text=True), slug)


def test_legal_pages_render_required_content_metadata_footer_and_deletion_workflow(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        terms = client.get("/terms").get_data(as_text=True)
        privacy = client.get("/privacy").get_data(as_text=True)

    assert '<link rel="canonical" href="http://localhost/terms">' in terms
    assert '<link rel="canonical" href="http://localhost/privacy">' in privacy
    assert "AI Pantry does not store or have access to your authentication provider password." in terms
    assert "AI Pantry is not a medical, nutritional, dietary, or food-safety service." in terms
    assert "The final governing jurisdiction will be listed here before public launch." in terms
    assert "Pending final legal review" in terms
    assert 'href="mailto:support@aipantry.app"' in terms
    assert "Welcome to AI Pantry (“AI Pantry,” “we,” “our,” or “us”)." in terms

    assert "AI Pantry configures its providers and integrations according to the options" in privacy
    assert "AI Pantry does not sell personal information." in privacy
    assert "cross-context behavioral advertising" in privacy
    assert 'href="mailto:support@aipantry.app"' in privacy
    assert 'class="public-legal-action" href="/#settingsDangerZonePanel"' in privacy
    assert "Request Account Deletion" in privacy
    assert "Children’s Privacy" in privacy
    assert "â" not in terms
    assert "â" not in privacy

    app_script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    account_routes = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    settings_template = (ROOT / "PushShoppingList/templates/sections/settings_workspace.html").read_text(
        encoding="utf-8"
    )
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(
        encoding="utf-8"
    )
    assert 'settingsDangerZonePanel: "danger-zone"' in app_script
    assert '@account_bp.route("/account/delete/request", methods=["POST"])' in account_routes
    assert 'id="settingsDangerZonePanel"' in settings_template
    assert 'action="{{ url_for(\'account_bp.request_account_delete_route\') }}"' in account_template

    terms_footer = terms[terms.index('class="public-auth-footer'):]
    privacy_footer = privacy[privacy.index('class="public-auth-footer'):]
    assert re.search(
        r'href="/terms"\s+class="is-current" aria-current="page"',
        terms_footer,
    )
    assert re.search(
        r'href="/privacy"\s+class="is-current" aria-current="page"',
        privacy_footer,
    )
    assert "&copy; 2026 AI Pantry" in terms_footer
    assert "Help &amp; Support" in terms_footer


def test_sign_in_legal_sentence_and_footer_use_same_tab_links(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)

    legal_start = html.index('class="public-auth-legal"')
    legal_end = html.index("</p>", legal_start)
    legal = html[legal_start:legal_end]
    assert "By signing in, you agree to our" in legal
    assert "and acknowledge our" in legal
    assert '<a href="/terms">Terms of Service</a>' in legal
    assert '<a href="/privacy">Privacy Policy</a>' in legal
    assert "target=" not in legal

    footer = html[html.index('class="public-auth-footer'):]
    assert '<a href="/terms"' in footer
    assert '<a href="/privacy"' in footer
    assert "target=" not in footer

    template = (ROOT / "PushShoppingList/templates/sections/public_auth_card.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/public-auth.js").read_text(encoding="utf-8")
    assert 'autocomplete="email"' in template
    assert 'autocomplete="current-password"' in template
    assert ".reset(" not in script
    assert "form.reset" not in script


def test_legal_pages_reuse_light_and_dark_public_theme_and_responsive_contract(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        terms = client.get("/terms").get_data(as_text=True)
        privacy = client.get("/privacy").get_data(as_text=True)

    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    theme_head = (ROOT / "PushShoppingList/templates/includes/public_theme_head.html").read_text(encoding="utf-8")
    legal_template = (ROOT / "PushShoppingList/templates/legal_page.html").read_text(encoding="utf-8")

    for html in (terms, privacy):
        assert 'data-public-theme-menu' in html
        assert 'data-public-theme-trigger' in html
        assert 'role="menu"' in html
        assert 'data-public-theme-option="light"' in html
        assert 'data-public-theme-option="dark"' in html
        assert 'localStorage.getItem("ai-pantry-public-theme")' in html

    assert 'html[data-public-auth-theme="light"]' in css
    assert 'html[data-public-auth-theme="dark"]' in css
    assert ".public-legal-main" in css
    assert "width: min(960px, calc(100% - 56px));" in css
    assert "scroll-margin-top: 104px;" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "document.documentElement.dataset.publicAuthTheme = theme;" in theme_head
    assert '<main class="public-legal-main"' in legal_template
    assert '<article class="public-legal-article">' in legal_template
    assert '<nav class="public-legal-toc"' in legal_template
    assert '<section class="public-legal-section"' in legal_template
    assert '<footer class="public-auth-footer public-legal-footer"' in legal_template


def test_unresolved_governing_law_is_explicitly_marked_for_production_review():
    content = (ROOT / "PushShoppingList/services/legal_content.py").read_text(encoding="utf-8")
    assert len(LEGAL_DOCUMENTS["terms"]["sections"]) == 20
    assert len(LEGAL_DOCUMENTS["privacy"]["sections"]) == 18
    assert "GOVERNING_JURISDICTION = None" in content
    assert "TODO: Finalize with business owner and legal counsel before production launch." in content
