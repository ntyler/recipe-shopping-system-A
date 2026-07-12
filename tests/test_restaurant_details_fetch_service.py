import json

from PushShoppingList.services import restaurant_details_fetch_service as service


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
    assert proposals["online_payment"]["value"] == "true"
    assert proposals["delivery"]["value"] == "true"
    assert proposals["phone"]["value"] == "(317) 537-2025"
    assert proposals["city"]["value"] == "Indianapolis"


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


def test_logo_candidate_rejects_menu_screenshot_and_food_photo():
    payload = {"@type": "Restaurant", "name": "Pisco Mar", "logo": "/images/menu-screenshot.jpg", "image": "/images/food-photo.jpg"}
    result = service.extract_restaurant_candidates(
        f'<script type="application/ld+json">{json.dumps(payload)}</script>', "https://example.com"
    )

    assert not any(item["field"] == "image_url" for item in result["candidates"])


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
