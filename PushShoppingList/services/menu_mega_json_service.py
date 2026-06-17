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
NUTRITION_INFERENCE_FIELDS = [
    "serving_basis",
    "calories",
    "carbohydrates",
    "protein",
    "fat",
    "saturated_fat",
    "polyunsaturated_fat",
    "monounsaturated_fat",
    "trans_fat",
    "cholesterol",
    "sodium",
    "potassium",
    "fiber",
    "sugar",
    "vitamin_a",
    "vitamin_c",
    "calcium",
    "iron",
]


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


def cartana_menu_item_order_url(source_url, menu_id="", menu_item_id=""):
    menu_id = clean_text(menu_id)
    menu_item_id = clean_text(menu_item_id)
    if not menu_id or not menu_item_id:
        return ""

    parsed = urlparse(str(source_url or ""))
    if not parsed.scheme or not parsed.netloc or not parsed.path.endswith("menu_home.action"):
        return ""

    res_input = ""
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "resInput" and value:
            res_input = value
            break
    if not res_input:
        return ""

    base_path = parsed.path.rsplit("/", 1)[0] + "/"
    item_path = urljoin(base_path, "menuItem_home.action")
    query = urlencode({
        "resInput": res_input,
        "menuIdInput": menu_id,
        "menuItemIdInput": menu_item_id,
        "orderType": "null",
    })
    return urlunparse((parsed.scheme, parsed.netloc, item_path, "", query, ""))


def item_deep_link(source_url, item, menu_item_id):
    item = item if isinstance(item, dict) else {}
    explicit = clean_text(item.get("menu_order_url") or item.get("deep_link_url") or item.get("item_url") or item.get("url"))
    if explicit:
        return absolute_url(source_url, explicit)

    if not menu_item_id:
        return ""

    order_url = cartana_menu_item_order_url(source_url, item.get("menu_id"), menu_item_id)
    if order_url:
        return order_url

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


def text_list_for_menu_metadata(value):
    return ", ".join(clean_text(item) for item in normalize_list(value) if clean_text(item))


def restaurant_metadata_from_mega_json(mega_json):
    mega_json = mega_json if isinstance(mega_json, dict) else {}
    source = mega_json.get("source") if isinstance(mega_json.get("source"), dict) else {}
    restaurant = mega_json.get("restaurant") if isinstance(mega_json.get("restaurant"), dict) else {}
    metadata = restaurant.get("metadata") if isinstance(restaurant.get("metadata"), dict) else {}
    restaurant_name = clean_text(
        metadata.get("restaurant_name")
        or metadata.get("name")
        or (restaurant.get("name") if clean_text(restaurant.get("name")).lower() != "restaurant menu" else "")
    )
    return {
        "restaurant_name": restaurant_name,
        "restaurant_website_url": clean_text(
            restaurant.get("website")
            or metadata.get("restaurant_website_url")
            or metadata.get("website_url")
            or metadata.get("website")
        ),
        "source_menu_url": clean_text(
            metadata.get("source_menu_url")
            or source.get("source_url")
            or source.get("final_url")
        ),
        "restaurant_cuisine_tags": clean_text(
            text_list_for_menu_metadata(metadata.get("cuisine_tags"))
            or text_list_for_menu_metadata(metadata.get("cuisines"))
        ),
        "restaurant_phone": clean_text(restaurant.get("phone") or metadata.get("phone")),
        "restaurant_address": clean_text(
            restaurant.get("address")
            or metadata.get("full_address")
            or metadata.get("address")
            or metadata.get("address_line")
        ),
        "restaurant_hours_text": clean_text(
            text_list_for_menu_metadata(restaurant.get("hours"))
            or metadata.get("hours_text")
            or text_list_for_menu_metadata(metadata.get("hours"))
        ),
        "restaurant_current_status": clean_text(metadata.get("current_status") or metadata.get("status")),
        "restaurant_promotions": clean_text(
            metadata.get("rewards_text")
            or text_list_for_menu_metadata(metadata.get("promotions"))
            or metadata.get("rewards")
        ),
        "restaurant_online_payment_available": (
            metadata.get("online_payment_available") if "online_payment_available" in metadata else None
        ),
        "restaurant_delivery_available": (
            metadata.get("delivery_available") if "delivery_available" in metadata else None
        ),
    }


