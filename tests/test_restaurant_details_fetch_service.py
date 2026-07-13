import json
from pathlib import Path

from PushShoppingList.services import restaurant_details_fetch_service as service
from PushShoppingList.services import restaurant_hours_service


FIXTURES = Path(__file__).parent / "fixtures"


def restaurant_html():
    payload = {
        "@context": "https://schema.org",
        "@type": "Restaurant",
        "name": "Pisco Mar",
        "telephone": "(317) 537-2025",
        "logo": "/assets/pisco-mar-logo.png",
        "businessStatus": "https://schema.org/TemporarilyClosed",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "9546 Allisonville Rd",
            "addressLocality": "Indianapolis",
            "addressRegion": "IN",
            "postalCode": "46250",
            "addressCountry": "US",
        },
        "openingHoursSpecification": [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": ["Monday", "Tuesday"],
                "opens": "11:00",
                "closes": "14:00",
            },
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": "Monday",
                "opens": "17:00",
                "closes": "21:00",
            },
        ],
        "potentialAction": {"@type": "OrderAction", "target": "/order"},
    }
    return f"""
        <html><head><script type="application/ld+json">{json.dumps(payload)}</script></head>
        <body>We offer delivery. Holiday hours may vary. Join our rewards program for member discounts.</body></html>
    """


def restaurant_ordering_html():
    payload = {
        "@context": "https://schema.org",
        "@type": "Restaurant",
        "name": "Pisco Mar",
        "telephone": "(317) 537-2025",
        "potentialAction": {
            "@type": "OrderAction",
            "target": "https://pisco.example/order?utm_source=menu",
        },
    }
    return f"""
        <html><head><script type="application/ld+json">{json.dumps(payload)}</script></head><body>
          <nav>
            <a href="/pickup?utm_campaign=spring">Pickup online</a>
            <a href="https://www.doordash.com/store/pisco-mar-indianapolis/?utm_source=site">DoorDash delivery</a>
            <a href="https://www.grubhub.com/restaurant/pisco-mar-9546-allisonville-rd">Grubhub</a>
            <a href="https://www.ubereats.com/store/pisco-mar/branch-123">Uber Eats</a>
            <a href="https://order.toasttab.com/online/pisco-mar-indianapolis">Order with Toast</a>
            <a href="https://www.doordash.com/">Generic DoorDash home</a>
            <a href="https://www.grubhub.com/search?query=pisco">Provider search</a>
          </nav>
        </body></html>
    """


def test_extract_restaurant_proposals_from_public_structured_data():
    proposals = service.extract_restaurant_proposals(
        restaurant_html(),
        "https://example.com/restaurant",
    )

    assert proposals["weekly_hours"]["value"]["monday"] == {
        "closed": False,
        "ranges": [
            {"opens": "11:00", "closes": "14:00"},
            {"opens": "17:00", "closes": "21:00"},
        ],
    }
    assert proposals["hours_notes"]["found"] is True
    assert proposals["rewards_promotions"]["found"] is True
    assert proposals["image_url"]["value"] == "https://example.com/assets/pisco-mar-logo.png"
    assert proposals["current_status"]["value"] == "temporarily_closed"
    assert proposals["online_payment"]["found"] is False
    assert proposals["delivery"]["value"] == "true"
    assert proposals["phone"]["value"] == "(317) 537-2025"
    assert proposals["city"]["value"] == "Indianapolis"


def test_extracts_classified_ordering_links_and_separate_service_status_evidence():
    result = service.extract_restaurant_candidates(
        restaurant_ordering_html(),
        "https://pisco.example/restaurant",
        source_type="official_website",
        record={"restaurant_name": "Pisco Mar", "phone": "(317) 537-2025"},
        retrieved_at="2026-07-13T12:00:00Z",
    )
    ordering = [item for item in result["candidates"] if item["field"] == "ordering_link"]
    links = {item["normalized_value"]["provider"]: item["normalized_value"] for item in ordering}

    assert {"official_online_ordering", "doordash", "grubhub", "uber_eats", "toast"} <= set(links)
    assert {
        item["normalized_value"]["url"] for item in ordering
        if item["normalized_value"]["provider"] == "official_online_ordering"
    } == {"https://pisco.example/order", "https://pisco.example/pickup"}
    assert links["doordash"]["url"] == "https://www.doordash.com/store/pisco-mar-indianapolis"
    assert all(item["is_active"] is True for item in links.values())
    assert not any(item["normalized_value"]["url"] == "https://www.doordash.com/" for item in ordering)
    assert not any("/search" in item["normalized_value"]["url"] for item in ordering)
    assert any(item["field"] == "online_ordering" and item["normalized_value"] is True for item in result["candidates"])
    assert any(item["field"] == "pickup" and item["normalized_value"] is True for item in result["candidates"])
    assert any(item["field"] == "delivery" and item["normalized_value"] is True for item in result["candidates"])
    assert not any(item["field"] == "online_payment" for item in result["candidates"])


