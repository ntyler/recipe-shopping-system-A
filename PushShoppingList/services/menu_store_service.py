import json
import re
import threading
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

from PushShoppingList.services.storage_service import scoped_package_path


MENU_STORE_FILE = scoped_package_path("restaurant_menus.json")
MENU_STORE_LOCK = threading.RLock()
MENU_SOURCE_ITEM_QUERY_KEYS = {
    "menu_item",
    "menu_item_id",
    "menuidinput",
    "menuitemidinput",
    "ordertype",
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_text(value):
    return " ".join(str(value or "").strip().split())


def clean_nullable_text(value):
    value = clean_text(value)
    return value if value else None


def clean_text_list(value):
    if isinstance(value, str):
        value = re.split(r"[,;\n]+", value)

    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for item in value:
        text = clean_text(item)
        key = text.lower()
        if text and key not in seen:
            items.append(text)
            seen.add(key)
    return items


def clean_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_price(value):
    if value in (None, ""):
        return None
    text = clean_text(value)
    if not text:
        return None
    try:
        return f"${float(text.replace('$', '').replace(',', '')):.2f}"
    except ValueError:
        return text


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def empty_store():
    return {
        "restaurants": [],
        "menus": [],
        "sections": [],
        "items": [],
        "pdf_logs": [],
    }


def menu_store_file():
    path = Path(MENU_STORE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_store(payload):
    payload = payload if isinstance(payload, dict) else {}
    normalized = empty_store()
    for key in normalized:
        value = payload.get(key)
        normalized[key] = value if isinstance(value, list) else []
    return normalized


def load_menu_store():
    path = menu_store_file()
    if not path.exists():
        return empty_store()

    try:
        return normalize_store(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return empty_store()


def save_menu_store(payload):
    normalized = normalize_store(payload)
    menu_store_file().write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return normalized


def restaurant_name_key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def menu_source_query_key_is_item_specific(key):
    return str(key or "").strip().lower() in MENU_SOURCE_ITEM_QUERY_KEYS


def canonical_menu_source_url(menu_url):
    menu_url = clean_text(menu_url)
    if not menu_url:
        return ""

    try:
        parsed = urlparse(menu_url)
    except ValueError:
        return menu_url.split("#", 1)[0].strip()

    path = parsed.path or ""
    if path.endswith("menuItem_home.action"):
        path = path.rsplit("/", 1)[0] + "/menu_home.action"

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query or "", keep_blank_values=True)
        if not menu_source_query_key_is_item_specific(key)
    ]
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        parsed.params,
        urlencode(query_pairs, doseq=True),
        "",
    )).strip()


def menu_source_identity_key(value):
    canonical = canonical_menu_source_url(value)
    return canonical.lower() if canonical else ""


def restaurant_source_identity_key(restaurant):
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    return menu_source_identity_key(restaurant.get("source_menu_url"))


def restaurant_name_quality_score(value):
    text = clean_text(value)
    if not text:
        return 0
    generic_penalty = 0 if text.lower() in {"restaurant menu", "menu"} else 1000
    return generic_penalty + len(text)


def menu_identity_key(menu, restaurant=None):
    menu = menu if isinstance(menu, dict) else {}
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    source_key = menu_source_identity_key(
        menu.get("source_url")
        or menu.get("source_menu_url")
        or restaurant.get("source_menu_url")
    )
    if source_key:
        return f"source:{source_key}"
    return "|".join([
        clean_text(menu.get("source_type")),
        clean_text(menu.get("source_url")),
        clean_text(menu.get("source_uploaded_file_path")),
        clean_text(menu.get("cookbook_id")),
    ])


def find_restaurant(payload, restaurant_name="", website_url="", source_url=""):
    name_key = restaurant_name_key(restaurant_name)
    website_url = clean_text(website_url)
    source_url = clean_text(source_url)
    source_key = menu_source_identity_key(source_url)

    if source_key:
        for restaurant in payload.get("restaurants", []):
            if restaurant_source_identity_key(restaurant) == source_key:
                return restaurant

    for restaurant in payload.get("restaurants", []):
        if website_url and clean_text(restaurant.get("restaurant_website_url")) == website_url:
            return restaurant
        if source_url and menu_source_identity_key(restaurant.get("source_menu_url")) == source_key:
            return restaurant
        if name_key and restaurant_name_key(restaurant.get("restaurant_name")) == name_key:
            return restaurant

    return None