def normalize_equipment_prediction_records(value):
    records = []
    for item in normalize_list(value):
        if isinstance(item, dict):
            name = clean_text(
                item.get("name")
                or item.get("equipment")
                or item.get("text")
                or item.get("item")
            )
            if not name:
                continue
            record = {"name": name}
            category = clean_text(item.get("category") or item.get("equipment_category") or "")
            if category:
                record["category"] = category
            reason = clean_text(item.get("reason") or item.get("note") or "")
            if reason:
                record["reason"] = reason
            try:
                confidence = float(item.get("confidence"))
            except (TypeError, ValueError):
                confidence = None
            if confidence is not None:
                record["confidence"] = max(0.0, min(1.0, confidence))
        else:
            name = clean_text(item)
            if not name:
                continue
            record = {"name": name}

        if record not in records:
            records.append(record)

    return records


def default_recipe_inference():
    return {
        "status": "not_generated",
        "ingredients": [],
        "equipment": [],
        "instructions": [],
        "servings": None,
        "confidence": None,
        "model": None,
        "generated_at": None,
        "notes": [],
    }


def default_nutrition_inference():
    return {
        "status": "not_generated",
        **{field: None for field in NUTRITION_INFERENCE_FIELDS},
        "other": [],
        "servings": None,
        "calories_per_serving": None,
        "protein_g": None,
        "carbs_g": None,
        "fat_g": None,
        "sodium_mg": None,
        "model": None,
        "generated_at": None,
        "notes": [],
    }


def default_pdf_generation():
    return {
        "status": "not_generated",
        "generated_pdf_path": "",
        "generated_cloudflare_pdf_path": "",
        "source_pdf_path": "",
        "source_cloudflare_pdf_path": "",
        "generated_at": None,
        "notes": [],
    }


def normalize_placeholder(value, default_factory):
    default = default_factory()
    if isinstance(value, dict):
        default.update(value)
    return default


def normalize_menu_item_placeholders(item):
    item = item if isinstance(item, dict) else {}
    item["recipe_inference"] = normalize_placeholder(
        item.get("recipe_inference"),
        default_recipe_inference,
    )
    item["recipe_inference"]["equipment"] = normalize_equipment_prediction_records(
        item["recipe_inference"].get("equipment")
    )
    item["nutrition_inference"] = normalize_placeholder(
        item.get("nutrition_inference"),
        default_nutrition_inference,
    )
    item["pdf_generation"] = normalize_placeholder(
        item.get("pdf_generation"),
        default_pdf_generation,
    )
    return item


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
            deep_link_url = item_deep_link(source_url, item, menu_item_id)

            canonical_item = {
                "menu_item_id": menu_item_id,
                "display_order": safe_int(item.get("display_order") or item.get("index"), item_index) + (
                    0 if item.get("display_order") not in (None, "") else 1
                ),
                "name": name,
                "description": description,
                "price": price_number(price_text),
                "price_text": price_text,
                "currency": clean_text(item.get("currency") or "USD") or "USD",
                "deep_link_url": deep_link_url,
                "menu_order_url": deep_link_url,
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
                "recipe_inference": default_recipe_inference(),
                "nutrition_inference": default_nutrition_inference(),
                "pdf_generation": default_pdf_generation(),
            }
            for optional_field in (
                "normalized_name",
                "normalized_section_name",
                "item_type",
                "broad_category",
                "duplicate_group_id",
                "should_create_recipe_stub",
                "cleanup_confidence",
                "cleanup_notes",
            ):
                if optional_field in item:
                    canonical_item[optional_field] = item.get(optional_field)
            canonical_items.append(normalize_menu_item_placeholders(canonical_item))

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

    for section in sections:
        if not isinstance(section, dict):
            continue
        items = section.get("items")
        if not isinstance(items, list):
            section["items"] = []
            continue
        for item in items:
            if isinstance(item, dict):
                normalize_menu_item_placeholders(item)

    item_count = sum(
        len(section.get("items") or [])
        for section in sections
        if isinstance(section, dict)
    )
    extraction = mega_json.setdefault("extraction", {})
    extraction["item_count"] = item_count
    extraction["section_count"] = len(sections)
    extraction.setdefault("duplicate_count", 0)
    extraction.setdefault("method", "deterministic_html_first")
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


