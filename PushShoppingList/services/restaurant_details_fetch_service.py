"""Evidence-backed restaurant information discovery, review, and approved apply."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import ipaddress
import json
import base64
from pathlib import Path
import re
import socket
import threading
import time
import uuid
from io import BytesIO
from urllib.parse import quote, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from PushShoppingList.services import menu_store_service
from PushShoppingList.services.file_lock_service import workspace_write_lock
from PushShoppingList.services.recipe_extract_service import menu_page_request_headers
from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import scoped_package_path


FETCH_TIMEOUT = (6, 16)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
MAX_SCAN_WORKERS = 3
MAX_DISCOVERED_LINKS = 6
CACHE_TTL_SECONDS = 15 * 60
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
FIELD_ORDER = (
    "restaurant_name", "website_url", "menu_url", "phone", "street_address", "city",
    "state_or_region", "postal_code", "country", "latitude", "longitude", "weekly_hours",
    "raw_hours_text", "hours_notes", "current_status", "image_url", "rating", "rating_count",
    "online_payment", "online_ordering", "pickup", "delivery", "reservations",
    "rewards_promotions", "promotions", "social_urls", "ordering_provider_urls",
)
PROPOSAL_FIELDS = (
    "weekly_hours", "raw_hours_text", "hours_notes", "rewards_promotions", "image_url",
    "current_status", "online_payment", "delivery", "phone", "street_address", "city",
    "state_or_region", "postal_code", "country",
)
BOOLEAN_FIELDS = {"online_payment", "online_ordering", "pickup", "delivery", "reservations"}
ADDRESS_FIELDS = {"street_address", "city", "state_or_region", "postal_code", "country"}
SENSITIVE_APPLY_ALL_FIELDS = {*ADDRESS_FIELDS, "image_url", "current_status"}
SOURCE_QUALITY = {
    "official_website": 1.0,
    "official_menu": 0.98,
    "official_menu_item": 0.97,
    "official_discovered": 0.92,
    "saved_source": 0.88,
    "supported_public_source": 0.72,
}
METHOD_RELIABILITY = {
    "json_ld": 0.98,
    "structured_metadata": 0.94,
    "open_graph": 0.83,
    "meta_tag": 0.8,
    "navigation_link": 0.79,
    "visible_text": 0.68,
    "ai_interpretation": 0.58,
}
CURRENT_FIELD_KEYS = {
    "restaurant_name": ("restaurant_name",),
    "website_url": ("restaurant_website_url", "website_url"),
    "menu_url": ("source_menu_url", "menu_url"),
    "phone": ("phone", "restaurant_phone"),
    "street_address": ("address_line", "restaurant_street_address", "full_address"),
    "city": ("city", "restaurant_city"),
    "state_or_region": ("state", "state_or_region", "restaurant_state"),
    "postal_code": ("postal_code", "restaurant_postal_code"),
    "country": ("country", "restaurant_country"),
    "latitude": ("latitude",),
    "longitude": ("longitude",),
    "weekly_hours": ("weekly_hours",),
    "raw_hours_text": ("raw_hours_data", "hours_text"),
    "hours_notes": ("hours_notes",),
    "current_status": ("current_status",),
    "image_url": ("logo_url", "restaurant_logo_url", "logo"),
    "rating": ("rating", "restaurant_rating"),
    "rating_count": ("rating_count",),
    "online_payment": ("online_payment_available", "online_payment"),
    "online_ordering": ("online_ordering_available", "online_ordering"),
    "pickup": ("pickup_available", "pickup"),
    "delivery": ("delivery_available", "delivery"),
    "reservations": ("reservation_available", "reservations"),
    "rewards_promotions": ("rewards_text", "rewards_promotions"),
    "promotions": ("promotions",),
    "social_urls": ("social_urls",),
    "ordering_provider_urls": ("ordering_provider_urls",),
}
STORE_FIELD_KEYS = {
    "restaurant_name": "restaurant_name", "website_url": "restaurant_website_url",
    "menu_url": "source_menu_url", "phone": "phone", "street_address": "address_line",
    "city": "city", "state_or_region": "state", "postal_code": "postal_code",
    "country": "country", "latitude": "latitude", "longitude": "longitude",
    "weekly_hours": "weekly_hours", "raw_hours_text": "raw_hours_data",
    "hours_notes": "hours_notes", "current_status": "current_status", "image_url": "logo_url",
    "rating": "rating", "rating_count": "rating_count",
    "online_payment": "online_payment_available", "online_ordering": "online_ordering_available",
    "pickup": "pickup_available", "delivery": "delivery_available",
    "reservations": "reservation_available", "rewards_promotions": "rewards_text",
    "promotions": "promotions", "social_urls": "social_urls",
    "ordering_provider_urls": "ordering_provider_urls",
}
_PAGE_CACHE = {}
_ROBOTS_CACHE = {}
_CACHE_LOCK = threading.RLock()
_PENDING_LOCK = threading.RLock()
PENDING_SCAN_FILE = scoped_package_path("restaurant_information_scans.json")


class RestaurantFetchError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _text_key(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).casefold()).strip()


def _first(record, keys):
    for key in keys:
        value = record.get(key) if isinstance(record, dict) else None
        if value not in (None, "", [], {}):
            return value
    return None


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
        if not ipaddress.ip_address(address).is_global:
            raise RestaurantFetchError("blocked_url", "Private or local restaurant URLs cannot be fetched.")
    return url


def _cache_key(url):
    parsed = urlparse(_clean(url))
    return urlunparse((parsed.scheme.casefold(), (parsed.netloc or "").casefold(), parsed.path or "/", "", parsed.query, ""))


def _robots_allowed(url):
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    with _CACHE_LOCK:
        cached = _ROBOTS_CACHE.get(robots_url)
        if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
    allowed = True
    try:
        response = requests.get(robots_url, headers=menu_page_request_headers(), timeout=(3, 6))
        if response.ok:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            allowed = parser.can_fetch(menu_page_request_headers().get("User-Agent", "*"), url)
    except requests.RequestException:
        allowed = True
    with _CACHE_LOCK:
        _ROBOTS_CACHE[robots_url] = (time.time(), allowed)
    return allowed


def fetch_public_restaurant_page(url, force=False):
    """Fetch bounded public HTML, validating redirects and honoring robots exclusions."""
    current = _public_http_url(url)
    key = _cache_key(current)
    if not force:
        with _CACHE_LOCK:
            cached = _PAGE_CACHE.get(key)
            if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
                html, metadata = cached[1]
                return html, {**metadata, "cached": True}
    if not _robots_allowed(current):
        raise RestaurantFetchError("robots_blocked", "The source does not permit automated scanning.")
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(
                current, headers=menu_page_request_headers(), timeout=FETCH_TIMEOUT,
                stream=True, allow_redirects=False,
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
                if not _robots_allowed(current):
                    raise RestaurantFetchError("robots_blocked", "The redirect target does not permit automated scanning.")
                continue
            if response.status_code in {401, 403, 429, 451}:
                raise RestaurantFetchError("blocked", "The restaurant website blocked automated access.")
            response.raise_for_status()
            content_type = _clean(response.headers.get("content-type")).casefold()
            if content_type and not any(kind in content_type for kind in ("html", "xhtml", "text/plain")):
                raise RestaurantFetchError("unsupported", "The restaurant URL did not return a webpage.")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise RestaurantFetchError("too_large", "The restaurant webpage was too large to inspect safely.")
                chunks.append(chunk)
            html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
            metadata = {
                "url": str(response.url or current), "retrieved_at": _now_iso(),
                "fetched_at": _now_iso(), "http_status": response.status_code, "cached": False,
            }
            with _CACHE_LOCK:
                _PAGE_CACHE[key] = (time.time(), (html, metadata))
            return html, metadata
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
    values = node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type")]
    return {_clean(value).casefold() for value in values if _clean(value)}


def _address_values(address):
    if not isinstance(address, dict):
        return {}
    country = address.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    return {
        "street_address": _clean(address.get("streetAddress")),
        "city": _clean(address.get("addressLocality")),
        "state_or_region": _clean(address.get("addressRegion")),
        "postal_code": _clean(address.get("postalCode")),
        "country": _clean(country),
    }


def _phone_key(value):
    digits = re.sub(r"\D+", "", _clean(value))
    return digits[-10:] if len(digits) >= 10 else digits


def _node_match_score(node, record, source_url):
    record = record if isinstance(record, dict) else {}
    address = _address_values(node.get("address"))
    score, reasons = 0, []
    current_name = _text_key(_first(record, CURRENT_FIELD_KEYS["restaurant_name"]))
    candidate_name = _text_key(node.get("name"))
    if current_name and candidate_name:
        ratio = SequenceMatcher(None, current_name, candidate_name).ratio()
        if ratio >= 0.88:
            score += 4
            reasons.append("name")
        elif ratio < 0.48:
            score -= 4
    current_phone = _phone_key(_first(record, CURRENT_FIELD_KEYS["phone"]))
    candidate_phone = _phone_key(node.get("telephone"))
    if len(current_phone) >= 7 and candidate_phone:
        if current_phone == candidate_phone:
            score += 6
            reasons.append("phone")
        else:
            score -= 3
    for field, points in (("street_address", 5), ("city", 2), ("state_or_region", 1), ("postal_code", 3)):
        current = _text_key(_first(record, CURRENT_FIELD_KEYS[field]))
        candidate = _text_key(address.get(field))
        if current and candidate:
            if current == candidate or (field == "street_address" and current in candidate):
                score += points
                reasons.append(field)
            elif field in {"street_address", "postal_code"}:
                score -= points
    current_site = _clean(_first(record, CURRENT_FIELD_KEYS["website_url"]))
    if current_site and urlparse(current_site).hostname == urlparse(source_url).hostname:
        score += 1
        reasons.append("official_domain")
    return score, reasons


def _select_restaurant_node(nodes, record, source_url):
    accepted = {"restaurant", "foodestablishment", "localbusiness", "organization"}
    candidates = [node for node in nodes if _type_names(node) & accepted]
    if not candidates:
        return {}, {"matched": True, "reason": "No location-specific structured node was present."}
    ranked = sorted(
        ((*_node_match_score(node, record, source_url), node) for node in candidates),
        key=lambda item: item[0], reverse=True,
    )
    score, reasons, selected = ranked[0]
    record_has_identity = any(_first(record, CURRENT_FIELD_KEYS[field]) for field in (
        "restaurant_name", "phone", "street_address", "city", "postal_code"
    ))
    if record_has_identity and score < 1:
        return {}, {"matched": False, "reason": "The source did not match the saved restaurant location."}
    if len(ranked) > 1 and record_has_identity and score < 3:
        return {}, {"matched": False, "reason": "The source contains multiple locations and no reliable location match."}
    return selected, {"matched": True, "score": score, "reasons": reasons}


def _time_24(value):
    text = _clean(value)
    if re.fullmatch(r"24:00(?::00)?", text):
        return "24:00"
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        return ""
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{hour:02d}:{minute:02d}" if 0 <= hour <= 23 and 0 <= minute <= 59 else ""


def _day_key(value):
    return DAY_ALIASES.get(_clean(value).split("/")[-1].casefold(), "")


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
    if opens == "00:00" and closes in {"23:59", "24:00"}:
        entry["open_24_hours"] = True
    value = {"opens": opens, "closes": closes}
    if opens and closes and value not in entry["ranges"]:
        entry["ranges"].append(value)


def _hours_from_specs(raw):
    weekly = {}
    for spec in (raw if isinstance(raw, list) else [raw]):
        if not isinstance(spec, dict):
            continue
        days = spec.get("dayOfWeek")
        days = days if isinstance(days, list) else [days]
        opens, closes = _time_24(spec.get("opens")), _time_24(spec.get("closes"))
        for raw_day in days:
            day = _day_key(raw_day)
            if not day:
                continue
            if _clean(spec.get("opens")).casefold() == "closed":
                weekly[day] = {"closed": True, "ranges": []}
            elif opens and closes:
                _append_hours_range(weekly, day, opens, closes)
    return weekly


def _hours_from_strings(raw):
    weekly = {}
    for value in (raw if isinstance(raw, list) else [raw]):
        text = _clean(value)
        match = re.match(r"([A-Za-z]+)(?:\s*-\s*([A-Za-z]+))?\s+(.+)$", text)
        if not match:
            continue
        first = _day_key(match.group(1))
        last = _day_key(match.group(2)) if match.group(2) else first
        days, detail = _days_between(first, last), match.group(3)
        if detail.casefold() == "closed":
            for day in days:
                weekly[day] = {"closed": True, "ranges": []}
            continue
        if re.search(r"open\s+24\s+hours", detail, re.I):
            for day in days:
                weekly[day] = {"closed": False, "open_24_hours": True, "ranges": [{"opens": "00:00", "closes": "24:00"}]}
            continue
        ranges = re.findall(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", detail)
        for day in days:
            for opens, closes in ranges:
                _append_hours_range(weekly, day, _time_24(opens), _time_24(closes))
    return weekly


def _normalize_url(value):
    text = _clean(value)
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        return urlunparse((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, "", parsed.query, ""))
    except ValueError:
        return ""


def _normalize_status(value):
    token = re.sub(r"[^a-z]+", "_", _clean(value).split("/")[-1].casefold()).strip("_")
    if "temporarily" in token and "closed" in token:
        return "temporarily_closed"
    if "permanently" in token and "closed" in token:
        return "permanently_closed"
    if token in {"open", "operating", "active"}:
        return "operating"
    if token in {"closed", "unknown"}:
        return "unknown"
    return ""


def _structured_boolean(value):
    """Return an explicit structured boolean without treating missing data as false."""
    if isinstance(value, bool):
        return value
    token = _clean(value).casefold()
    if token in {"true", "yes", "1", "available"}:
        return True
    if token in {"false", "no", "0", "unavailable", "not available"}:
        return False
    return None


def _normalize_value(field, value):
    if value in (None, "", [], {}):
        return None
    if field in {"website_url", "menu_url", "image_url"}:
        return _normalize_url(value) or None
    if field in {"social_urls", "ordering_provider_urls"}:
        values = value if isinstance(value, list) else [value]
        return sorted({_normalize_url(item) for item in values if _normalize_url(item)}) or None
    if field in BOOLEAN_FIELDS:
        if value is True or _clean(value).casefold() == "true":
            return True
        if value is False or _clean(value).casefold() == "false":
            return False
        return None
    if field == "phone":
        digits = re.sub(r"\D+", "", _clean(value))
        if len(digits) == 10:
            return f"+1{digits}"
        return f"+{digits}" if 7 <= len(digits) <= 15 else None
    if field in {"latitude", "longitude", "rating", "rating_count"}:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if field == "rating" and not 0 <= numeric <= 5:
            return None
        if field == "latitude" and not -90 <= numeric <= 90:
            return None
        if field == "longitude" and not -180 <= numeric <= 180:
            return None
        return int(numeric) if numeric.is_integer() else numeric
    if field == "current_status":
        return _normalize_status(value) or None
    if field == "weekly_hours":
        return value if isinstance(value, dict) and value else None
    if field in {"promotions"}:
        values = value if isinstance(value, list) else [value]
        return [_clean(item) for item in values if _clean(item)] or None
    return _clean(value) or None


def _candidate(field, value, source_url, source_type, method, confidence, evidence, retrieved_at, metadata=None):
    normalized = _normalize_value(field, value)
    if normalized in (None, "", [], {}):
        return None
    if field == "image_url" and isinstance(metadata, dict):
        image_format = _clean(metadata.get("image_format")).casefold()
        width, height = metadata.get("width"), metadata.get("height")
        if image_format == "svg":
            confidence += 0.04
        elif image_format == "png":
            confidence += 0.02
        if width and height:
            aspect_ratio = float(width) / float(height)
            if 0.75 <= aspect_ratio <= 1.34:
                confidence += 0.03
            elif aspect_ratio > 4 or aspect_ratio < 0.25:
                confidence -= 0.08
        if metadata.get("fallback"):
            confidence = min(confidence, 0.52)
    source_quality = SOURCE_QUALITY.get(source_type, 0.65)
    method_quality = METHOD_RELIABILITY.get(method, 0.6)
    score = max(0.01, min(0.99, float(confidence) * source_quality * method_quality))
    payload = {
        "field": field, "value": value, "normalized_value": normalized,
        "source_url": source_url, "source_type": source_type, "extraction_method": method,
        "confidence": round(score, 2), "retrieved_at": retrieved_at or _now_iso(),
        "evidence": _clean(evidence)[:280],
    }
    if isinstance(metadata, dict):
        payload.update({key: value for key, value in metadata.items() if value not in (None, "")})
    signature = json.dumps([field, normalized, source_url, method], sort_keys=True, default=str)
    payload["candidate_id"] = f"candidate_{hashlib.sha256(signature.encode('utf-8')).hexdigest()[:18]}"
    return payload


def _first_url(value, base_url):
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl") or value.get("@id")
    if isinstance(value, list):
        value = next((item for item in value if item), "")
        if isinstance(value, dict):
            value = value.get("url") or value.get("contentUrl") or value.get("@id")
    return urljoin(base_url, _clean(value)) if _clean(value) else ""


def _looks_like_brand_logo(url, evidence="", explicit=False):
    text = f"{url} {evidence}".casefold()
    rejected_tokens = (
        "menu-screenshot", "menu_image", "menu-image", "recipe-image", "food-photo",
        "dish-", "meal-", "restaurant-interior", "storefront-photo", "advertisement",
        "promo-banner", "placeholder", "no-image", "no_image", "default-image",
        "favicon", "apple-touch-icon",
    )
    if any(token in text for token in rejected_tokens):
        return False
    return explicit or any(token in text for token in ("logo", "brand", "wordmark"))


def _image_asset_metadata(url, tag=None, fallback=False):
    suffix = Path(urlparse(_clean(url)).path).suffix.casefold().lstrip(".")
    image_format = "jpeg" if suffix in {"jpg", "jpeg"} else suffix if suffix in {"png", "webp", "svg", "gif", "ico"} else ""
    width = _clean(tag.get("width")) if tag else ""
    height = _clean(tag.get("height")) if tag else ""
    try:
        width = int(float(width)) if width else None
    except ValueError:
        width = None
    try:
        height = int(float(height)) if height else None
    except ValueError:
        height = None
    return {"image_format": image_format, "width": width, "height": height, "fallback": bool(fallback)}


def _visible_text(soup):
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return _clean(clone.get_text(" ", strip=True))[:160000]


def _link_candidates(soup, source_url):
    results = {"menu": [], "order": [], "reservation": [], "rewards": [], "social": []}
    source_host = (urlparse(source_url).hostname or "").casefold().removeprefix("www.")
    for anchor in soup.find_all("a", href=True):
        text = _clean(anchor.get_text(" ", strip=True) or anchor.get("aria-label") or anchor.get("title"))
        href = urljoin(source_url, anchor.get("href"))
        normalized = _normalize_url(href)
        if not normalized:
            continue
        host = (urlparse(normalized).hostname or "").casefold().removeprefix("www.")
        key = f"{text} {normalized}".casefold()
        if re.search(r"\b(menu|food menu)\b", key):
            results["menu"].append((normalized, text))
        if re.search(r"\b(order|ordering|order online|pickup|delivery)\b", key):
            results["order"].append((normalized, text))
        if re.search(r"\b(reserve|reservation|book a table)\b", key):
            results["reservation"].append((normalized, text))
        if re.search(r"\b(rewards?|loyalty|promotions?|offers?)\b", key):
            results["rewards"].append((normalized, text))
        if any(domain in host for domain in ("facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com")):
            results["social"].append((normalized, text))
        if host == source_host and re.search(r"\b(hours?|contact|locations?|menu|order|delivery|reservations?|rewards?|promotions?)\b", key):
            results.setdefault("follow", []).append((normalized, text))
    return results


def extract_restaurant_candidates(html, source_url, source_type="official_website", record=None, retrieved_at=""):
    soup = BeautifulSoup(html or "", "html.parser")
    nodes = _json_ld_nodes(soup)
    node, match = _select_restaurant_node(nodes, record or {}, source_url)
    if not match.get("matched"):
        return {"matched": False, "match": match, "candidates": [], "follow_links": []}
    candidates = []

    def add(field, value, method, confidence, evidence, metadata=None):
        candidate = _candidate(field, value, source_url, source_type, method, confidence, evidence, retrieved_at, metadata=metadata)
        if candidate:
            candidates.append(candidate)

    if node:
        add("restaurant_name", node.get("name"), "json_ld", 0.99, f"Structured name: {node.get('name', '')}")
        add("phone", node.get("telephone"), "json_ld", 0.98, f"Structured telephone: {node.get('telephone', '')}")
        add("website_url", node.get("url"), "json_ld", 0.96, "Structured business URL")
        for field, value in _address_values(node.get("address")).items():
            add(field, value, "json_ld", 0.98, f"Structured PostalAddress {field}")
        geo = node.get("geo") if isinstance(node.get("geo"), dict) else {}
        add("latitude", geo.get("latitude"), "json_ld", 0.97, "Structured GeoCoordinates latitude")
        add("longitude", geo.get("longitude"), "json_ld", 0.97, "Structured GeoCoordinates longitude")
        weekly = _hours_from_specs(node.get("openingHoursSpecification")) or _hours_from_strings(node.get("openingHours"))
        add("weekly_hours", weekly, "json_ld", 0.98, "Structured opening hours")
        raw_hours = node.get("openingHours")
        if raw_hours:
            raw_text = "\n".join(_clean(item) for item in (raw_hours if isinstance(raw_hours, list) else [raw_hours]) if _clean(item))
            add("raw_hours_text", raw_text, "json_ld", 0.56, raw_text)
        add("current_status", node.get("businessStatus") or node.get("status"), "json_ld", 0.96, "Structured permanent business status")
        structured_booleans = {
            "online_payment": ("onlinePaymentAvailable",),
            "online_ordering": ("onlineOrderingAvailable",),
            "pickup": ("pickupAvailable", "takeoutAvailable"),
            "delivery": ("deliveryAvailable", "offersDelivery"),
            "reservations": ("acceptsReservations", "reservationAvailable"),
        }
        for field, keys in structured_booleans.items():
            matched_key = next((key for key in keys if key in node), "")
            normalized_boolean = _structured_boolean(node.get(matched_key)) if matched_key else None
            if normalized_boolean is not None:
                add(
                    field, normalized_boolean, "json_ld", 0.96,
                    f"Structured {matched_key} value",
                )
        rating = node.get("aggregateRating") if isinstance(node.get("aggregateRating"), dict) else {}
        add("rating", rating.get("ratingValue"), "json_ld", 0.96, "Structured AggregateRating value")
        add("rating_count", rating.get("ratingCount") or rating.get("reviewCount"), "json_ld", 0.94, "Structured AggregateRating count")
        logo = _first_url(node.get("logo"), source_url)
        if logo and _looks_like_brand_logo(logo, "structured logo", explicit=True):
            add("image_url", logo, "json_ld", 0.98, "Explicit schema.org logo for the matched restaurant", _image_asset_metadata(logo))
        menu_url = _first_url(node.get("hasMenu") or node.get("menu"), source_url)
        add("menu_url", menu_url, "json_ld", 0.95, "Structured Menu URL")
        same_as = node.get("sameAs") if isinstance(node.get("sameAs"), list) else [node.get("sameAs")]
        add("social_urls", [value for value in same_as if value], "json_ld", 0.91, "Structured sameAs links")
        actions = node.get("potentialAction") or node.get("action") or []
        actions = actions if isinstance(actions, list) else [actions]
        order_urls, reservation_urls = [], []
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_types = _type_names(action)
            target = _first_url(action.get("target") or action.get("url"), source_url)
            if action_types & {"orderaction", "buyaction"}:
                if target:
                    order_urls.append(target)
                add("online_ordering", True, "json_ld", 0.94, "Structured OrderAction")
                add("online_payment", True, "json_ld", 0.79, "Structured online ordering action")
            if action_types & {"reserveaction", "scheduleaction"}:
                if target:
                    reservation_urls.append(target)
                add("reservations", True, "json_ld", 0.93, "Structured ReserveAction")
        add("ordering_provider_urls", order_urls, "json_ld", 0.9, "Structured ordering targets")
        if reservation_urls:
            add("social_urls", reservation_urls, "json_ld", 0.65, "Structured reservation targets")

    links = _link_candidates(soup, source_url)
    if links["menu"]:
        add("menu_url", links["menu"][0][0], "navigation_link", 0.88, links["menu"][0][1] or "Menu navigation link")
    if links["order"]:
        add("ordering_provider_urls", [item[0] for item in links["order"][:5]], "navigation_link", 0.83, "Order or delivery navigation links")
        add("online_ordering", True, "navigation_link", 0.82, links["order"][0][1] or "Order online link")
        if any(re.search(r"pickup", item[1], re.I) for item in links["order"]):
            add("pickup", True, "navigation_link", 0.8, "Pickup navigation link")
        if any(re.search(r"delivery", item[1], re.I) for item in links["order"]):
            add("delivery", True, "navigation_link", 0.8, "Delivery navigation link")
    if links["reservation"]:
        add("reservations", True, "navigation_link", 0.84, links["reservation"][0][1] or "Reservation link")
    if links["social"]:
        add("social_urls", [item[0] for item in links["social"][:8]], "navigation_link", 0.86, "Official social links")

    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical:
        add("website_url", urljoin(source_url, canonical.get("href", "")), "meta_tag", 0.86, "Canonical page URL")
    og_title = soup.find("meta", attrs={"property": "og:site_name"})
    if og_title:
        add("restaurant_name", og_title.get("content"), "open_graph", 0.78, "Open Graph site name")
    explicit_logo = soup.find("meta", attrs={"property": re.compile(r"og:logo", re.I)})
    if explicit_logo:
        logo_url = urljoin(source_url, _clean(explicit_logo.get("content")))
        if _looks_like_brand_logo(logo_url, "Open Graph logo", explicit=True):
            add("image_url", logo_url, "open_graph", 0.9, "Explicit Open Graph logo", _image_asset_metadata(logo_url))

    for image in soup.select("header img[src], nav img[src], [role='banner'] img[src]"):
        image_url = urljoin(source_url, _clean(image.get("src")))
        evidence = " ".join(filter(None, (
            _clean(image.get("alt")), _clean(image.get("class")), _clean(image.get("id")), image_url,
        )))
        if _looks_like_brand_logo(image_url, evidence):
            add(
                "image_url", image_url, "structured_metadata", 0.92,
                f"Header or navigation branding: {_clean(image.get('alt')) or 'logo image'}",
                _image_asset_metadata(image_url, image),
            )

    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image:
        image_url = urljoin(source_url, _clean(og_image.get("content")))
        if _looks_like_brand_logo(image_url, "Open Graph image"):
            add("image_url", image_url, "open_graph", 0.8, "Open Graph image appears to be a brand mark", _image_asset_metadata(image_url))

    favicon_links = soup.find_all("link", rel=lambda value: value and any("icon" in str(item).casefold() for item in (value if isinstance(value, list) else [value])))
    for favicon in favicon_links[:2]:
        image_url = urljoin(source_url, _clean(favicon.get("href")))
        if not image_url:
            continue
        add(
            "image_url", image_url, "meta_tag", 0.52,
            "Official site icon used only as a fallback logo candidate",
            _image_asset_metadata(image_url, favicon, fallback=True),
        )

    visible = _visible_text(soup)
    notes = re.search(r"([^.!?]{0,90}(?:holiday hours|seasonal hours|hours may vary|kitchen closes)[^.!?]{0,150}[.!?]?)", visible, re.I)
    if notes:
        add("hours_notes", _clean(notes.group(1)), "visible_text", 0.82, notes.group(1))
    promo = re.search(r"([^.!?]{0,90}(?:rewards?|loyalty|promotion|discount|save \d+%)[^.!?]{0,200}[.!?]?)", visible, re.I)
    if promo:
        add("rewards_promotions", _clean(promo.group(1)), "visible_text", 0.76, promo.group(1))
    if re.search(r"\b(delivery available|we deliver|offers? delivery|delivery orders?)\b", visible, re.I):
        add("delivery", True, "visible_text", 0.75, "Page states that delivery is available")

    unique = {}
    for candidate in candidates:
        unique[candidate["candidate_id"]] = candidate
    return {
        "matched": True, "match": match, "candidates": list(unique.values()),
        "follow_links": [item[0] for item in links.get("follow", [])[:4]],
    }


def _proposal(value, confidence, source_url):
    found = value not in (None, "", [], {})
    return {"value": value if found else None, "found": found, "confidence": round(float(confidence), 2) if found else None, "source_url": source_url if found else ""}


def _compat_proposal_value(field, candidate):
    if not candidate:
        return None
    if field in BOOLEAN_FIELDS:
        normalized = candidate.get("normalized_value")
        return "true" if normalized is True else "false" if normalized is False else None
    if field == "current_status":
        return candidate.get("normalized_value")
    return candidate.get("value")


def extract_restaurant_proposals(html, source_url, record=None):
    """Compatibility projection for callers that still consume one proposal per field."""
    extracted = extract_restaurant_candidates(html, source_url, record=record)
    by_field = {}
    for candidate in extracted["candidates"]:
        current = by_field.get(candidate["field"])
        if not current or candidate["confidence"] > current["confidence"]:
            by_field[candidate["field"]] = candidate
    return {
        field: _proposal(
            _compat_proposal_value(field, by_field.get(field)),
            by_field.get(field, {}).get("confidence", 0),
            by_field.get(field, {}).get("source_url", ""),
        )
        for field in PROPOSAL_FIELDS
    }


def _discovery_sources(record):
    ordered = []
    for source_type, keys in (
        ("official_website", CURRENT_FIELD_KEYS["website_url"]),
        ("official_menu", CURRENT_FIELD_KEYS["menu_url"]),
        ("official_menu_item", ("menu_item_url", "restaurant_menu_item_url")),
    ):
        value = _normalize_url(_first(record, keys))
        if value and value not in {item["url"] for item in ordered}:
            ordered.append({"url": value, "source_type": source_type, "label": source_type.replace("_", " ").title()})
    for value in record.get("source_urls", []) if isinstance(record.get("source_urls"), list) else []:
        value = _normalize_url(value)
        if value and value not in {item["url"] for item in ordered}:
            ordered.append({"url": value, "source_type": "saved_source", "label": "Saved source"})
    return ordered


def _fetch_source(source, force=False):
    try:
        try:
            html, metadata = fetch_public_restaurant_page(source["url"], force=force)
        except TypeError as exc:
            if "force" not in str(exc):
                raise
            html, metadata = fetch_public_restaurant_page(source["url"])
        extracted = extract_restaurant_candidates(
            html, metadata["url"], source_type=source["source_type"],
            record=source.get("record") or {}, retrieved_at=metadata.get("retrieved_at") or metadata.get("fetched_at"),
        )
        if not extracted["matched"]:
            return {**source, "status": "mismatch", "status_label": "Source did not match restaurant", "reason": extracted["match"]["reason"], "metadata": metadata, **extracted}
        return {**source, "status": "success", "status_label": "Reached and parsed", "reason": "", "metadata": metadata, **extracted}
    except RestaurantFetchError as exc:
        return {**source, "status": exc.code, "status_label": str(exc), "reason": str(exc), "candidates": [], "follow_links": []}
    except Exception as exc:
        return {**source, "status": "parse_failed", "status_label": "Page could not be parsed", "reason": _clean(exc), "candidates": [], "follow_links": []}


def _normalized_key(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return _text_key(value)


def _confidence_label(score, conflict=False):
    if conflict:
        return "Conflict"
    if score >= 0.85:
        return "High"
    if score >= 0.65:
        return "Medium"
    return "Low"


def _reconcile_field(field, candidates, record, locked_fields):
    current = _first(record, CURRENT_FIELD_KEYS[field])
    current_normalized = _normalize_value(field, current)
    grouped = {}
    for candidate in candidates:
        key = _normalized_key(candidate["normalized_value"])
        grouped.setdefault(key, []).append(candidate)
    ranked = []
    for group in grouped.values():
        best = max(group, key=lambda item: item["confidence"])
        agreement_bonus = min(0.09, 0.03 * (len({item["source_url"] for item in group}) - 1))
        ranked.append({**best, "confidence": round(min(0.99, best["confidence"] + agreement_bonus), 2), "agreeing_source_count": len({item["source_url"] for item in group})})
    ranked.sort(key=lambda item: (item["confidence"], item["retrieved_at"]), reverse=True)
    recommended = ranked[0] if ranked else None
    conflict = len(ranked) > 1
    changed = bool(recommended) and _normalized_key(recommended["normalized_value"]) != _normalized_key(current_normalized)
    locked = field in locked_fields
    explicit = field in SENSITIVE_APPLY_ALL_FIELDS and bool(current not in (None, "", [], {}))
    if field == "current_status" and recommended and recommended["normalized_value"] == "permanently_closed":
        explicit = True
    selectable = bool(recommended and changed and not locked)
    return {
        "field": field,
        "current_value": current,
        "current_normalized_value": current_normalized,
        "candidates": ranked,
        "recommended": recommended,
        "conflict": conflict,
        "changed": changed,
        "locked": locked,
        "requires_explicit_review": explicit,
        "selectable": selectable,
        "confidence_label": _confidence_label(recommended["confidence"] if recommended else 0, conflict=conflict),
    }


def scan_restaurant_information(record, force=False):
    record = deepcopy(record) if isinstance(record, dict) else {}
    restaurant_id = _clean(record.get("restaurant_id") or record.get("id"))
    sources = _discovery_sources(record)
    if not sources:
        return {
            "ok": True, "restaurant_id": restaurant_id, "scan_id": "", "scanned_at": _now_iso(),
            "fields": {}, "proposals": {field: _proposal(None, 0, "") for field in PROPOSAL_FIELDS},
            "sources": [{"label": "Restaurant sources", "status": "not_configured", "status_label": "Source not configured", "url": ""}],
            "unresolved_fields": list(FIELD_ORDER),
            "summary": {"sources_scanned": 0, "sources_reached": 0, "fields_discovered": 0, "high_confidence_changes": 0, "conflicts": 0, "unresolved": len(FIELD_ORDER)},
            "message": "No restaurant website, menu URL, or menu-item URL is configured.",
        }
    for source in sources:
        source["record"] = record
    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_SCAN_WORKERS, len(sources))) as pool:
        futures = {pool.submit(_fetch_source, source, force): source for source in sources}
        for future in as_completed(futures):
            results.append(future.result())
    order = {item["url"]: index for index, item in enumerate(sources)}
    results.sort(key=lambda item: order.get(item["url"], 999))

    known_urls = {item["url"] for item in results}
    discovered = []
    official_hosts = {(urlparse(item["url"]).hostname or "").casefold() for item in sources}
    for result in results:
        if result.get("status") != "success":
            continue
        for url in result.get("follow_links", []):
            if len(discovered) >= MAX_DISCOVERED_LINKS:
                break
            if url in known_urls or (urlparse(url).hostname or "").casefold() not in official_hosts:
                continue
            known_urls.add(url)
            discovered.append({"url": url, "source_type": "official_discovered", "label": "Discovered official page", "record": record})
    if discovered:
        with ThreadPoolExecutor(max_workers=min(MAX_SCAN_WORKERS, len(discovered))) as pool:
            results.extend(pool.map(lambda source: _fetch_source(source, force), discovered))

    candidates_by_field = {field: [] for field in FIELD_ORDER}
    for result in results:
        for candidate in result.get("candidates", []):
            if candidate["field"] in candidates_by_field:
                candidates_by_field[candidate["field"]].append(candidate)
    locked_fields = set(record.get("restaurant_information_locked_fields") or record.get("locked_fields") or [])
    fields = {
        field: _reconcile_field(field, candidates, record, locked_fields)
        for field, candidates in candidates_by_field.items() if candidates
    }
    unresolved = [field for field in FIELD_ORDER if field not in fields]
    logo_candidates = fields.get("image_url", {}).get("candidates", [])
    if logo_candidates and all(candidate.get("fallback") for candidate in logo_candidates):
        unresolved.append("image_url")
    proposals = {}
    for field in PROPOSAL_FIELDS:
        recommended = fields.get(field, {}).get("recommended") or {}
        proposals[field] = _proposal(recommended.get("value"), recommended.get("confidence", 0), recommended.get("source_url", ""))
    scanned_at = _now_iso()
    scan_signature = json.dumps([restaurant_id, scanned_at, [item["url"] for item in results]], sort_keys=True)
    summary = {
        "sources_scanned": len(results),
        "sources_reached": sum(item.get("status") == "success" for item in results),
        "fields_discovered": len(fields),
        "high_confidence_changes": sum(
            row["changed"] and row["confidence_label"] == "High" and not row["conflict"] and not row["requires_explicit_review"] and not row["locked"]
            for row in fields.values()
        ),
        "conflicts": sum(row["conflict"] for row in fields.values()),
        "unresolved": len(unresolved),
    }
    public_sources = [{key: value for key, value in item.items() if key not in {"record", "candidates", "follow_links"}} for item in results]
    errors = [
        {"url": item.get("url", ""), "code": item.get("status", "scan_failed"), "message": item.get("reason") or item.get("status_label", "Source scan failed.")}
        for item in results if item.get("status") != "success"
    ]
    return {
        "ok": True, "restaurant_id": restaurant_id,
        "scan_id": f"scan_{hashlib.sha256(scan_signature.encode('utf-8')).hexdigest()[:20]}",
        "scanned_at": scanned_at, "fields": fields, "proposals": proposals,
        "sources": public_sources, "errors": errors, "unresolved_fields": unresolved, "summary": summary,
        "partial": any(item.get("status") != "success" for item in results),
        "message": "Restaurant information is ready to review." if fields else "Sources were scanned, but no matching restaurant fields were discovered.",
    }


def fetch_restaurant_details(record, force=False):
    """Compatibility name retained for the existing route while returning the new scan model."""
    if not _discovery_sources(record if isinstance(record, dict) else {}):
        return {
            "ok": False,
            "code": "missing_urls",
            "error": "Add a Website URL or Menu URL before fetching details.",
            "restaurant_id": _clean((record or {}).get("restaurant_id") or (record or {}).get("id")),
        }
    return scan_restaurant_information(record, force=force)


def _load_pending_scans():
    path = Path(PENDING_SCAN_FILE)
    if not path.exists():
        return {"scans": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return {"scans": payload.get("scans") if isinstance(payload.get("scans"), dict) else {}}


def _save_pending_scans(payload):
    path = Path(PENDING_SCAN_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def store_pending_restaurant_scan(scan):
    if not isinstance(scan, dict) or not scan.get("scan_id"):
        return scan
    with _PENDING_LOCK:
        payload = _load_pending_scans()
        scans = payload["scans"]
        scans[scan["scan_id"]] = deepcopy(scan)
        ordered = sorted(
            scans.items(), key=lambda item: _clean(item[1].get("scanned_at")), reverse=True
        )[:30]
        payload["scans"] = dict(ordered)
        _save_pending_scans(payload)
    return scan


def load_pending_restaurant_scan(scan_id, restaurant_id):
    with _PENDING_LOCK:
        scan = deepcopy(_load_pending_scans()["scans"].get(_clean(scan_id)))
    if not scan or _clean(scan.get("restaurant_id")) != _clean(restaurant_id):
        return {"ok": False, "error": "The pending restaurant information scan was not found."}
    return scan


def select_restaurant_scan_values(scan, selections=None, mode="selected", locked_fields=None):
    scan = scan if isinstance(scan, dict) else {}
    fields = scan.get("fields") if isinstance(scan.get("fields"), dict) else {}
    selections = selections if isinstance(selections, dict) else {}
    locked = set(locked_fields or [])
    values, accepted, rejected = {}, [], []
    for field, row in fields.items():
        if field in locked or row.get("locked"):
            rejected.append({"field": field, "reason": "locked"})
            continue
        candidate = None
        if mode == "high_confidence":
            recommended = row.get("recommended") or {}
            if (
                row.get("selectable") and not row.get("conflict")
                and not row.get("requires_explicit_review")
                and row.get("confidence_label") == "High"
            ):
                candidate = recommended
        else:
            candidate_id = _clean(selections.get(field))
            candidate = next((item for item in row.get("candidates", []) if item.get("candidate_id") == candidate_id), None)
        if not candidate:
            continue
        normalized = _normalize_value(field, candidate.get("value"))
        if normalized in (None, "", [], {}) or _normalized_key(normalized) == _normalized_key(row.get("current_normalized_value")):
            rejected.append({"field": field, "reason": "empty_or_unchanged"})
            continue
        values[field] = candidate.get("value")
        accepted.append({"field": field, "candidate": candidate})
    return {"ok": True, "values": values, "accepted": accepted, "rejected": rejected}


def _snapshot_file(path):
    path = Path(path)
    return path.exists(), path.read_bytes() if path.exists() else b""


def _restore_file(path, snapshot):
    path = Path(path)
    existed, data = snapshot
    if existed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    elif path.exists():
        path.unlink()


def _fetch_approved_logo_bytes(url):
    current = _public_http_url(url)
    if not _robots_allowed(current):
        raise RestaurantFetchError("robots_blocked", "The logo source does not permit automated downloading.")
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(
                current,
                headers={**menu_page_request_headers(), "Accept": "image/png,image/webp,image/jpeg,image/svg+xml,image/*;q=0.8"},
                timeout=FETCH_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise RestaurantFetchError("timeout", "The approved logo download timed out.") from exc
        except requests.RequestException as exc:
            raise RestaurantFetchError("unreachable", "The approved logo could not be downloaded.") from exc
        try:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RestaurantFetchError("blocked", "The logo source returned an invalid redirect.")
                current = _public_http_url(urljoin(current, location))
                continue
            response.raise_for_status()
            mime_type = _clean(response.headers.get("content-type")).split(";", 1)[0].casefold()
            if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}:
                raise RestaurantFetchError("invalid_logo", "The approved logo is not a supported PNG, JPEG, WebP, or SVG image.")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > 5 * 1024 * 1024:
                    raise RestaurantFetchError("logo_too_large", "The approved logo is larger than 5 MB.")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise RestaurantFetchError("invalid_logo", "The approved logo file was empty.")
            return payload, mime_type, current
        except requests.RequestException as exc:
            raise RestaurantFetchError("request_failed", "The approved logo could not be downloaded.") from exc
        finally:
            response.close()
    raise RestaurantFetchError("redirect_loop", "The approved logo redirected too many times.")


def _safe_svg_logo(payload):
    if len(payload) > 1024 * 1024:
        raise RestaurantFetchError("logo_too_large", "SVG logos must be 1 MB or smaller.")
    text = payload.decode("utf-8", errors="strict")
    lowered = text.casefold()
    if "<svg" not in lowered or any(token in lowered for token in ("<script", "<foreignobject", "javascript:", "data:text/html")):
        raise RestaurantFetchError("invalid_logo", "The approved SVG logo contains unsupported active content.")
    if re.search(r"\son[a-z]+\s*=", lowered) or re.search(r"(?:href|src)\s*=\s*['\"]https?://", lowered):
        raise RestaurantFetchError("invalid_logo", "The approved SVG logo contains external or interactive content.")
    return payload


def _store_approved_logo(candidate, restaurant_id):
    payload, mime_type, final_url = _fetch_approved_logo_bytes(candidate.get("value"))
    from PushShoppingList.services import recipe_edit_service
    if mime_type == "image/svg+xml":
        payload = _safe_svg_logo(payload)
        folder = recipe_edit_service.RESTAURANT_LOGO_UPLOAD_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", restaurant_id).strip("_") or "restaurant"
        path = folder / f"{safe_id}_{uuid.uuid4().hex}.svg"
        path.write_bytes(payload)
        logo_url = f"/restaurant_source_logo?restaurant_id={quote(restaurant_id, safe='')}&v={path.stat().st_mtime_ns}"
        return {"logo_url": logo_url, "logo_path": str(path), "logo_thumbnail_path": str(path), "original_url": final_url}
    encoded = base64.b64encode(payload).decode("ascii")
    path, logo_url = recipe_edit_service.save_editable_restaurant_logo_data(
        restaurant_id, f"data:{mime_type};base64,{encoded}"
    )
    thumbnail_path = path.with_name(f"{path.stem}_thumb.webp")
    try:
        from PIL import Image
        with Image.open(BytesIO(payload)) as image:
            image.thumbnail((256, 256), Image.Resampling.LANCZOS)
            image.save(thumbnail_path, "WEBP", quality=88, method=6)
    except Exception:
        thumbnail_path = path
    return {"logo_url": logo_url, "logo_path": str(path), "logo_thumbnail_path": str(thumbnail_path), "original_url": final_url}


def apply_restaurant_information_scan(restaurant_id, scan, selections=None, mode="selected", lock_updates=None):
    restaurant_id = _clean(restaurant_id)
    if not isinstance(scan, dict):
        return {"ok": False, "error": "The pending restaurant information scan is invalid."}
    if mode not in {"selected", "high_confidence"}:
        return {"ok": False, "error": "The restaurant information apply mode is invalid."}
    if not restaurant_id or _clean(scan.get("restaurant_id")) != restaurant_id:
        return {"ok": False, "error": "The scan does not belong to this restaurant."}
    lock_updates = lock_updates if isinstance(lock_updates, dict) else {}
    with workspace_write_lock("restaurant-information-scan"), menu_store_service.MENU_STORE_LOCK:
        path = Path(menu_store_service.MENU_STORE_FILE)
        snapshot = _snapshot_file(path)
        created_logo_paths = []
        try:
            store = menu_store_service.load_menu_store()
            restaurant = menu_store_service.restaurant_for(store, restaurant_id)
            if not restaurant:
                return {"ok": False, "error": "Restaurant source was not found."}
            locked = set(restaurant.get("restaurant_information_locked_fields") or [])
            for field, value in lock_updates.items():
                if field not in FIELD_ORDER:
                    continue
                if value is True:
                    locked.add(field)
                elif value is False:
                    locked.discard(field)
            selected = select_restaurant_scan_values(scan, selections=selections, mode=mode, locked_fields=locked)
            now = _now_iso()
            audit_changes = []
            for accepted in selected["accepted"]:
                field, candidate = accepted["field"], accepted["candidate"]
                store_field = STORE_FIELD_KEYS[field]
                previous = deepcopy(restaurant.get(store_field))
                value = deepcopy(selected["values"][field])
                if field in BOOLEAN_FIELDS:
                    value = _normalize_value(field, value)
                if field in {"website_url", "menu_url", "image_url"}:
                    value = _normalize_url(value)
                if field == "image_url":
                    stored_logo = _store_approved_logo(candidate, restaurant_id)
                    created_logo_paths.extend([stored_logo.get("logo_path"), stored_logo.get("logo_thumbnail_path")])
                    value = stored_logo["logo_url"]
                    restaurant["logo_path"] = stored_logo["logo_path"]
                    restaurant["logo_thumbnail_path"] = stored_logo["logo_thumbnail_path"]
                    restaurant["logo_original_source_url"] = stored_logo["original_url"]
                    restaurant["logo_source_page_url"] = candidate.get("source_url")
                    restaurant["logo_source_type"] = candidate.get("source_type")
                    restaurant["logo_source_attribution"] = candidate.get("evidence")
                restaurant[store_field] = value
                if field == "website_url":
                    restaurant["website_url"] = value
                elif field == "menu_url":
                    restaurant["menu_url"] = value
                    menus = [item for item in store.get("menus", []) if _clean(item.get("restaurant_id")) == restaurant_id]
                    if menus:
                        menus[0]["source_url"] = value
                        menus[0]["updated_at"] = now
                elif field == "image_url":
                    restaurant["logo"] = value
                audit_changes.append({
                    "field": field, "previous_value": previous, "new_value": value,
                    "source_url": candidate.get("source_url"), "source_type": candidate.get("source_type"),
                    "extraction_method": candidate.get("extraction_method"), "confidence": candidate.get("confidence"),
                })
            restaurant["restaurant_information_locked_fields"] = sorted(locked)
            restaurant["restaurant_information_last_scanned_at"] = scan.get("scanned_at") or now
            restaurant["restaurant_information_scan_summary"] = deepcopy(scan.get("summary") or {})
            if audit_changes:
                history = restaurant.get("restaurant_information_audit")
                history = history if isinstance(history, list) else []
                history.append({
                    "scan_id": scan.get("scan_id"), "timestamp": now, "user_id": _clean(active_user_id()),
                    "mode": mode, "changes": audit_changes,
                })
                restaurant["restaurant_information_audit"] = history[-50:]
                restaurant["updated_at"] = now
            menu_store_service.save_menu_store(store)
        except Exception as exc:
            _restore_file(path, snapshot)
            for logo_path in {item for item in created_logo_paths if item}:
                try:
                    Path(logo_path).unlink(missing_ok=True)
                except OSError:
                    pass
            return {"ok": False, "error": f"Restaurant information changes were rolled back: {exc}"}
    from PushShoppingList.services.recipe_edit_service import get_editable_restaurant
    saved = get_editable_restaurant(restaurant_id)
    return {
        "ok": True, "restaurant": saved.get("restaurant", {}),
        "applied_fields": [item["field"] for item in selected["accepted"]],
        "rejected": selected["rejected"], "locked_fields": sorted(locked),
    }