def find_menu(payload, menu_id):
    menu_id = clean_text(menu_id)
    return next((menu for menu in payload.get("menus", []) if menu.get("id") == menu_id), None)


def find_menu_item(payload, menu_item_id):
    menu_item_id = clean_text(menu_item_id)
    return next((item for item in payload.get("items", []) if item.get("id") == menu_item_id), None)


def find_menu_pdf_log(payload, log_id):
    log_id = clean_text(log_id)
    return next((log for log in payload.get("pdf_logs", []) if log.get("id") == log_id), None)


def find_existing_menu(payload, candidate, restaurant=None):
    target_key = menu_identity_key(candidate, restaurant)
    if not target_key.strip("|"):
        return None

    for menu in payload.get("menus", []):
        menu_restaurant = restaurant_for(payload, menu.get("restaurant_id"))
        if menu_identity_key(menu, menu_restaurant) == target_key:
            return menu

    return None


def normalize_restaurant_fields(raw_restaurant, source_url=""):
    raw_restaurant = raw_restaurant if isinstance(raw_restaurant, dict) else {}
    return {
        "restaurant_name": clean_text(raw_restaurant.get("restaurant_name") or raw_restaurant.get("name")),
        "restaurant_website_url": clean_nullable_text(
            raw_restaurant.get("restaurant_website_url")
            or raw_restaurant.get("website_url")
            or raw_restaurant.get("website")
        ),
        "source_menu_url": clean_nullable_text(source_url or raw_restaurant.get("source_menu_url")),
        "cuisine_tags": clean_text_list(raw_restaurant.get("cuisine_tags") or raw_restaurant.get("cuisines")),
        "phone": clean_nullable_text(raw_restaurant.get("phone")),
        "full_address": clean_nullable_text(raw_restaurant.get("full_address") or raw_restaurant.get("address")),
        "address_line": clean_nullable_text(raw_restaurant.get("address_line")),
        "city": clean_nullable_text(raw_restaurant.get("city")),
        "state": clean_nullable_text(raw_restaurant.get("state")),
        "postal_code": clean_nullable_text(raw_restaurant.get("postal_code") or raw_restaurant.get("zip")),
        "hours_text": clean_nullable_text(raw_restaurant.get("hours_text") or raw_restaurant.get("hours")),
        "current_status": clean_nullable_text(raw_restaurant.get("current_status") or raw_restaurant.get("status")),
        "delivery_available": clean_bool(raw_restaurant.get("delivery_available")),
        "online_payment_available": clean_bool(raw_restaurant.get("online_payment_available")),
        "rewards_text": clean_nullable_text(raw_restaurant.get("rewards_text") or raw_restaurant.get("rewards")),
        "promotions": clean_text_list(raw_restaurant.get("promotions")),
        "logo_url": clean_nullable_text(raw_restaurant.get("logo_url")),
        "hero_image_url": clean_nullable_text(raw_restaurant.get("hero_image_url")),
    }


def apply_nonempty_fields(target, source):
    for key, value in source.items():
        if value in (None, "", []):
            continue
        target[key] = value
    return target


def upsert_restaurant(payload, raw_restaurant, source_url=""):
    now = utc_now_iso()
    normalized = normalize_restaurant_fields(raw_restaurant, source_url=source_url)
    restaurant = find_restaurant(
        payload,
        normalized.get("restaurant_name", ""),
        normalized.get("restaurant_website_url", ""),
        normalized.get("source_menu_url", ""),
    )

    if restaurant:
        existing_name = clean_text(restaurant.get("restaurant_name"))
        incoming_name = clean_text(normalized.get("restaurant_name"))
        apply_nonempty_fields(restaurant, normalized)
        if (
            existing_name
            and incoming_name
            and restaurant_name_key(existing_name) != restaurant_name_key(incoming_name)
            and restaurant_name_quality_score(existing_name) >= restaurant_name_quality_score(incoming_name)
        ):
            restaurant["restaurant_name"] = existing_name
        restaurant["updated_at"] = now
        restaurant["last_seen_at"] = now
        return restaurant

    restaurant = {
        "id": new_id("restaurant"),
        **normalized,
        "imported_at": now,
        "updated_at": now,
        "last_seen_at": now,
    }
    if not restaurant.get("restaurant_name"):
        restaurant["restaurant_name"] = "Restaurant Menu"
    payload["restaurants"].append(restaurant)
    return restaurant


