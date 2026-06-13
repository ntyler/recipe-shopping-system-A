import json
import re
import uuid
from datetime import datetime
from datetime import timezone
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlunparse

from bs4 import BeautifulSoup

from PushShoppingList.services.storage_service import workspace_data_root


SCHEMA_VERSION = "menu_mega_json_v1"
SNAPSHOT_DIR_NAME = "menu_mega_json_snapshots"
SNAPSHOT_INDEX_FILE = "menu_mega_json_snapshots.json"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def price_number(value):
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def snapshot_dir():
    path = workspace_data_root() / SNAPSHOT_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_index_path():
    return workspace_data_root() / SNAPSHOT_INDEX_FILE


def domain_for_url(url):
    parsed = urlparse(str(url or ""))
    return parsed.netloc.lower()


def absolute_url(base_url, value):
    text = clean_text(value)
    if not text:
        return ""
    return urljoin(str(base_url or ""), text)


def item_deep_link(source_url, item, menu_item_id):
    item = item if isinstance(item, dict) else {}
    explicit = clean_text(item.get("deep_link_url") or item.get("item_url") or item.get("url"))
    if explicit:
        return absolute_url(source_url, explicit)

    if not menu_item_id:
        return ""

    parsed = urlparse(str(source_url or ""))
    if not parsed.scheme or not parsed.netloc:
        return ""

    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("menu_item_id", menu_item_id))
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(query),
        "",
    ))


def html_capture(html_text, source_url):
    soup = BeautifulSoup(html_text or "", "html.parser")
    page_title = clean_text(soup.title.string if soup.title and soup.title.string else "")
    links = []
    images = []
    structured_data = []

    for link in soup.find_all("a", href=True):
        href = absolute_url(source_url, link.get("href"))
        label = clean_text(link.get_text(" ", strip=True))
        if href:
            links.append({"href": href, "text": label})
        if len(links) >= 250:
            break

    for image in soup.find_all("img"):
        src = absolute_url(source_url, image.get("src") or image.get("data-src") or "")
        if not src:
            continue
        images.append({
            "src": src,
            "alt": clean_text(image.get("alt") or ""),
        })
        if len(images) >= 250:
            break

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.get_text("\n", strip=True)
        if not text:
            continue
        try:
            structured_data.append(json.loads(text))
        except (TypeError, ValueError, json.JSONDecodeError):
            structured_data.append({"raw": text[:5000]})

    return {
        "page_title": page_title,
        "links": links,
        "images": images,
        "structured_data": structured_data,
    }


def menu_item_id_for(section_id, section_index, item_index, item):
    item = item if isinstance(item, dict) else {}
    explicit = clean_text(item.get("menu_item_id") or item.get("item_id") or item.get("id"))
    if explicit:
        return explicit
    return f"{section_id}-item-{item_index + 1:03d}"


def normalize_tags(item):
    item = item if isinstance(item, dict) else {}
    tags = []
    for value in item.get("tags") or item.get("dietary_tags") or []:
        text = clean_text(value)
        if text and text not in tags:
            tags.append(text)
    if item.get("is_spicy") and "Spicy" not in tags:
        tags.append("Spicy")
    if item.get("is_veggie") and "Vegetarian" not in tags:
        tags.append("Vegetarian")
    return tags


def normalize_list(value):
    return value if isinstance(value, list) else []


