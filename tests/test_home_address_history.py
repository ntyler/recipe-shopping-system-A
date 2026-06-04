from flask import render_template

from PushShoppingList.app import create_app
from PushShoppingList.services import home_address_service
from PushShoppingList.services import storage_service


def configure_legacy_home_data(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "LEGACY_EXTRACTOR_DIR", tmp_path / "legacy-extractor")


def test_save_home_address_records_recent_history(monkeypatch, tmp_path):
    configure_legacy_home_data(monkeypatch, tmp_path)

    saved = home_address_service.save_home_address({
        "address_street": "1701 East College Avenue",
        "address_city": "Bloomington",
        "address_county": "McLean County",
        "address_state": "IL",
        "address_zip": "61704",
        "address_country": "United States",
    })
    history = home_address_service.load_home_address_history()

    assert history[0]["full_address"] == saved["full_address"]
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
    assert "1701 East College Avenue, Bloomington" in html