def test_scan_returns_individual_ordering_rows_and_unresolved_provider_entries(monkeypatch):
    monkeypatch.setattr(
        service,
        "fetch_public_restaurant_page",
        lambda url: (restaurant_ordering_html(), {
            "url": url, "fetched_at": "2026-07-13T12:00:00Z", "http_status": 200,
        }),
    )
    result = service.scan_restaurant_information({
        "restaurant_id": "restaurant-1",
        "restaurant_name": "Pisco Mar",
        "phone": "(317) 537-2025",
        "restaurant_website_url": "https://pisco.example/restaurant",
    })

    rows = result["ordering_link_recommendations"]
    providers = {row["recommended"]["normalized_value"]["provider"] for row in rows}
    assert {"official_online_ordering", "doordash", "grubhub", "uber_eats", "toast"} <= providers
    assert all(row["row_key"].startswith("ordering_link:candidate_") for row in rows)
    assert "ordering_provider_urls" not in result["fields"]
    assert "ordering_providers" not in result["fields"]
    assert result["summary"]["fields_discovered"] >= len(rows)
    assert {item["provider"] for item in result["unresolved_ordering_providers"]} == set()


def test_scan_lists_core_ordering_providers_as_unresolved_without_guessing(monkeypatch):
    monkeypatch.setattr(
        service,
        "fetch_public_restaurant_page",
        lambda url: ('<script type="application/ld+json">{"@type":"Restaurant","name":"Pisco Mar"}</script>', {
            "url": url, "fetched_at": "2026-07-13T12:00:00Z", "http_status": 200,
        }),
    )
    result = service.scan_restaurant_information({
        "restaurant_id": "restaurant-1",
        "restaurant_name": "Pisco Mar",
        "restaurant_website_url": "https://pisco.example",
    })

    unresolved = {item["label"]: item["reason"] for item in result["unresolved_ordering_providers"]}
    assert set(unresolved) == {"Official Online Ordering", "DoorDash", "Grubhub", "Uber Eats"}
    assert set(unresolved.values()) == {"No reliable source value found."}