def normalize_section(raw_section, index):
    raw_section = raw_section if isinstance(raw_section, dict) else {}
    return {
        "section_name": clean_text(
            raw_section.get("section_name")
            or raw_section.get("name")
            or raw_section.get("title")
            or f"Menu Section {index + 1}"
        ),
        "section_description": clean_nullable_text(
            raw_section.get("section_description")
            or raw_section.get("description")
        ),
        "display_order": int(raw_section.get("display_order") or index + 1),
    }


def normalize_item(raw_item, section_name, index):
    raw_item = raw_item if isinstance(raw_item, dict) else {}
    item_name = clean_text(
        raw_item.get("item_name")
        or raw_item.get("name")
        or raw_item.get("title")
    )
    if not item_name:
        return None
    return {
        "item_name": item_name,
        "menu_price": normalize_price(raw_item.get("menu_price") or raw_item.get("price")),
        "menu_description": clean_nullable_text(
            raw_item.get("menu_description")
            or raw_item.get("description")
        ),
        "dietary_tags": clean_text_list(raw_item.get("dietary_tags")),
        "spice_level": clean_text(raw_item.get("spice_level") or ("hot" if raw_item.get("is_spicy") else "none")),
        "chef_recommended": clean_bool(raw_item.get("chef_recommended")),
        "image_url": clean_nullable_text(raw_item.get("image_url")),
        "display_order": int(raw_item.get("display_order") or index + 1),
        "source_type": clean_text(raw_item.get("source_type") or "imported"),
        "recipe_id": clean_nullable_text(raw_item.get("recipe_id")),
        "recipe_url": clean_nullable_text(raw_item.get("recipe_url") or raw_item.get("url")),
        "source_menu_section": clean_nullable_text(raw_item.get("source_menu_section")),
        "menu_order_url": clean_nullable_text(
            raw_item.get("menu_order_url")
            or raw_item.get("deep_link_url")
            or raw_item.get("item_url")
        ),
        "menu_section": section_name,
        "is_spicy": clean_bool(raw_item.get("is_spicy")) or str(raw_item.get("spice_level") or "").lower() in {"medium", "hot"},
        "is_veggie": clean_bool(raw_item.get("is_veggie")) or any(
            tag.lower() in {"vegetarian", "veggie", "vegan"}
            for tag in clean_text_list(raw_item.get("dietary_tags"))
        ),
    }


def replace_menu_sections_and_items(payload, menu, sections):
    menu_id = menu.get("id")
    restaurant_id = menu.get("restaurant_id")
    cookbook_id = menu.get("cookbook_id", "")
    now = utc_now_iso()
    payload["sections"] = [
        section for section in payload.get("sections", []) if section.get("menu_id") != menu_id
    ]
    payload["items"] = [
        item for item in payload.get("items", []) if item.get("menu_id") != menu_id
    ]

    section_count = 0
    item_count = 0
    for section_index, raw_section in enumerate(sections or []):
        normalized_section = normalize_section(raw_section, section_index)
        section_name = normalized_section["section_name"]
        section = {
            "id": new_id("section"),
            "menu_id": menu_id,
            "restaurant_id": restaurant_id,
            "cookbook_id": cookbook_id,
            **normalized_section,
            "imported_at": now,
            "last_seen_at": now,
        }
        payload["sections"].append(section)
        section_count += 1

        for item_index, raw_item in enumerate((raw_section or {}).get("items") or []):
            normalized_item = normalize_item(raw_item, section_name, item_index)
            if not normalized_item:
                continue
            item = {
                "id": new_id("item"),
                "menu_id": menu_id,
                "restaurant_id": restaurant_id,
                "cookbook_id": cookbook_id,
                "menu_section_id": section["id"],
                **normalized_item,
                "imported_at": now,
                "last_seen_at": now,
            }
            payload["items"].append(item)
            item_count += 1

    menu["section_count"] = section_count
    menu["item_count"] = item_count
    return menu


