from flask import render_template

from PushShoppingList.app import create_app
from PushShoppingList.services import home_address_service
from PushShoppingList.services import storage_service


def configure_legacy_home_data(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "LEGACY_EXTRACTOR_DIR", tmp_path / "legacy-extractor")


def test_save_home_address_records_recent_history(monkeypatch, tmp_path):
    configure_legacy_home_data(monkeypatch, tmp_path)

    saved = home_address_service.save_home_address({
        "address_label": "Grandma's House",
        "address_street": "1701 East College Avenue",
        "address_city": "Bloomington",
        "address_county": "McLean County",
        "address_state": "IL",
        "address_zip": "61704",
        "address_country": "United States",
    })
    history = home_address_service.load_home_address_history()

    assert history[0]["full_address"] == saved["full_address"]
    assert history[0]["label"] == "Grandma's House"
    assert history[0]["id"]
    assert history[0]["street"] == "1701 East College Avenue"
    assert history[0]["saved_at"]
    assert history[0]["saved_at_display"]


def test_save_home_address_ajax_returns_history(monkeypatch, tmp_path):
    configure_legacy_home_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        response = client.post(
            "/save_home_address",
            data={
                "ajax": "1",
                "address_street": "1701 East College Avenue",
                "address_city": "Bloomington",
                "address_county": "McLean County",
                "address_state": "IL",
                "address_zip": "61704",
                "address_country": "United States",
            },
            headers={"X-Requested-With": "fetch"},
        )

    data = response.get_json()

    assert response.status_code == 200
    assert data["home_address_history"][0]["full_address"] == data["home_address"]["full_address"]


def test_home_address_history_label_and_delete_routes(monkeypatch, tmp_path):
    configure_legacy_home_data(monkeypatch, tmp_path)
    app = create_app()

    saved = home_address_service.save_home_address({
        "address_label": "Home",
        "address_street": "5905 Arlo Drive",
        "address_city": "Indianapolis",
        "address_state": "IN",
        "address_zip": "46237",
        "address_country": "United States",
    })
    entry_id = home_address_service.load_home_address_history()[0]["id"]

    with app.test_client() as client:
        label_response = client.post(
            f"/api/home_address_history/{entry_id}/label",
            json={"label": "Grandma's House"},
            headers={"X-Requested-With": "fetch"},
        )
        delete_response = client.post(
            f"/api/home_address_history/{entry_id}/delete",
            headers={"X-Requested-With": "fetch"},
        )

    label_data = label_response.get_json()
    delete_data = delete_response.get_json()

    assert saved["full_address"]
    assert label_response.status_code == 200
    assert label_data["home_address_history"][0]["label"] == "Grandma's House"
    assert delete_response.status_code == 200
    assert delete_data["home_address_history"] == []


def test_home_address_template_renders_history_panel():
    app = create_app()

    with app.test_request_context("/"):
        html = render_template(
            "sections/home_address.html",
            home_address={
                "street": "",
                "apartment": "",
                "city": "",
                "county": "",
                "state": "",
                "zip": "",
                "country": "",
                "full_address": "",
            },
            home_address_history=[
                {
                    "id": "address-1",
                    "label": "Home",
                    "street": "1701 East College Avenue",
                    "apartment": "",
                    "city": "Bloomington",
                    "county": "McLean County",
                    "state": "IL",
                    "zip": "61704",
                    "country": "United States",
                    "full_address": "1701 East College Avenue, Bloomington, McLean County, IL 61704, United States",
                    "saved_at": "2026-06-03T12:00:00+00:00",
                    "saved_at_display": "2026-06-03 12:00 UTC",
                }
            ],
        )

    assert "Home Address History" in html
    assert "data-home-address-history-list" in html
    assert "useHomeAddressHistoryEntry(this)" in html
    assert "saveHomeAddressHistoryTitle(this)" in html
    assert "removeHomeAddressHistoryEntry(this)" in html
    assert "Address title, e.g. Home" in html
    assert "Grandma" not in html
    assert "Home" in html
    assert "1701 East College Avenue, Bloomington" in html


def test_home_address_history_scripts_are_wired():
    script = open("PushShoppingList/static/js/app.js", encoding="utf-8").read()
    css = open("PushShoppingList/static/css/app.css", encoding="utf-8").read()

    assert "function saveHomeAddressHistoryTitle" in script
    assert "function removeHomeAddressHistoryEntry" in script
    assert "address_label" in script
    assert ".home-address-history-title-row" in css
    assert ".home-address-history-remove-btn" in css