def snapshot_summary(record):
    return {
        "id": record["id"],
        "source_url": record["source_url"],
        "final_url": record["final_url"],
        "saved_at": record["saved_at"],
        "updated_at": record.get("updated_at", record["saved_at"]),
        "job_id": record["job_id"],
        "import_job_id": record.get("import_job_id", record["job_id"]),
        "cookbook_id": record.get("cookbook_id", ""),
        "cookbook_name": record.get("cookbook_name", ""),
        "item_count": record["item_count"],
        "section_count": record["section_count"],
        "duplicate_count": record.get("duplicate_count", 0),
        "extraction_status": record["extraction_status"],
        "used_openai": bool(record.get("used_openai")),
        "openai_model": record.get("openai_model"),
    }


def write_snapshot_record(record):
    (snapshot_dir() / f"{record['id']}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    index = load_snapshot_index()
    summaries = [
        item
        for item in (index.get("snapshots") if isinstance(index.get("snapshots"), list) else [])
        if isinstance(item, dict) and item.get("id") != record["id"]
    ]
    summaries.insert(0, snapshot_summary(record))
    index["snapshots"] = summaries[:200]
    save_snapshot_index(index)
    return record


def save_menu_mega_json_snapshot(
    mega_json,
    job_id="",
    extraction_status="saved",
    import_job_id="",
    cookbook_id="",
    cookbook_name="",
):
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
        "created_at": saved_at,
        "updated_at": saved_at,
        "job_id": clean_text(job_id),
        "import_job_id": clean_text(import_job_id or job_id),
        "cookbook_id": clean_text(cookbook_id),
        "cookbook_name": clean_text(cookbook_name),
        "schema_version": clean_text(mega_json.get("schema_version") or SCHEMA_VERSION),
        "menu_mega_json": mega_json,
        "item_count": safe_int(extraction.get("item_count"), 0),
        "section_count": safe_int(extraction.get("section_count"), 0),
        "duplicate_count": safe_int(extraction.get("duplicate_count"), 0),
        "extraction_status": clean_text(extraction_status or "saved"),
        "extraction_method": clean_text(extraction.get("method") or ""),
        "used_openai": bool(extraction.get("used_openai")),
        "openai_model": extraction.get("openai_model"),
        "extraction_warnings": list(extraction.get("warnings") or []),
        "extraction_errors": list(extraction.get("errors") or []),
    }
    return write_snapshot_record(record)