def upsert_menu_from_facts(facts, cookbook_id="", cookbook_name=""):
    facts = facts if isinstance(facts, dict) else {}
    now = utc_now_iso()
    raw_menu = facts.get("menu") if isinstance(facts.get("menu"), dict) else {}
    raw_restaurant = facts.get("restaurant") if isinstance(facts.get("restaurant"), dict) else {}
    source_url = clean_text(facts.get("source_url") or raw_restaurant.get("source_menu_url"))
    uploaded_path = clean_text(facts.get("source_uploaded_file_path") or facts.get("uploaded_file_path"))
    source_type = clean_text(facts.get("menu_source_type") or facts.get("source_type") or "imported_menu")
    menu_source_type = source_type if source_type in {"ai_generated_menu", "cookbook_generated_menu"} else "imported_menu"
    sections = facts.get("sections") if isinstance(facts.get("sections"), list) else []

    with MENU_STORE_LOCK:
        payload = load_menu_store()
        restaurant = upsert_restaurant(payload, raw_restaurant, source_url=source_url)
        candidate = {
            "source_type": menu_source_type,
            "source_url": source_url,
            "source_uploaded_file_path": uploaded_path,
            "cookbook_id": clean_text(cookbook_id),
        }
        menu = None if menu_source_type == "ai_generated_menu" else find_existing_menu(payload, candidate, restaurant)
        if menu:
            menu["updated_at"] = now
        else:
            menu = {
                "id": new_id("menu"),
                "created_at": now,
            }
            payload["menus"].append(menu)

        menu.update({
            "restaurant_id": restaurant.get("id"),
            "cookbook_id": clean_text(menu.get("cookbook_id")) or clean_text(cookbook_id),
            "cookbook_name": clean_text(menu.get("cookbook_name")) or clean_text(cookbook_name),
            "menu_title": clean_text(raw_menu.get("menu_title") or raw_menu.get("title") or f"{restaurant.get('restaurant_name')} Menu"),
            "menu_subtitle": clean_nullable_text(raw_menu.get("menu_subtitle") or raw_menu.get("subtitle")),
            "menu_description": clean_nullable_text(raw_menu.get("menu_description") or raw_menu.get("description")),
            "menu_theme": clean_nullable_text(raw_menu.get("menu_theme") or raw_menu.get("theme")),
            "menu_style": clean_nullable_text(raw_menu.get("menu_style") or raw_menu.get("style")),
            "source_type": menu_source_type,
            "source_input_type": clean_text(facts.get("source_input_type") or source_type),
            "source_url": source_url,
            "source_uploaded_file_path": uploaded_path,
            "source_name": clean_text(facts.get("source_name")),
            "created_from_cookbook_id": clean_text(menu.get("created_from_cookbook_id")) or clean_text(facts.get("created_from_cookbook_id") or cookbook_id),
            "is_public": clean_bool(raw_menu.get("is_public") or facts.get("is_public")),
            "generated_by_model": clean_text(facts.get("generated_by_model") or facts.get("model_used") or facts.get("model")),
            "model_source": clean_text(facts.get("model_source")),
            "updated_at": now,
        })
        replace_menu_sections_and_items(payload, menu, sections)
        save_menu_store(payload)
        return get_menu(menu["id"], payload=payload)


def menu_sections_for(payload, menu_id):
    sections = [
        section for section in payload.get("sections", []) if section.get("menu_id") == menu_id
    ]
    return sorted(sections, key=lambda row: (int(row.get("display_order") or 0), row.get("section_name") or ""))