def build_mega_menu_json(
    source_url,
    sections,
    extracted_text="",
    diagnostics=None,
    html_text="",
    html_snapshot_path="",
    fetched_at="",
):
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    source_url = clean_text(source_url)
    final_url = clean_text(diagnostics.get("final_url") or source_url)
    capture = html_capture(html_text, final_url or source_url)
    restaurant = diagnostics.get("restaurant") if isinstance(diagnostics.get("restaurant"), dict) else {}
    restaurant_name = clean_text(
        restaurant.get("restaurant_name")
        or restaurant.get("name")
        or capture.get("page_title")
        or "Restaurant Menu"
    )

    canonical_sections = []
    duplicate_keys = set()
    duplicate_count = 0
    item_count = 0

    for section_index, section in enumerate(sections if isinstance(sections, list) else []):
        if not isinstance(section, dict):
            continue
        section_name = clean_text(
            section.get("section_name")
            or section.get("menu_section")
            or section.get("name")
            or f"Menu Section {section_index + 1}"
        )
        section_id = clean_text(
            section.get("section_id")
            or section.get("menu_section_id")
            or f"section-{section_index + 1:03d}"
        )
        menu_id = clean_text(section.get("menu_id") or "")
        canonical_items = []

        for item_index, item in enumerate(section.get("items") or []):
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name") or item.get("item_name") or item.get("title"))
            if not name:
                continue
            price_text = clean_text(item.get("price_text") or item.get("menu_price") or item.get("price"))
            menu_item_id = menu_item_id_for(section_id, section_index, item_index, item)
            description = clean_text(
                item.get("description")
                or item.get("menu_description")
                or item.get("item_description")
                or ""
            )
            raw_text = clean_text(
                item.get("raw_text")
                or " | ".join(part for part in (section_name, name, description, price_text) if part)
            )
            duplicate_key = "|".join([section_name.lower(), name.lower(), description.lower(), price_text.lower()])
            if duplicate_key in duplicate_keys:
                duplicate_count += 1
            elif duplicate_key.strip("|"):
                duplicate_keys.add(duplicate_key)
            item_count += 1

            canonical_items.append({
                "menu_item_id": menu_item_id,
                "display_order": safe_int(item.get("display_order") or item.get("index"), item_index) + (
                    0 if item.get("display_order") not in (None, "") else 1
                ),
                "name": name,
                "description": description,
                "price": price_number(price_text),
                "price_text": price_text,
                "currency": clean_text(item.get("currency") or "USD") or "USD",
                "deep_link_url": item_deep_link(source_url, item, menu_item_id),
                "image_url": absolute_url(source_url, item.get("image_url") or item.get("image") or ""),
                "tags": normalize_tags(item),
                "options": normalize_list(item.get("options")),
                "modifiers": normalize_list(item.get("modifiers")),
                "raw_text": raw_text,
                "raw_html": str(item.get("raw_html") or ""),
                "metadata": {
                    "restaurant_id": clean_text(item.get("restaurant_id") or restaurant.get("restaurant_id") or ""),
                    "menu_id": clean_text(item.get("menu_id") or menu_id),
                    "menu_section_id": clean_text(item.get("menu_section_id") or section_id),
                    "is_spicy": bool(item.get("is_spicy")),
                    "is_veggie": bool(item.get("is_veggie")),
                    "item_type": clean_text(item.get("item_type") or ""),
                    "broad_category": clean_text(item.get("broad_category") or ""),
                    "source_index": item_index,
                },
            })

        if canonical_items:
            canonical_sections.append({
                "section_id": section_id,
                "section_name": section_name,
                "section_description": clean_text(section.get("section_description") or section.get("description") or ""),
                "display_order": safe_int(section.get("display_order"), section_index + 1),
                "items": canonical_items,
            })

    mega_json = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "source_url": source_url,
            "final_url": final_url,
            "domain": domain_for_url(final_url or source_url),
            "fetched_at": clean_text(fetched_at or diagnostics.get("fetched_at") or now_iso()),
            "source_type": "restaurant_menu_url",
            "http_status": diagnostics.get("http_status"),
            "content_type": clean_text(diagnostics.get("content_type") or ""),
            "page_title": capture.get("page_title") or clean_text(diagnostics.get("page_title") or ""),
        },
        "restaurant": {
            "name": restaurant_name,
            "address": clean_text(restaurant.get("full_address") or restaurant.get("address") or ""),
            "phone": clean_text(restaurant.get("phone") or ""),
            "website": clean_text(restaurant.get("restaurant_website_url") or restaurant.get("website") or ""),
            "hours": normalize_list(restaurant.get("hours")),
            "metadata": {
                key: value
                for key, value in restaurant.items()
                if key not in {"restaurant_name", "name", "full_address", "address", "phone", "restaurant_website_url", "website", "hours"}
            },
        },
        "menu": {
            "menu_id": clean_text(diagnostics.get("menu_id") or ""),
            "menu_name": clean_text(diagnostics.get("menu_name") or f"{restaurant_name} Menu"),
            "sections": canonical_sections,
        },
        "raw_capture": {
            "html_snapshot_path": clean_text(html_snapshot_path or diagnostics.get("html_snapshot_path") or ""),
            "text_snapshot": str(extracted_text or ""),
            "structured_data": capture.get("structured_data") or [],
            "links": capture.get("links") or [],
            "images": capture.get("images") or [],
        },
        "extraction": {
            "method": clean_text(diagnostics.get("menu_extraction_source") or "deterministic_html_first"),
            "used_openai": False,
            "openai_model": None,
            "warnings": list(diagnostics.get("warnings") or []),
            "errors": list(diagnostics.get("errors") or []),
            "item_count": item_count,
            "section_count": len(canonical_sections),
            "duplicate_count": duplicate_count,
        },
    }
    return validate_mega_menu_json(mega_json)