def update_menu_mega_json_snapshot(snapshot_id, mega_json=None, **updates):
    snapshot_id = clean_text(snapshot_id)
    record = load_menu_mega_json_snapshot(snapshot_id)
    if not record:
        return None

    if isinstance(mega_json, dict):
        mega_json = validate_mega_menu_json(mega_json)
        mega_json["snapshot_id"] = snapshot_id
        source = mega_json.get("source") if isinstance(mega_json.get("source"), dict) else {}
        extraction = mega_json.get("extraction") if isinstance(mega_json.get("extraction"), dict) else {}
        record.update({
            "source_url": clean_text(source.get("source_url") or record.get("source_url") or ""),
            "final_url": clean_text(source.get("final_url") or source.get("source_url") or record.get("final_url") or ""),
            "fetched_at": clean_text(source.get("fetched_at") or record.get("fetched_at") or ""),
            "schema_version": clean_text(mega_json.get("schema_version") or SCHEMA_VERSION),
            "menu_mega_json": mega_json,
            "item_count": safe_int(extraction.get("item_count"), 0),
            "section_count": safe_int(extraction.get("section_count"), 0),
            "duplicate_count": safe_int(extraction.get("duplicate_count"), 0),
            "extraction_method": clean_text(extraction.get("method") or record.get("extraction_method") or ""),
            "used_openai": bool(extraction.get("used_openai")),
            "openai_model": extraction.get("openai_model"),
            "extraction_warnings": list(extraction.get("warnings") or []),
            "extraction_errors": list(extraction.get("errors") or []),
        })

    for key, value in updates.items():
        if value is not None:
            record[key] = value
    record["updated_at"] = now_iso()
    return write_snapshot_record(record)