def menu_items_for(payload, menu_id, section_id=None):
    items = [
        item for item in payload.get("items", []) if item.get("menu_id") == menu_id
    ]
    if section_id:
        items = [item for item in items if item.get("menu_section_id") == section_id]
    return sorted(items, key=lambda row: (int(row.get("display_order") or 0), row.get("item_name") or ""))


def restaurant_for(payload, restaurant_id):
    return next(
        (restaurant for restaurant in payload.get("restaurants", []) if restaurant.get("id") == restaurant_id),
        {},
    )


def pdf_logs_for_menu(payload, menu_id):
    logs = [
        log for log in payload.get("pdf_logs", []) if log.get("menu_id") == menu_id
    ]
    return sorted(logs, key=lambda row: row.get("generated_at") or row.get("created_at") or "", reverse=True)


def get_menu(menu_id, payload=None):
    payload = payload or load_menu_store()
    menu = find_menu(payload, menu_id)
    if not menu:
        return {}

    sections = []
    for section in menu_sections_for(payload, menu.get("id")):
        sections.append({
            **section,
            "items": menu_items_for(payload, menu.get("id"), section.get("id")),
        })

    return {
        "menu": dict(menu),
        "restaurant": dict(restaurant_for(payload, menu.get("restaurant_id"))),
        "sections": sections,
        "items": menu_items_for(payload, menu.get("id")),
        "pdf_logs": pdf_logs_for_menu(payload, menu.get("id")),
    }


def regroup_menu_sections(menu_id, section_payload):
    section_payload = section_payload if isinstance(section_payload, list) else []
    if not section_payload:
        return {}

    with MENU_STORE_LOCK:
        payload = load_menu_store()
        menu = find_menu(payload, menu_id)
        if not menu:
            return {}

        menu_id = menu.get("id")
        now = utc_now_iso()
        restaurant_id = menu.get("restaurant_id")
        cookbook_id = menu.get("cookbook_id", "")
        existing_sections = [
            section for section in payload.get("sections", []) if section.get("menu_id") == menu_id
        ]
        existing_sections_by_name = {}
        for section in existing_sections:
            key = clean_text(section.get("section_name")).lower()
            if key and key not in existing_sections_by_name:
                existing_sections_by_name[key] = section

        menu_items = [
            item for item in payload.get("items", []) if item.get("menu_id") == menu_id
        ]
        menu_items_by_id = {
            clean_text(item.get("id")): item
            for item in menu_items
            if clean_text(item.get("id"))
        }
        rebuilt_sections = []
        assigned_item_ids = set()

        for section_index, raw_section in enumerate(section_payload):
            raw_section = raw_section if isinstance(raw_section, dict) else {}
            raw_items = raw_section.get("items") if isinstance(raw_section.get("items"), list) else []
            if not raw_items:
                continue

            normalized_section = normalize_section(raw_section, section_index)
            section_name = normalized_section["section_name"]
            section_key = section_name.lower()
            section = existing_sections_by_name.get(section_key)
            if not section:
                section = {
                    "id": new_id("section"),
                    "menu_id": menu_id,
                    "restaurant_id": restaurant_id,
                    "cookbook_id": cookbook_id,
                    "imported_at": now,
                }

            section.update({
                "menu_id": menu_id,
                "restaurant_id": restaurant_id,
                "cookbook_id": cookbook_id,
                **normalized_section,
                "last_seen_at": now,
            })
            rebuilt_sections.append(section)

            for item_index, raw_item in enumerate(raw_items):
                raw_item = raw_item if isinstance(raw_item, dict) else {}
                item_id = clean_text(raw_item.get("id") or raw_item.get("item_id"))
                item = menu_items_by_id.get(item_id)
                if not item or item_id in assigned_item_ids:
                    continue

                item["menu_section_id"] = section["id"]
                item["menu_section"] = section_name
                item["display_order"] = item_index + 1
                item["last_seen_at"] = now
                source_menu_section = clean_text(raw_item.get("source_menu_section"))
                if source_menu_section:
                    item["source_menu_section"] = source_menu_section
                assigned_item_ids.add(item_id)

        if not rebuilt_sections:
            return {}

        payload["sections"] = [
            section for section in payload.get("sections", []) if section.get("menu_id") != menu_id
        ] + rebuilt_sections
        menu["section_count"] = len(rebuilt_sections)
        menu["item_count"] = len(menu_items)
        menu["updated_at"] = now

        save_menu_store(payload)
        return get_menu(menu_id, payload=payload)