def test_fetch_restaurant_details_uses_website_then_menu_and_does_not_mutate(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return restaurant_html(), {
            "url": url,
            "fetched_at": "2026-07-12T12:00:00Z",
            "http_status": 200,
        }

    monkeypatch.setattr(service, "fetch_public_restaurant_page", fake_fetch)
    record = {
        "restaurant_id": "restaurant-1",
        "restaurant_name": "Pisco Mar",
        "restaurant_website_url": "https://example.com",
        "source_menu_url": "https://example.com/menu",
        "phone": "saved-value",
    }
    original = dict(record)

    result = service.fetch_restaurant_details(record)

    assert result["ok"] is True
    assert result["restaurant_id"] == "restaurant-1"
    assert set(calls) == {"https://example.com", "https://example.com/menu"}
    assert record == original
    assert result["proposals"]["phone"]["value"] == "(317) 537-2025"


def test_fetch_restaurant_details_reports_missing_urls_without_guessing():
    result = service.fetch_restaurant_details({"restaurant_id": "restaurant-1"})

    assert result == {
        "ok": False,
        "code": "missing_urls",
        "error": "Add a Website URL or Menu URL before fetching details.",
        "restaurant_id": "restaurant-1",
    }


def test_fetch_restaurant_details_preserves_unknown_for_missing_boolean_fields(monkeypatch):
    monkeypatch.setattr(
        service,
        "fetch_public_restaurant_page",
        lambda url: (
            '<script type="application/ld+json">{"@type":"Restaurant","telephone":"555-0100"}</script>',
            {"url": url, "fetched_at": "2026-07-12T12:00:00Z", "http_status": 200},
        ),
    )

    result = service.fetch_restaurant_details({
        "restaurant_id": "restaurant-1",
        "restaurant_website_url": "https://example.com",
    })

    assert result["ok"] is True
    assert result["proposals"]["online_payment"]["found"] is False
    assert result["proposals"]["online_payment"]["value"] is None
    assert result["proposals"]["delivery"]["found"] is False
    assert result["proposals"]["delivery"]["value"] is None


def test_fetch_restaurant_details_returns_partial_results(monkeypatch):
    def fake_fetch(url):
        if url.endswith("/menu"):
            raise service.RestaurantFetchError("blocked", "The restaurant website blocked automated access.")
        return restaurant_html(), {"url": url, "fetched_at": "now", "http_status": 200}

    monkeypatch.setattr(service, "fetch_public_restaurant_page", fake_fetch)

    result = service.fetch_restaurant_details({
        "restaurant_id": "restaurant-1",
        "restaurant_website_url": "https://example.com",
        "source_menu_url": "https://example.com/menu",
    })

    assert result["ok"] is True
    assert result["partial"] is True
    assert result["errors"][0]["code"] == "blocked"


def test_unparsed_public_hours_are_reviewable_raw_data():
    html = """
        <script type="application/ld+json">
        {"@type":"Restaurant","openingHours":"Call for today's seasonal service times"}
        </script>
    """

    proposals = service.extract_restaurant_proposals(html, "https://example.com")

    assert proposals["weekly_hours"]["found"] is False
    assert proposals["raw_hours_text"]["value"] == "Call for today's seasonal service times"
    assert proposals["raw_hours_text"]["confidence"] == 0.55


def test_public_url_validation_blocks_private_targets(monkeypatch):
    monkeypatch.setattr(
        service.socket,
        "getaddrinfo",
        lambda *args: [(service.socket.AF_INET, service.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )

    try:
        service._public_http_url("https://example.com")
    except service.RestaurantFetchError as exc:
        assert exc.code == "blocked_url"
    else:
        raise AssertionError("Private targets must be rejected")


def candidate(field, value, candidate_id, confidence=0.95, source_url="https://example.com"):
    return {
        "field": field,
        "value": value,
        "normalized_value": service._normalize_value(field, value),
        "candidate_id": candidate_id,
        "confidence": confidence,
        "source_url": source_url,
        "source_type": "official_website",
        "extraction_method": "json_ld",
        "retrieved_at": "2026-07-12T12:00:00Z",
        "evidence": "Structured test evidence",
    }


def scan_field(field, current, candidates, **overrides):
    recommended = candidates[0]
    return {
        "field": field,
        "current_value": current,
        "current_normalized_value": service._normalize_value(field, current),
        "candidates": candidates,
        "recommended": recommended,
        "conflict": len({service._normalized_key(item["normalized_value"]) for item in candidates}) > 1,
        "changed": service._normalized_key(recommended["normalized_value"]) != service._normalized_key(service._normalize_value(field, current)),
        "locked": False,
        "requires_explicit_review": False,
        "selectable": True,
        "confidence_label": "High",
        **overrides,
    }


def test_scan_reconciliation_recognizes_edit_form_aliases_as_current_values():
    record = {
        "restaurant_latitude": "39.7684",
        "restaurant_longitude": "-86.1581",
        "restaurant_rating_count": "224",
        "restaurant_rewards_program": "Member rewards",
        "restaurant_active_promotions": ["Lunch special"],
        "restaurant_social_urls": ["https://instagram.com/piscomar"],
    }
    values = {
        "latitude": 39.7684,
        "longitude": -86.1581,
        "rating_count": 224,
        "rewards_promotions": "Member rewards",
        "promotions": ["Lunch special"],
        "social_urls": ["https://instagram.com/piscomar"],
    }

    for field, value in values.items():
        reconciled = service._reconcile_field(
            field,
            [candidate(field, value, f"{field}-candidate")],
            record,
            set(),
        )
        assert reconciled["status"] == "already_saved"
        assert reconciled["changed"] is False


def test_open_24_hours_and_multi_period_hours_are_normalized():
    weekly = service._hours_from_specs([
        {"dayOfWeek": "Monday", "opens": "00:00", "closes": "24:00"},
        {"dayOfWeek": "Tuesday", "opens": "11:00", "closes": "14:00"},
        {"dayOfWeek": "Tuesday", "opens": "17:00", "closes": "21:00"},
    ])

    assert weekly["monday"]["open_24_hours"] is True
    assert weekly["monday"]["ranges"] == [{"opens": "00:00", "closes": "24:00"}]
    assert weekly["tuesday"]["ranges"] == [
        {"opens": "11:00", "closes": "14:00"},
        {"opens": "17:00", "closes": "21:00"},
    ]


def test_fromtherestaurant_nested_edit_url_is_decoded_and_separated():
    nested = (
        "http://127.0.0.1:5083/recipe/edit?url="
        "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/"
        "?category%3D1%26menu_item%3Dmenu-item-1-Papa_Potatoe_a_la_Huancaina"
    )

    result = service.fromtherestaurant_source_urls(nested)

    assert result["menu_url"] == "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/"
    assert result["menu_item_url"] == (
        "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/"
        "?category=1&menu_item=menu-item-1-Papa_Potatoe_a_la_Huancaina"
    )


def test_fromtherestaurant_provider_detection_and_footer_extraction(caplog):
    html = (FIXTURES / "fromtherestaurant_menu.html").read_text(encoding="utf-8")
    url = "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/"
    caplog.set_level("DEBUG", logger=service.__name__)

    result = service.parse_fromtherestaurant_menu_page(
        html,
        url,
        record={"restaurant_name": "Pisco Mar", "restaurant_phone": "+13175372025"},
        retrieved_at="2026-07-12T12:00:00Z",
    )
    fields = {candidate["field"]: candidate for candidate in result["candidates"]}

    assert result["detected"] is True
    assert result["matched"] is True
    assert fields["restaurant_name"]["value"] == "Pisco Mar"
    assert fields["phone"]["value"] == "(317) 537-2025"
    assert fields["phone"]["normalized_value"] == "+13175372025"
    assert fields["phone"]["original_display_value"] == "(317) 537-2025"
    assert fields["street_address"]["value"] == "9546 Allisonville Rd"
    assert fields["city"]["value"] == "Indianapolis"
    assert fields["state_or_region"]["value"] == "IN"
    assert fields["postal_code"]["value"] == "46250"
    assert fields["country"]["value"] == "US"
    assert len(fields["weekly_hours"]["value"]) == 7
    assert fields["weekly_hours"]["value"]["sunday"]["ranges"] == [{"opens": "11:00", "closes": "20:00"}]
    assert fields["raw_hours_text"]["value"].splitlines()[0] == "Sun 11:00 am - 8:00 pm"
    assert fields["online_ordering"]["normalized_value"] is False
    assert "online_payment" not in fields
    assert fields["ordering_providers"]["value"] == [{
        "provider_name": "FOX Ordering",
        "provider_type": "ordering_provider",
        "website_url": "https://foxordering.com",
        "source_url": url,
    }]
    assert fields["allergy_information_note"]["value"] == "Please call for allergy information."
    assert fields["restaurant_note"]["value"] == "Please call for allergy information."
    assert "hours_notes" not in fields
    assert all(candidate["source_type"] == "official_menu_page" for candidate in fields.values())
    assert all(candidate["extraction_method"] == "provider_specific_html_parser" for candidate in fields.values())
    assert "provider detected" in caplog.text
    assert "weekday hour lines extracted=7" in caplog.text


def test_fromtherestaurant_equivalent_menu_phone_and_address_are_no_change(monkeypatch):
    html = (FIXTURES / "fromtherestaurant_menu.html").read_text(encoding="utf-8")
    monkeypatch.setattr(service, "fetch_public_restaurant_page", lambda url, force=False: (
        html,
        {"url": url, "retrieved_at": "2026-07-12T12:00:00Z", "http_status": 200},
    ))
    result = service.scan_restaurant_information({
        "restaurant_id": "restaurant-1",
        "restaurant_name": "pisco  mar",
        "restaurant_phone": "+1 (317) 537-2025",
        "restaurant_website_url": "https://fromtherestaurant.com",
        "source_menu_url": "HTTPS://FROMTHERESTAURANT.COM//pisco-mar/menu/9546-Allisonville-Rd/?category=1",
        "restaurant_street_address": "9546  Allisonville Rd",
        "restaurant_city": "INDIANAPOLIS",
        "restaurant_state": "in",
        "restaurant_postal_code": "46250",
        "restaurant_country": "us",
    })

    for field in ("restaurant_name", "menu_url", "phone", "street_address", "city", "state_or_region", "postal_code", "country"):
        assert result["fields"][field]["changed"] is False
        assert result["fields"][field]["conflict"] is False
    assert result["fields"]["online_ordering"]["changed"] is True
    assert result["fields"]["online_ordering"]["recommended"]["normalized_value"] is False
    assert result["summary"]["conflicts"] == 0
    assert "website_url" in result["unresolved_fields"]
    assert all(field not in result["unresolved_fields"] for field in (
        "phone", "street_address", "city", "state_or_region", "postal_code", "country", "weekly_hours", "raw_hours_text",
    ))
    platform = next(source for source in result["sources"] if source["source_type"] == "platform_website")
    assert "misclassified platform URL" in platform["classification_warning"]


def test_fromtherestaurant_partial_footer_and_layout_variation():
    html = """
    <html><body><div role="region" aria-label="Hours and business information">
      <strong>FromTheRestaurant</strong><a href="https://foxordering.com">FOX Ordering</a>
      <address aria-label="Business name and address"><span id="foxBusinessName"><strong>Cafe Uno</strong></span>
      <span>12 Main St<br>Fort Wayne IN 46802</span></address>
      <div aria-label="Hours">
        <div>Sunday Closed</div><div>Monday Open 24 Hours</div>
        <div>Tuesday 11 am - 2 pm, 5 pm - 9 pm</div>
      </div>
    </div></body></html>
    """
    result = service.parse_fromtherestaurant_menu_page(
        html,
        "https://fromtherestaurant.com/cafe-uno/menu/12-Main-St/",
        record={"restaurant_name": "Cafe Uno"},
    )
    fields = {candidate["field"]: candidate["value"] for candidate in result["candidates"]}

    assert fields["street_address"] == "12 Main St"
    assert "phone" not in fields
    assert fields["weekly_hours"]["sunday"]["closed"] is True
    assert fields["weekly_hours"]["monday"]["open_24_hours"] is True
    assert fields["weekly_hours"]["tuesday"]["ranges"] == [
        {"opens": "11:00", "closes": "14:00"},
        {"opens": "17:00", "closes": "21:00"},
    ]


def test_fromtherestaurant_missing_footer_falls_back_to_json_ld():
    html = """
    <html><body><strong>FromTheRestaurant</strong><a href="https://foxordering.com">FOX Ordering</a>
    <script type="application/ld+json">{"@type":"Restaurant","name":"Cafe Uno","telephone":"260-555-0100"}</script>
    </body></html>
    """
    result = service.extract_restaurant_candidates(
        html,
        "https://fromtherestaurant.com/cafe-uno/menu/12-Main-St/",
        record={"restaurant_name": "Cafe Uno"},
    )
    fields = {candidate["field"]: candidate for candidate in result["candidates"]}

    assert result["matched"] is True
    assert fields["phone"]["normalized_value"] == "+12605550100"
    assert fields["phone"]["extraction_method"] == "json_ld"


def test_non_menu_fromtherestaurant_url_is_platform_source_not_official_website():
    sources = service._discovery_sources({"restaurant_website_url": "https://fromtherestaurant.com"})

    assert sources == [{
        "url": "https://fromtherestaurant.com",
        "source_type": "platform_website",
        "label": "FromTheRestaurant platform website",
        "classification_warning": "Possible misclassified platform URL; not treated as the restaurant's official website.",
    }]


def test_same_name_different_location_is_rejected():
    html = """
    <script type="application/ld+json">
    {"@type":"Restaurant","name":"Pisco Mar","telephone":"212-555-9999",
     "address":{"streetAddress":"1 Broadway","addressLocality":"New York","postalCode":"10001"}}
    </script>
    """
    result = service.extract_restaurant_candidates(html, "https://example.com", record={
        "restaurant_name": "Pisco Mar", "phone": "317-537-2025",
        "address_line": "9546 Allisonville Rd", "city": "Indianapolis", "postal_code": "46250",
    })

    assert result["matched"] is False
    assert result["candidates"] == []


def test_multi_location_page_selects_matching_location():
    payload = {"@context": "https://schema.org", "@graph": [
        {"@type": "Restaurant", "name": "Pisco Mar", "telephone": "212-555-9999", "address": {"streetAddress": "1 Broadway", "addressLocality": "New York"}},
        {"@type": "Restaurant", "name": "Pisco Mar", "telephone": "317-537-2025", "address": {"streetAddress": "9546 Allisonville Rd", "addressLocality": "Indianapolis", "postalCode": "46250"}},
    ]}
    result = service.extract_restaurant_candidates(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>',
        "https://example.com/locations",
        record={"restaurant_name": "Pisco Mar", "phone": "317-537-2025", "postal_code": "46250"},
    )
    phone = next(item for item in result["candidates"] if item["field"] == "phone")

    assert result["matched"] is True
    assert phone["value"] == "317-537-2025"


def test_conflicting_sources_are_retained_for_review(monkeypatch):
    def fake_fetch(url, force=False):
        phone = "317-537-2025" if url.endswith("official") else "317-555-0100"
        html = f'<script type="application/ld+json">{{"@type":"Restaurant","name":"Pisco Mar","telephone":"{phone}"}}</script>'
        return html, {"url": url, "retrieved_at": "2026-07-12T12:00:00Z", "http_status": 200}

    monkeypatch.setattr(service, "fetch_public_restaurant_page", fake_fetch)
    result = service.scan_restaurant_information({
        "restaurant_id": "restaurant-1", "restaurant_name": "Pisco Mar",
        "restaurant_website_url": "https://example.com/official", "source_menu_url": "https://example.com/menu",
    })

    assert result["fields"]["phone"]["conflict"] is True
    assert len(result["fields"]["phone"]["candidates"]) == 2
    assert result["fields"]["phone"]["confidence_label"] == "Conflict"


def test_empty_scan_result_is_successful_and_lists_unresolved_fields(monkeypatch):
    monkeypatch.setattr(service, "fetch_public_restaurant_page", lambda url, force=False: ("<html><body>Welcome</body></html>", {"url": url, "retrieved_at": "now"}))

    result = service.scan_restaurant_information({"restaurant_id": "restaurant-1", "restaurant_website_url": "https://example.com"})

    assert result["ok"] is True
    assert result["fields"] == {}
    assert result["summary"]["fields_discovered"] == 0
    assert "phone" in result["unresolved_fields"]


def test_apply_selected_and_high_confidence_respect_locks_conflicts_and_unchanged_values():
    phone = candidate("phone", "317-537-2025", "phone-1")
    city = candidate("city", "Indianapolis", "city-1")
    logo = candidate("image_url", "https://example.com/logo.png", "logo-1")
    conflicting = [candidate("delivery", True, "delivery-1"), candidate("delivery", False, "delivery-2")]
    scan = {"fields": {
        "phone": scan_field("phone", "", [phone]),
        "city": scan_field("city", "Indianapolis", [city], changed=False),
        "image_url": scan_field("image_url", "https://old.example/logo.png", [logo], requires_explicit_review=True),
        "delivery": scan_field("delivery", None, conflicting, conflict=True, confidence_label="Conflict"),
    }}

    selected = service.select_restaurant_scan_values(scan, selections={"image_url": "logo-1", "delivery": "delivery-1"})
    automatic = service.select_restaurant_scan_values(scan, mode="high_confidence", locked_fields={"phone"})

    assert selected["values"] == {"image_url": "https://example.com/logo.png", "delivery": True}
    assert automatic["values"] == {}
    assert {item["reason"] for item in automatic["rejected"]} == {"locked", "empty_or_unchanged"}


def test_apply_rejects_unknown_mode_before_writing():
    result = service.apply_restaurant_information_scan(
        "restaurant-1",
        {"restaurant_id": "restaurant-1", "fields": {}},
        mode="automatic",
    )

    assert result == {"ok": False, "error": "The restaurant information apply mode is invalid."}


def test_logo_candidate_rejects_menu_screenshot_and_food_photo():
    payload = {"@type": "Restaurant", "name": "Pisco Mar", "logo": "/images/menu-screenshot.jpg", "image": "/images/food-photo.jpg"}
    result = service.extract_restaurant_candidates(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>', "https://example.com"
    )

    assert not any(item["field"] == "image_url" for item in result["candidates"])


def test_logo_candidate_rejects_generic_placeholder_even_when_structured():
    payload = {"@type": "Restaurant", "name": "Pisco Mar", "logo": "/images/default-image-placeholder.png"}
    result = service.extract_restaurant_candidates(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>', "https://example.com"
    )

    assert not any(item["field"] == "image_url" for item in result["candidates"])


def test_header_logo_is_ranked_above_favicon_and_keeps_asset_metadata(monkeypatch):
    html = """
    <html><head><link rel="icon" href="/favicon.png"></head>
    <body><header><img src="/assets/pisco-mar-logo.svg" alt="Pisco Mar logo" width="240" height="120"></header></body></html>
    """
    extracted = service.extract_restaurant_candidates(html, "https://example.com", record={})
    logos = [item for item in extracted["candidates"] if item["field"] == "image_url"]

    assert len(logos) == 2
    header = max(logos, key=lambda item: item["confidence"])
    favicon = min(logos, key=lambda item: item["confidence"])
    assert header["value"] == "https://example.com/assets/pisco-mar-logo.svg"
    assert header["image_format"] == "svg"
    assert (header["width"], header["height"]) == (240, 120)
    assert favicon["fallback"] is True
    assert header["confidence"] > favicon["confidence"]


def test_favicon_only_scan_keeps_logo_unresolved(monkeypatch):
    monkeypatch.setattr(
        service,
        "fetch_public_restaurant_page",
        lambda url, force=False: (
            '<html><head><link rel="icon" href="/favicon.png"></head><body>Pisco Mar</body></html>',
            {"url": url, "retrieved_at": "2026-07-12T12:00:00Z", "http_status": 200},
        ),
    )
    result = service.scan_restaurant_information({
        "restaurant_id": "restaurant-1",
        "restaurant_name": "Pisco Mar",
        "restaurant_website_url": "https://example.com",
    })

    assert result["fields"]["image_url"]["recommended"]["fallback"] is True
    assert "image_url" in result["unresolved_fields"]


def test_explicit_structured_false_boolean_is_preserved_without_inventing_unknown_values():
    payload = {
        "@type": "Restaurant",
        "name": "Pisco Mar",
        "deliveryAvailable": False,
        "takeoutAvailable": "true",
    }
    extracted = service.extract_restaurant_candidates(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>',
        "https://example.com",
    )
    by_field = {item["field"]: item["normalized_value"] for item in extracted["candidates"]}

    assert by_field["delivery"] is False
    assert by_field["pickup"] is True
    assert "online_payment" not in by_field


def test_apply_transaction_rolls_back_when_store_save_fails(monkeypatch, tmp_path):
    store_path = tmp_path / "restaurant_menus.json"
    original = {"restaurants": [{"id": "restaurant-1", "restaurant_id": "restaurant-1", "restaurant_name": "Pisco Mar", "phone": "old"}], "menus": [], "sections": [], "items": [], "pdf_logs": []}
    store_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(service.menu_store_service, "MENU_STORE_FILE", store_path)
    scan = {
        "ok": True, "restaurant_id": "restaurant-1", "scan_id": "scan-1", "scanned_at": "now", "summary": {},
        "fields": {"phone": scan_field("phone", "old", [candidate("phone", "317-537-2025", "phone-1")])},
    }
    monkeypatch.setattr(service.menu_store_service, "save_menu_store", lambda _store: (_ for _ in ()).throw(RuntimeError("disk failure")))

    result = service.apply_restaurant_information_scan("restaurant-1", scan, selections={"phone": "phone-1"})

    assert result["ok"] is False
    assert "rolled back" in result["error"]
    assert json.loads(store_path.read_text(encoding="utf-8")) == original


def test_apply_selected_persists_audit_locks_and_approved_logo_attribution(monkeypatch, tmp_path):
    store_path = tmp_path / "restaurant_menus.json"
    store = {"restaurants": [{"id": "restaurant-1", "restaurant_id": "restaurant-1", "restaurant_name": "Pisco Mar", "phone": "old", "logo_url": "/old-logo.png"}], "menus": [], "sections": [], "items": [], "pdf_logs": []}
    store_path.write_text(json.dumps(store), encoding="utf-8")
    monkeypatch.setattr(service.menu_store_service, "MENU_STORE_FILE", store_path)
    monkeypatch.setattr(service, "active_user_id", lambda: "user-42")
    monkeypatch.setattr(service, "_store_approved_logo", lambda candidate, restaurant_id: {
        "logo_url": f"/restaurant_source_logo?restaurant_id={restaurant_id}",
        "logo_path": str(tmp_path / "logo.png"),
        "logo_thumbnail_path": str(tmp_path / "logo_thumb.webp"),
        "original_url": candidate["value"],
    })
    phone = candidate("phone", "317-537-2025", "phone-1")
    logo = candidate("image_url", "https://example.com/brand/logo.png", "logo-1")
    scan = {
        "ok": True, "restaurant_id": "restaurant-1", "scan_id": "scan-1", "scanned_at": "2026-07-12T12:00:00Z", "summary": {},
        "fields": {
            "phone": scan_field("phone", "old", [phone]),
            "image_url": scan_field("image_url", "/old-logo.png", [logo], requires_explicit_review=True),
        },
    }

    result = service.apply_restaurant_information_scan(
        "restaurant-1", scan, selections={"phone": "phone-1", "image_url": "logo-1"}, lock_updates={"city": True}
    )
    saved = json.loads(store_path.read_text(encoding="utf-8"))["restaurants"][0]

    assert result["ok"] is True
    assert set(result["applied_fields"]) == {"phone", "image_url"}
    assert saved["phone"] == "317-537-2025"
    assert saved["logo_original_source_url"] == "https://example.com/brand/logo.png"
    assert saved["logo_source_page_url"] == "https://example.com"
    assert saved["restaurant_information_locked_fields"] == ["city"]
    audit = saved["restaurant_information_audit"][0]
    assert audit["user_id"] == "user-42"
    assert {change["field"] for change in audit["changes"]} == {"phone", "image_url"}


def test_apply_selected_persists_structured_ordering_provider_and_restaurant_notes(monkeypatch, tmp_path):
    store_path = tmp_path / "restaurant_menus.json"
    store = {"restaurants": [{"id": "restaurant-1", "restaurant_id": "restaurant-1", "restaurant_name": "Pisco Mar"}], "menus": [], "sections": [], "items": [], "pdf_logs": []}
    store_path.write_text(json.dumps(store), encoding="utf-8")
    monkeypatch.setattr(service.menu_store_service, "MENU_STORE_FILE", store_path)
    provider_value = [{
        "provider_name": "FOX Ordering",
        "provider_type": "ordering_provider",
        "website_url": "https://foxordering.com",
        "source_url": "https://fromtherestaurant.com/pisco-mar/menu/9546-Allisonville-Rd/",
    }]
    provider = candidate("ordering_providers", provider_value, "provider-1")
    allergy = candidate("allergy_information_note", "Please call for allergy information.", "allergy-1")
    ordering = candidate("online_ordering", False, "ordering-1")
    scan = {
        "ok": True,
        "restaurant_id": "restaurant-1",
        "scan_id": "scan-structured",
        "scanned_at": "2026-07-12T12:00:00Z",
        "summary": {},
        "fields": {
            "ordering_providers": scan_field("ordering_providers", [], [provider]),
            "allergy_information_note": scan_field("allergy_information_note", "", [allergy]),
            "online_ordering": scan_field("online_ordering", None, [ordering]),
        },
    }

    result = service.apply_restaurant_information_scan(
        "restaurant-1",
        scan,
        selections={
            "ordering_providers": "provider-1",
            "allergy_information_note": "allergy-1",
            "online_ordering": "ordering-1",
        },
    )
    saved = json.loads(store_path.read_text(encoding="utf-8"))["restaurants"][0]

    assert result["ok"] is True
    assert saved["ordering_providers"] == provider_value
    assert saved["allergy_information_note"] == "Please call for allergy information."
    assert saved["online_ordering_available"] is False


def test_staged_apply_adds_selected_ordering_link_and_requires_replace_for_conflict(monkeypatch, tmp_path):
    store_path = tmp_path / "restaurant_menus.json"
    existing = {
        "provider": "doordash",
        "url": "https://www.doordash.com/store/pisco-mar-old",
        "is_active": True,
    }
    store_path.write_text(json.dumps({
        "restaurants": [{
            "id": "restaurant-1",
            "restaurant_id": "restaurant-1",
            "restaurant_name": "Pisco Mar",
            "ordering_delivery_links": [existing],
        }],
        "menus": [], "sections": [], "items": [], "pdf_logs": [],
    }), encoding="utf-8")
    monkeypatch.setattr(service.menu_store_service, "MENU_STORE_FILE", store_path)
    discovered = service._candidate(
        "ordering_link",
        {
            "provider": "doordash",
            "provider_name": "DoorDash",
            "url": "https://www.doordash.com/store/pisco-mar-new",
            "is_active": True,
            "supports_online_ordering": True,
            "supports_pickup": False,
            "supports_delivery": True,
            "source_url": "https://pisco.example",
        },
        "https://pisco.example",
        "official_website",
        "navigation_link",
        0.98,
        "Official website DoorDash link",
        "2026-07-13T12:00:00Z",
    )
    row = service._reconcile_ordering_links(
        [discovered], {"ordering_delivery_links": [existing]}, set()
    )[0]
    scan = {
        "ok": True,
        "restaurant_id": "restaurant-1",
        "scan_id": "scan-ordering",
        "ordering_link_recommendations": [row],
        "fields": {},
    }

    kept = service.prepare_restaurant_information_scan_apply(
        "restaurant-1",
        scan,
        selections={row["row_key"]: discovered["candidate_id"]},
        ordering_link_resolutions={row["row_key"]: "keep"},
    )
    replaced = service.prepare_restaurant_information_scan_apply(
        "restaurant-1",
        scan,
        selections={row["row_key"]: discovered["candidate_id"]},
        ordering_link_resolutions={row["row_key"]: "replace"},
    )

    assert kept["applied_values"] == {}
    assert kept["rejected"] == [{"field": row["row_key"], "reason": "conflict_kept"}]
    assert replaced["applied_fields"] == [row["row_key"]]
    assert replaced["applied_values"]["ordering_providers"] == [{
        **discovered["normalized_value"],
        "replace_existing": True,
    }]
    assert json.loads(store_path.read_text(encoding="utf-8"))["restaurants"][0]["ordering_delivery_links"] == [existing]


def test_shared_hours_codec_canonicalizes_split_closed_and_open_24_hours():
    weekly, notes = restaurant_hours_service.parse_weekly_hours_text(
        "Monday: 00:00-24:00\n"
        "Tuesday: 11:00-14:00, 17:00-21:00\n"
        "Wednesday: Closed\n"
        "Notes: Kitchen closes early"
    )

    assert weekly["monday"] == {
        "closed": False,
        "open_24_hours": True,
        "ranges": [{"opens": "00:00", "closes": "24:00"}],
    }
    assert weekly["tuesday"]["ranges"] == [
        {"opens": "11:00", "closes": "14:00"},
        {"opens": "17:00", "closes": "21:00"},
    ]
    assert weekly["wednesday"] == {"closed": True, "ranges": []}
    assert notes == "Kitchen closes early"
    assert restaurant_hours_service.weekly_hours_to_text(weekly, notes).startswith("Monday: 00:00-24:00")


def test_reconcile_unchanged_hours_is_already_saved_and_not_explicit_review():
    weekly = service._hours_from_strings(["Monday 11:00 am - 9:00 pm"])
    row = service._reconcile_field(
        "weekly_hours",
        [candidate("weekly_hours", weekly, "hours-1")],
        {"weekly_hours": weekly},
        set(),
    )

    assert row["changed"] is False
    assert row["selectable"] is False
    assert row["requires_explicit_review"] is False
    assert row["status"] == "already_saved"


def test_staged_scan_apply_returns_normalized_values_without_mutating_store(monkeypatch, tmp_path):
    store_path = tmp_path / "restaurant_menus.json"
    original = {
        "restaurants": [{
            "id": "restaurant-1",
            "restaurant_id": "restaurant-1",
            "restaurant_name": "Pisco Mar",
            "weekly_hours": {},
            "online_ordering_available": None,
            "online_payment_available": None,
            "delivery_available": None,
        }],
        "menus": [], "sections": [], "items": [], "pdf_logs": [],
    }
    store_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(service.menu_store_service, "MENU_STORE_FILE", store_path)
    weekly = service._hours_from_strings(["Monday 11:00 am - 9:00 pm"])
    hours = candidate("weekly_hours", weekly, "hours-1")
    raw_hours = candidate("raw_hours_text", "Monday 11 am - 9 pm\nTuesday Closed", "raw-hours-1")
    ordering = candidate("online_ordering", False, "ordering-1")
    scan = {
        "restaurant_id": "restaurant-1",
        "fields": {
            "weekly_hours": scan_field("weekly_hours", {}, [hours]),
            "raw_hours_text": scan_field("raw_hours_text", "", [raw_hours]),
            "online_ordering": scan_field("online_ordering", None, [ordering]),
        },
    }

    result = service.prepare_restaurant_information_scan_apply(
        "restaurant-1",
        scan,
        selections={
            "weekly_hours": "hours-1",
            "raw_hours_text": "raw-hours-1",
            "online_ordering": "ordering-1",
        },
    )

    assert result["ok"] is True
    assert result["persisted"] is False
    assert result["applied_fields"] == ["weekly_hours", "raw_hours_text", "online_ordering"]
    assert result["applied_values"]["weekly_hours"] == weekly
    assert result["applied_values"]["raw_hours_text"] == "Monday 11 am - 9 pm\nTuesday Closed"
    assert result["applied_values"]["online_ordering"] is False
    assert result["field_statuses"] == {
        "weekly_hours": "applied",
        "raw_hours_text": "applied",
        "online_ordering": "applied",
    }
    assert json.loads(store_path.read_text(encoding="utf-8")) == original


def test_staged_high_confidence_apply_excludes_unchanged_conflict_medium_and_locked(monkeypatch, tmp_path):
    store_path = tmp_path / "restaurant_menus.json"
    store_path.write_text(json.dumps({
        "restaurants": [{"id": "restaurant-1", "restaurant_id": "restaurant-1"}],
        "menus": [], "sections": [], "items": [], "pdf_logs": [],
    }), encoding="utf-8")
    monkeypatch.setattr(service.menu_store_service, "MENU_STORE_FILE", store_path)
    phone = candidate("phone", "317-537-2025", "phone-1")
    scan = {"restaurant_id": "restaurant-1", "fields": {
        "phone": scan_field("phone", "317-537-2025", [phone], changed=False, selectable=False, status="already_saved"),
        "city": scan_field("city", "", [candidate("city", "Indianapolis", "city-1", confidence=0.7)], confidence_label="Medium"),
        "delivery": scan_field("delivery", None, [candidate("delivery", True, "delivery-1")], locked=True),
    }}

    result = service.prepare_restaurant_information_scan_apply(
        "restaurant-1", scan, mode="high_confidence"
    )

    assert result["ok"] is True
    assert result["applied_values"] == {}
    assert result["applied_fields"] == []


def test_order_action_does_not_imply_online_payment_without_explicit_evidence():
    payload = {
        "@type": "Restaurant",
        "name": "Pisco Mar",
        "potentialAction": {"@type": "OrderAction", "target": "https://orders.example.com/pisco"},
    }
    result = service.extract_restaurant_candidates(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>',
        "https://example.com",
    )
    fields = {item["field"]: item["normalized_value"] for item in result["candidates"]}

    assert fields["online_ordering"] is True
    assert "online_payment" not in fields