def update_mega_menu_json_with_cleanup(mega_json, cleaned_sections, cleanup_debug=None):
    mega_json = validate_mega_menu_json(mega_json)
    cleanup_debug = cleanup_debug if isinstance(cleanup_debug, dict) else {}
    cleaned_items = []
    for section in cleaned_sections or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if isinstance(item, dict):
                cleaned_items.append((section, item))

    item_index = 0
    for section in mega_json.get("menu", {}).get("sections", []):
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item_index >= len(cleaned_items):
                item_index += 1
                continue
            cleaned_section, cleaned_item = cleaned_items[item_index]
            normalized_name = clean_text(cleaned_item.get("item_name") or "")
            normalized_section = clean_text(
                cleaned_item.get("menu_section")
                or cleaned_item.get("section_name")
                or cleaned_section.get("section_name")
                or ""
            )
            item["normalized_name"] = normalized_name
            item["normalized_section_name"] = normalized_section
            item["item_type"] = clean_text(cleaned_item.get("item_type") or item.get("item_type") or "unknown") or "unknown"
            item["broad_category"] = clean_text(cleaned_item.get("broad_category") or item.get("broad_category") or "")
            if cleaned_item.get("duplicate_group_id"):
                item["duplicate_group_id"] = clean_text(cleaned_item.get("duplicate_group_id"))
            elif cleaned_item.get("duplicate_of_index") not in (None, ""):
                item["duplicate_group_id"] = f"duplicate-of-{cleaned_item.get('duplicate_of_index')}"
            if "should_create_recipe" in cleaned_item:
                item["should_create_recipe_stub"] = bool(cleaned_item.get("should_create_recipe"))
            if cleaned_item.get("skip_reason"):
                item["cleanup_notes"] = [clean_text(cleaned_item.get("skip_reason"))]
            predicted_equipment = normalize_equipment_prediction_records(
                cleaned_item.get("predicted_equipment")
                or cleaned_item.get("equipment")
            )
            if predicted_equipment:
                item["predicted_equipment"] = predicted_equipment
                recipe_inference = normalize_placeholder(
                    item.get("recipe_inference"),
                    default_recipe_inference,
                )
                recipe_inference["equipment"] = predicted_equipment
                if recipe_inference.get("status") == "not_generated":
                    recipe_inference["status"] = "equipment_predicted"
                recipe_inference["model"] = cleanup_debug.get("model") or recipe_inference.get("model")
                recipe_inference["generated_at"] = recipe_inference.get("generated_at") or now_iso()
                notes = normalize_list(recipe_inference.get("notes"))
                note = "Equipment predicted from menu item metadata during cleanup."
                if note not in notes:
                    notes.append(note)
                recipe_inference["notes"] = notes
                item["recipe_inference"] = recipe_inference
            metadata = item.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["item_type"] = item["item_type"]
                metadata["broad_category"] = item["broad_category"]
                metadata["normalized_name"] = normalized_name
                metadata["normalized_section_name"] = normalized_section
                if predicted_equipment:
                    metadata["predicted_equipment_count"] = len(predicted_equipment)
            item_index += 1

    extraction = mega_json.setdefault("extraction", {})
    if int(cleanup_debug.get("openai_calls_used") or 0) > 0:
        extraction["used_openai"] = True
        extraction["openai_model"] = cleanup_debug.get("model")
        warnings = list(extraction.get("warnings") or [])
        if cleanup_debug.get("error"):
            warnings.append("AI cleanup failed, but deterministic menu extraction succeeded.")
        extraction["warnings"] = warnings
    return validate_mega_menu_json(mega_json)


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
    restaurant_metadata = restaurant_metadata_from_mega_json(mega_json)
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
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            original_item_name = clean_text(item.get("name") or item.get("item_name") or "")
            item_name = clean_text(
                item.get("normalized_name")
                or metadata.get("normalized_name")
                or original_item_name
            )
            if not item_name:
                continue
            original_section_name = clean_text(
                item.get("original_section_name")
                or section.get("section_name")
                or f"Menu Section {section_index + 1}"
            )
            normalized_section_name = clean_text(
                item.get("normalized_section_name")
                or metadata.get("normalized_section_name")
                or section_name
            )
            duplicate_group_id = clean_text(item.get("duplicate_group_id") or "")
            cleanup_notes = normalize_list(item.get("cleanup_notes"))
            recipe_inference = normalize_placeholder(
                item.get("recipe_inference"),
                default_recipe_inference,
            )
            predicted_equipment = normalize_equipment_prediction_records(
                item.get("predicted_equipment")
                or recipe_inference.get("equipment")
            )
            if predicted_equipment:
                recipe_inference["equipment"] = predicted_equipment
            item_display_order = safe_int(item.get("display_order"), item_index + 1)
            unpacked_item = {
                "item_name": item_name,
                "menu_section": normalized_section_name,
                "section_name": normalized_section_name,
                "section_id": section_id,
                "section_display_order": section_display_order,
                "item_display_order": item_display_order,
                "display_order": item_display_order,
                "original_item_name": original_item_name,
                "original_section_name": original_section_name,
                "normalized_name": item_name,
                "normalized_section_name": normalized_section_name,
                "description": clean_text(item.get("description") or ""),
                "price": clean_text(item.get("price_text") or item.get("price") or ""),
                "price_text": clean_text(item.get("price_text") or ""),
                "currency": clean_text(item.get("currency") or "USD") or "USD",
                "source_url": source_url,
                "deep_link_url": clean_text(item.get("deep_link_url") or ""),
                "menu_order_url": clean_text(item.get("menu_order_url") or item.get("deep_link_url") or ""),
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
                "item_type": clean_text(item.get("item_type") or metadata.get("item_type") or "unknown") or "unknown",
                "broad_category": clean_text(item.get("broad_category") or metadata.get("broad_category") or ""),
                "duplicate_group_id": duplicate_group_id,
                "cleanup_notes": cleanup_notes,
                "predicted_equipment": predicted_equipment,
                "recipe_inference": recipe_inference,
                "parent_menu_snapshot_id": snapshot_id,
                "menu_mega_snapshot_id": snapshot_id,
            }
            for key, value in restaurant_metadata.items():
                if value not in (None, "", []):
                    unpacked_item[key] = value
            if item.get("should_create_recipe_stub") is False:
                unpacked_item["should_create_recipe"] = False
                unpacked_item["skip_reason"] = clean_text((cleanup_notes or ["not_recipe_item"])[0])
            if duplicate_group_id.startswith("duplicate-of-"):
                unpacked_item["duplicate_of_index"] = duplicate_group_id.replace("duplicate-of-", "", 1)
            items.append(unpacked_item)

        if items:
            sections.append({
                "section_id": section_id,
                "section_name": section_name,
                "section_description": clean_text(section.get("section_description") or ""),
                "display_order": section_display_order,
                "items": items,
            })

    return sections