def list_menus(payload=None):
    payload = payload or load_menu_store()
    return [
        get_menu(menu.get("id"), payload=payload)
        for menu in payload.get("menus", [])
        if menu.get("id")
    ]


def menus_by_cookbook():
    grouped = {}
    for detail in list_menus():
        menu = detail.get("menu", {})
        cookbook_id = clean_text(menu.get("cookbook_id"))
        if not cookbook_id:
            continue
        grouped.setdefault(cookbook_id, []).append(detail)
    return grouped


def selected_items_as_sections(menu_id, item_ids):
    detail = get_menu(menu_id)
    if not detail:
        return []

    selected_ids = {clean_text(item_id) for item_id in item_ids or [] if clean_text(item_id)}
    if not selected_ids:
        return []

    menu = detail.get("menu", {})
    source_url = menu.get("source_url") or menu.get("source_uploaded_file_path") or f"menu://{menu_id}"
    sections = []
    for section in detail.get("sections", []):
        selected_items = []
        for item in section.get("items", []):
            if item.get("id") not in selected_ids:
                continue
            selected_items.append({
                "item_name": item.get("item_name", ""),
                "menu_section": section.get("section_name", ""),
                "section_description": section.get("section_description") or "",
                "description": item.get("menu_description") or "",
                "price": item.get("menu_price") or "",
                "source_url": source_url,
                "menu_order_url": item.get("menu_order_url") or "",
                "deep_link_url": item.get("menu_order_url") or "",
                "restaurant_id": item.get("restaurant_id", ""),
                "menu_id": item.get("menu_id", ""),
                "menu_section_id": item.get("menu_section_id", ""),
                "menu_item_id": item.get("id", ""),
                "is_spicy": item.get("is_spicy", False),
                "is_veggie": item.get("is_veggie", False),
            })
        if selected_items:
            sections.append({
                "section_name": section.get("section_name", ""),
                "description": section.get("section_description") or "",
                "items": selected_items,
            })
    return sections


def latest_menu_pdf_log(menu_id):
    logs = get_menu(menu_id).get("pdf_logs", [])
    return logs[0] if logs else {}


def count_pdf_pages(pdf_path):
    try:
        from PyPDF2 import PdfReader
        with Path(pdf_path).open("rb") as handle:
            return len(PdfReader(handle).pages)
    except Exception:
        return 0


def record_menu_pdf_generated(menu_id, pdf_title, local_pdf_path, generated_by_model="", status="generated", error_message=""):
    now = utc_now_iso()
    path = Path(local_pdf_path) if local_pdf_path else None
    detail = get_menu(menu_id)
    menu = detail.get("menu", {})
    restaurant = detail.get("restaurant", {})

    with MENU_STORE_LOCK:
        payload = load_menu_store()
        log = {
            "id": new_id("menu_pdf"),
            "cookbook_id": menu.get("cookbook_id", ""),
            "menu_id": menu_id,
            "restaurant_id": menu.get("restaurant_id", ""),
            "source_type": menu.get("source_type", ""),
            "pdf_title": clean_text(pdf_title) or menu.get("menu_title", "") or "Restaurant Menu",
            "local_pdf_path": str(path) if path else "",
            "cloudflare_pdf_path": "",
            "cloudflare_pdf_url": "",
            "source_menu_url": menu.get("source_url", ""),
            "restaurant_website_url": restaurant.get("restaurant_website_url", ""),
            "generated_by_model": clean_text(generated_by_model or menu.get("generated_by_model")),
            "generated_at": now,
            "uploaded_at": "",
            "file_size_bytes": path.stat().st_size if path and path.exists() else 0,
            "page_count": count_pdf_pages(path) if path and path.exists() else 0,
            "status": clean_text(status) or "generated",
            "error_message": clean_text(error_message),
            "created_at": now,
            "updated_at": now,
        }
        payload["pdf_logs"].append(log)
        save_menu_store(payload)
        return log


