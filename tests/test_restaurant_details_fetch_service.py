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
    assert calls == ["https://example.com", "https://example.com/menu"]
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
