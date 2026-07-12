"""Fetch public restaurant metadata as reviewable, non-persistent proposals."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from PushShoppingList.services.recipe_extract_service import menu_page_request_headers


FETCH_TIMEOUT = (6, 16)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_ALIASES = {
    "mo": "monday", "mon": "monday", "monday": "monday",
    "tu": "tuesday", "tue": "tuesday", "tues": "tuesday", "tuesday": "tuesday",
    "we": "wednesday", "wed": "wednesday", "wednesday": "wednesday",
    "th": "thursday", "thu": "thursday", "thur": "thursday", "thurs": "thursday", "thursday": "thursday",
    "fr": "friday", "fri": "friday", "friday": "friday",
    "sa": "saturday", "sat": "saturday", "saturday": "saturday",
    "su": "sunday", "sun": "sunday", "sunday": "sunday",
}
PROPOSAL_FIELDS = (
    "weekly_hours", "raw_hours_text", "hours_notes", "rewards_promotions", "image_url", "current_status",
    "online_payment", "delivery", "phone", "street_address", "city", "state_or_region",
    "postal_code", "country",
)


class RestaurantFetchError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _public_http_url(value):
    url = _clean(value)
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise RestaurantFetchError("invalid_url", "The restaurant URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RestaurantFetchError("invalid_url", "The restaurant URL must use HTTP or HTTPS.")
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise RestaurantFetchError("blocked_url", "Private or local restaurant URLs cannot be fetched.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port)}
    except (socket.gaierror, ValueError) as exc:
        raise RestaurantFetchError("unreachable", "The restaurant website could not be reached.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise RestaurantFetchError("blocked_url", "Private or local restaurant URLs cannot be fetched.")
    return url


def fetch_public_restaurant_page(url):
    """Fetch bounded public HTML while validating every redirect target."""
    current = _public_http_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(
                current,
                headers=menu_page_request_headers(),
                timeout=FETCH_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise RestaurantFetchError("timeout", "The restaurant website request timed out.") from exc
        except requests.RequestException as exc:
            raise RestaurantFetchError("unreachable", "The restaurant website could not be reached.") from exc
        try:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RestaurantFetchError("blocked", "The restaurant website returned an invalid redirect.")
                current = _public_http_url(urljoin(current, location))
                continue
            if response.status_code in {401, 403, 429, 451}:
                raise RestaurantFetchError("blocked", "The restaurant website blocked automated access.")
            response.raise_for_status()
            content_type = _clean(response.headers.get("content-type")).casefold()
            if content_type and not any(kind in content_type for kind in ("html", "xhtml", "text/plain")):
                raise RestaurantFetchError("unsupported", "The restaurant URL did not return a webpage.")
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise RestaurantFetchError("too_large", "The restaurant webpage was too large to inspect safely.")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            html = b"".join(chunks).decode(encoding, errors="replace")
            return html, {
                "url": str(response.url or current),
                "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "http_status": response.status_code,
            }
        except requests.RequestException as exc:
            raise RestaurantFetchError("request_failed", "The restaurant website could not be fetched.") from exc
        finally:
            response.close()
    raise RestaurantFetchError("redirect_loop", "The restaurant website redirected too many times.")


def _json_ld_nodes(soup):
    nodes = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            nodes.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
    return nodes


def _type_names(node):
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {_clean(value).casefold() for value in values if _clean(value)}


def _restaurant_nodes(nodes, record=None):
    accepted = {"restaurant", "foodestablishment", "localbusiness", "organization"}
    record = record if isinstance(record, dict) else {}
    reference = _clean(" ".join(str(record.get(key) or "") for key in (
        "restaurant_name", "restaurant_street_address", "restaurant_city", "restaurant_state",
    ))).casefold()

    def rank(node):
        address = node.get("address") if isinstance(node.get("address"), dict) else {}
        candidate = _clean(" ".join(str(value or "") for value in (
            node.get("name"), address.get("streetAddress"), address.get("addressLocality"), address.get("addressRegion"),
        ))).casefold()
        overlap = len(set(reference.split()) & set(candidate.split())) if reference else 0
        return (0 if "restaurant" in _type_names(node) else 1, -overlap)

    return sorted(
        (node for node in nodes if _type_names(node) & accepted),
        key=rank,
    )


def _time_24(value):
    text = _clean(value)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        return ""
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{hour:02d}:{minute:02d}" if 0 <= hour <= 23 and 0 <= minute <= 59 else ""


def _day_key(value):
    token = _clean(value).split("/")[-1].casefold()
    return DAY_ALIASES.get(token, "")


def _days_between(first, last):
    try:
        start, end = WEEKDAYS.index(first), WEEKDAYS.index(last)
    except ValueError:
        return []
    return list(WEEKDAYS[start:end + 1]) if start <= end else list(WEEKDAYS[start:]) + list(WEEKDAYS[:end + 1])


def _append_hours_range(weekly, day, opens, closes):
    if not day:
        return
    entry = weekly.setdefault(day, {"closed": False, "ranges": []})
    if opens and closes and {"opens": opens, "closes": closes} not in entry["ranges"] and len(entry["ranges"]) < 2:
        entry["ranges"].append({"opens": opens, "closes": closes})


def _hours_from_specs(raw):
    specs = raw if isinstance(raw, list) else [raw]
    weekly = {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        days = spec.get("dayOfWeek")
        days = days if isinstance(days, list) else [days]
        opens, closes = _time_24(spec.get("opens")), _time_24(spec.get("closes"))
        for raw_day in days:
            day = _day_key(raw_day)
            if not day:
                continue
            if spec.get("validFrom") and spec.get("validThrough") and not opens and not closes:
                continue
            if opens and closes:
                _append_hours_range(weekly, day, opens, closes)
            elif _clean(spec.get("opens")).casefold() == "closed":
                weekly[day] = {"closed": True, "ranges": []}
    return weekly


def _hours_from_strings(raw):
    values = raw if isinstance(raw, list) else [raw]
    weekly = {}
    for value in values:
        text = _clean(value)
        match = re.match(r"([A-Za-z]+)(?:\s*-\s*([A-Za-z]+))?\s+(.+)$", text)
        if not match:
            continue
        first = _day_key(match.group(1))
        last = _day_key(match.group(2)) if match.group(2) else first
        days = _days_between(first, last) if first and last else []
        detail = match.group(3)
        if detail.casefold() == "closed":
            for day in days:
                weekly[day] = {"closed": True, "ranges": []}
            continue
        ranges = re.findall(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", detail)
        for day in days:
            for opens, closes in ranges[:2]:
                _append_hours_range(weekly, day, _time_24(opens), _time_24(closes))
    return weekly


def _proposal(value, confidence, source_url):
    found = value not in (None, "", [], {})
    return {
        "value": value if found else None,
        "found": found,
        "confidence": round(float(confidence), 2) if found else None,
        "source_url": source_url if found else "",
    }


def _first_url(value, base_url):
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    if isinstance(value, list):
        value = next((item for item in value if item), "")
        if isinstance(value, dict):
            value = value.get("url") or value.get("contentUrl")
    return urljoin(base_url, _clean(value)) if _clean(value) else ""


def _status(value):
    token = re.sub(r"[^a-z]+", "_", _clean(value).split("/")[-1].casefold()).strip("_")
    if "temporarily" in token and "closed" in token:
        return "temporarily_closed"
    if "permanently" in token and "closed" in token:
        return "permanently_closed"
    if token in {"open", "closed", "unknown"}:
        return token
    return ""


def _address_values(address):
    if not isinstance(address, dict):
        return {}
    return {
        "street_address": _clean(address.get("streetAddress")),
        "city": _clean(address.get("addressLocality")),
        "state_or_region": _clean(address.get("addressRegion")),
        "postal_code": _clean(address.get("postalCode")),
        "country": _clean(address.get("addressCountry", {}).get("name") if isinstance(address.get("addressCountry"), dict) else address.get("addressCountry")),
    }


def extract_restaurant_proposals(html, source_url, record=None):
    soup = BeautifulSoup(html or "", "html.parser")
    nodes = _restaurant_nodes(_json_ld_nodes(soup), record=record)
    node = nodes[0] if nodes else {}
    proposals = {field: _proposal(None, 0, "") for field in PROPOSAL_FIELDS}

    weekly = _hours_from_specs(node.get("openingHoursSpecification"))
    if not weekly:
        weekly = _hours_from_strings(node.get("openingHours"))
    if weekly:
        proposals["weekly_hours"] = _proposal(weekly, 0.96, source_url)
    else:
        raw_hours = node.get("openingHours")
        if raw_hours:
            raw_hours = "\n".join(_clean(item) for item in (raw_hours if isinstance(raw_hours, list) else [raw_hours]) if _clean(item))
            proposals["raw_hours_text"] = _proposal(raw_hours, 0.55, source_url)

    text_soup = BeautifulSoup(html or "", "html.parser")
    for tag in text_soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    visible = _clean(text_soup.get_text(" ", strip=True))[:200000]

    notes_match = re.search(
        r"([^.!?]{0,80}(?:holiday hours|seasonal hours|hours may vary|kitchen closes)[^.!?]{0,120}[.!?]?)",
        visible,
        re.I,
    )
    if notes_match:
        proposals["hours_notes"] = _proposal(_clean(notes_match.group(1)), 0.78, source_url)

    promo_match = re.search(
        r"([^.!?]{0,80}(?:rewards?|loyalty|promotion|discount|save \d+%)[^.!?]{0,180}[.!?]?)",
        visible,
        re.I,
    )
    if promo_match:
        proposals["rewards_promotions"] = _proposal(_clean(promo_match.group(1)), 0.72, source_url)

    logo = _first_url(node.get("logo"), source_url)
    image = _first_url(node.get("image"), source_url)
    if not logo:
        meta_logo = soup.find("meta", attrs={"property": re.compile(r"og:logo", re.I)})
        logo = _first_url(meta_logo.get("content") if meta_logo else "", source_url)
    if not image:
        meta_image = soup.find("meta", attrs={"property": "og:image"})
        image = _first_url(meta_image.get("content") if meta_image else "", source_url)
    if logo or image:
        proposals["image_url"] = _proposal(logo or image, 0.95 if logo else 0.76, source_url)

    status = _status(node.get("businessStatus") or node.get("status"))
    if status:
        proposals["current_status"] = _proposal(status, 0.9, source_url)

    action_text = json.dumps(node.get("potentialAction") or node.get("action") or "", ensure_ascii=True).casefold()
    if "orderaction" in action_text or re.search(r"\b(order online|online ordering|pay online)\b", visible, re.I):
        proposals["online_payment"] = _proposal("true", 0.88, source_url)
    if re.search(r"\b(delivery available|we deliver|offers? delivery|delivery orders?)\b", visible, re.I):
        proposals["delivery"] = _proposal("true", 0.86, source_url)

    phone = _clean(node.get("telephone"))
    if phone:
        proposals["phone"] = _proposal(phone, 0.94, source_url)
    for field, value in _address_values(node.get("address")).items():
        if value:
            proposals[field] = _proposal(value, 0.94, source_url)
    return proposals


def _merge_proposals(target, incoming):
    for field in PROPOSAL_FIELDS:
        candidate = incoming.get(field) or {}
        current = target.get(field) or {}
        if not candidate.get("found"):
            continue
        if not current.get("found") or float(candidate.get("confidence") or 0) > float(current.get("confidence") or 0):
            target[field] = candidate


def fetch_restaurant_details(record):
    record = record if isinstance(record, dict) else {}
    restaurant_id = _clean(record.get("restaurant_id") or record.get("id"))
    urls = []
    for value in (record.get("restaurant_website_url"), record.get("source_menu_url")):
        value = _clean(value)
        if value and value not in urls:
            urls.append(value)
    if not urls:
        return {
            "ok": False,
            "code": "missing_urls",
            "error": "Add a Website URL or Menu URL before fetching details.",
            "restaurant_id": restaurant_id,
        }

    proposals = {field: _proposal(None, 0, "") for field in PROPOSAL_FIELDS}
    sources, errors = [], []
    for url in urls:
        try:
            html, source = fetch_public_restaurant_page(url)
            sources.append(source)
            _merge_proposals(proposals, extract_restaurant_proposals(html, source["url"], record=record))
        except RestaurantFetchError as exc:
            errors.append({"url": url, "code": exc.code, "message": str(exc)})
        except Exception:
            errors.append({"url": url, "code": "parse_failed", "message": "The restaurant webpage could not be parsed."})

    found_count = sum(1 for proposal in proposals.values() if proposal.get("found"))
    if not found_count:
        if errors and not sources:
            return {
                "ok": False,
                "code": errors[0]["code"],
                "error": errors[0]["message"],
                "restaurant_id": restaurant_id,
                "sources": sources,
                "errors": errors,
            }
        return {
            "ok": False,
            "code": "no_data",
            "error": "No additional restaurant details were found.",
            "restaurant_id": restaurant_id,
            "sources": sources,
            "errors": errors,
            "proposals": proposals,
        }

    message = "Some details were found, but one or more sources could not be read." if errors else "Restaurant details are ready to review."
    return {
        "ok": True,
        "restaurant_id": restaurant_id,
        "sources": sources,
        "proposals": proposals,
        "partial": bool(errors),
        "errors": errors,
        "message": message,
    }