def update_menu_pdf_log(log_id, **updates):
    with MENU_STORE_LOCK:
        payload = load_menu_store()
        log = find_menu_pdf_log(payload, log_id)
        if not log:
            return {}

        for key, value in updates.items():
            if key in {"file_size_bytes", "page_count"}:
                try:
                    log[key] = int(value or 0)
                except (TypeError, ValueError):
                    log[key] = 0
            else:
                log[key] = value
        log["updated_at"] = utc_now_iso()
        save_menu_store(payload)
        return dict(log)


def menu_pdf_logs_for_cookbook(cookbook_id):
    cookbook_id = clean_text(cookbook_id)
    if not cookbook_id:
        return []
    payload = load_menu_store()
    menus = {
        menu.get("id"): menu
        for menu in payload.get("menus", [])
        if menu.get("id")
    }
    restaurants = {
        restaurant.get("id"): restaurant
        for restaurant in payload.get("restaurants", [])
        if restaurant.get("id")
    }
    rows = []
    for log in payload.get("pdf_logs", []):
        if clean_text(log.get("cookbook_id")) != cookbook_id:
            continue
        menu = menus.get(log.get("menu_id"), {})
        restaurant = restaurants.get(log.get("restaurant_id") or menu.get("restaurant_id"), {})
        rows.append({
            **log,
            "menu_title": menu.get("menu_title", ""),
            "restaurant_name": restaurant.get("restaurant_name", ""),
        })
    return sorted(rows, key=lambda row: row.get("generated_at") or row.get("created_at") or "", reverse=True)


def menu_pdf_logs_by_cookbook():
    payload = load_menu_store()
    grouped = {}
    for menu in payload.get("menus", []):
        cookbook_id = clean_text(menu.get("cookbook_id"))
        if cookbook_id:
            grouped.setdefault(cookbook_id, [])
    for log in payload.get("pdf_logs", []):
        cookbook_id = clean_text(log.get("cookbook_id"))
        if cookbook_id:
            grouped.setdefault(cookbook_id, []).append(log)
    for cookbook_id in list(grouped):
        grouped[cookbook_id] = menu_pdf_logs_for_cookbook(cookbook_id)
    return grouped


def delete_menu_pdf_log(log_id):
    with MENU_STORE_LOCK:
        payload = load_menu_store()
        before = len(payload.get("pdf_logs", []))
        payload["pdf_logs"] = [
            log for log in payload.get("pdf_logs", []) if log.get("id") != clean_text(log_id)
        ]
        if len(payload["pdf_logs"]) == before:
            return False
        save_menu_store(payload)
        return True


def update_menu_fields(menu_id, menu_fields, restaurant_fields=None, section_payload=None):
    menu_fields = menu_fields if isinstance(menu_fields, dict) else {}
    restaurant_fields = restaurant_fields if isinstance(restaurant_fields, dict) else {}
    with MENU_STORE_LOCK:
        payload = load_menu_store()
        menu = find_menu(payload, menu_id)
        if not menu:
            return {}

        for field in (
            "menu_title",
            "menu_subtitle",
            "menu_description",
            "menu_theme",
            "menu_style",
        ):
            if field in menu_fields:
                menu[field] = clean_nullable_text(menu_fields.get(field)) or ""
        menu["is_public"] = clean_bool(menu_fields.get("is_public")) if "is_public" in menu_fields else bool(menu.get("is_public"))
        menu["updated_at"] = utc_now_iso()

        restaurant = restaurant_for(payload, menu.get("restaurant_id"))
        if restaurant:
            apply_nonempty_fields(restaurant, normalize_restaurant_fields(restaurant_fields, source_url=menu.get("source_url", "")))
            restaurant["updated_at"] = utc_now_iso()

        if isinstance(section_payload, list):
            replace_menu_sections_and_items(payload, menu, section_payload)

        save_menu_store(payload)
        return get_menu(menu_id, payload=payload)