def validate_mega_menu_json(mega_json):
    mega_json = mega_json if isinstance(mega_json, dict) else {}
    warnings = []
    errors = []

    if mega_json.get("schema_version") != SCHEMA_VERSION:
        mega_json["schema_version"] = SCHEMA_VERSION
        warnings.append("schema_version_normalized")

    sections = (
        mega_json.get("menu", {}).get("sections")
        if isinstance(mega_json.get("menu"), dict)
        else []
    )
    if not isinstance(sections, list):
        sections = []
        mega_json.setdefault("menu", {})["sections"] = sections
        errors.append("menu_sections_missing")

    item_count = sum(
        len(section.get("items") or [])
        for section in sections
        if isinstance(section, dict)
    )
    extraction = mega_json.setdefault("extraction", {})
    extraction["item_count"] = item_count
    extraction["section_count"] = len(sections)
    extraction.setdefault("duplicate_count", 0)
    extraction.setdefault("used_openai", False)
    extraction.setdefault("openai_model", None)
    extraction["warnings"] = [*list(extraction.get("warnings") or []), *warnings]
    extraction["errors"] = [*list(extraction.get("errors") or []), *errors]
    return mega_json


def load_snapshot_index():
    path = snapshot_index_path()
    if not path.exists():
        return {"snapshots": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"snapshots": []}
    return payload if isinstance(payload, dict) else {"snapshots": []}


def save_snapshot_index(payload):
    path = snapshot_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def save_menu_mega_json_snapshot(mega_json, job_id="", extraction_status="saved"):
    mega_json = validate_mega_menu_json(mega_json)
    snapshot_id = clean_text(mega_json.get("snapshot_id") or uuid.uuid4().hex)
    saved_at = now_iso()
    mega_json["snapshot_id"] = snapshot_id
    source = mega_json.get("source") if isinstance(mega_json.get("source"), dict) else {}
    extraction = mega_json.get("extraction") if isinstance(mega_json.get("extraction"), dict) else {}
    record = {
        "id": snapshot_id,
        "snapshot_id": snapshot_id,
        "source_url": clean_text(source.get("source_url") or ""),
        "final_url": clean_text(source.get("final_url") or source.get("source_url") or ""),
        "fetched_at": clean_text(source.get("fetched_at") or ""),
        "saved_at": saved_at,
        "job_id": clean_text(job_id),
        "menu_mega_json": mega_json,
        "item_count": safe_int(extraction.get("item_count"), 0),
        "section_count": safe_int(extraction.get("section_count"), 0),
        "extraction_status": clean_text(extraction_status or "saved"),
        "extraction_warnings": list(extraction.get("warnings") or []),
        "extraction_errors": list(extraction.get("errors") or []),
    }
    (snapshot_dir() / f"{snapshot_id}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    index = load_snapshot_index()
    summaries = [
        item
        for item in (index.get("snapshots") if isinstance(index.get("snapshots"), list) else [])
        if isinstance(item, dict) and item.get("id") != snapshot_id
    ]
    summaries.insert(0, {
        "id": snapshot_id,
        "source_url": record["source_url"],
        "final_url": record["final_url"],
        "saved_at": record["saved_at"],
        "job_id": record["job_id"],
        "item_count": record["item_count"],
        "section_count": record["section_count"],
        "extraction_status": record["extraction_status"],
    })
    index["snapshots"] = summaries[:200]
    save_snapshot_index(index)
    return record


def load_menu_mega_json_snapshot(snapshot_id):
    snapshot_id = clean_text(snapshot_id)
    if not snapshot_id or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", snapshot_id):
        return None
    path = snapshot_dir() / f"{snapshot_id}.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def unpack_mega_menu_json_to_sections(mega_json, snapshot_id=""):
    mega_json = mega_json if isinstance(mega_json, dict) else {}
    snapshot_id = clean_text(snapshot_id or mega_json.get("snapshot_id") or "")
    source = mega_json.get("source") if isinstance(mega_json.get("source"), dict) else {}
    source_url = clean_text(source.get("source_url") or source.get("final_url") or "")
    menu = mega_json.get("menu") if isinstance(mega_json.get("menu"), dict) else {}
    sections = []

    for section_index, section in enumerate(menu.get("sections") or []):
        if not isinstance(section, dict):
            continue
        section_name = clean_text(section.get("section_name") or f"Menu Section {section_index + 1}")
        section_id = clean_text(section.get("section_id") or f"section-{section_index + 1:03d}")
        section_display_order = safe_int(section.get("display_order"), section_index + 1)
        items = []

        for item_index, item in enumerate(section.get("items") or []):
            if not isinstance(item, dict):
                continue
            item_name = clean_text(item.get("name") or item.get("item_name") or "")
            if not item_name:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            item_display_order = safe_int(item.get("display_order"), item_index + 1)
            items.append({
                "item_name": item_name,
                "menu_section": section_name,
                "section_name": section_name,
                "section_id": section_id,
                "section_display_order": section_display_order,
                "item_display_order": item_display_order,
                "display_order": item_display_order,
                "description": clean_text(item.get("description") or ""),
                "price": clean_text(item.get("price_text") or item.get("price") or ""),
                "price_text": clean_text(item.get("price_text") or ""),
                "currency": clean_text(item.get("currency") or "USD") or "USD",
                "source_url": source_url,
                "deep_link_url": clean_text(item.get("deep_link_url") or ""),
                "image_url": clean_text(item.get("image_url") or ""),
                "menu_item_id": clean_text(item.get("menu_item_id") or ""),
                "menu_id": clean_text(menu.get("menu_id") or metadata.get("menu_id") or ""),
                "menu_section_id": clean_text(metadata.get("menu_section_id") or section_id),
                "restaurant_id": clean_text(metadata.get("restaurant_id") or ""),
                "tags": normalize_list(item.get("tags")),
                "options": normalize_list(item.get("options")),
                "modifiers": normalize_list(item.get("modifiers")),
                "raw_text": clean_text(item.get("raw_text") or ""),
                "raw_html": str(item.get("raw_html") or ""),
                "item_type": clean_text(metadata.get("item_type") or "unknown") or "unknown",
                "broad_category": clean_text(metadata.get("broad_category") or ""),
                "parent_menu_snapshot_id": snapshot_id,
                "menu_mega_snapshot_id": snapshot_id,
            })

        if items:
            sections.append({
                "section_id": section_id,
                "section_name": section_name,
                "section_description": clean_text(section.get("section_description") or ""),
                "display_order": section_display_order,
                "items": items,
            })

    return sections
