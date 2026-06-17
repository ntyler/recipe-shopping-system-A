import json
import mimetypes
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from PushShoppingList.services.recipe_extract_service import UPLOAD_FOLDER
from PushShoppingList.services.recipe_extract_service import build_openai_chat_payload
from PushShoppingList.services.recipe_extract_service import build_vision_debug
from PushShoppingList.services.recipe_extract_service import call_openai_vision_image
from PushShoppingList.services.recipe_extract_service import cartana_menu_api_url
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import clean_menu_price
from PushShoppingList.services.recipe_extract_service import clean_recipe_text
from PushShoppingList.services.recipe_extract_service import extract_structured_menu_items_from_html
from PushShoppingList.services.recipe_extract_service import extract_text_from_generic_document
from PushShoppingList.services.recipe_extract_service import extract_text_from_pdf
from PushShoppingList.services.recipe_extract_service import fetch_cartana_menu_payload
from PushShoppingList.services.recipe_extract_service import fetch_menu_page_html
from PushShoppingList.services.recipe_extract_service import fetch_recipe_page_with_browser
from PushShoppingList.services.recipe_extract_service import flatten_menu_sections
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import menu_item_recipe_model_resolution
from PushShoppingList.services.recipe_extract_service import menu_page_visible_text
from PushShoppingList.services.recipe_extract_service import normalize_upload_mime_type
from PushShoppingList.services.recipe_extract_service import parse_cartana_menu_sections
from PushShoppingList.services.recipe_extract_service import resolve_menu_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_model_source
from PushShoppingList.services.recipe_extract_service import safe_filename
from PushShoppingList.services.recipe_extract_service import send_menu_file_prompt_to_openai
from PushShoppingList.services.recipe_extract_service import upload_can_use_openai_file_input
from PushShoppingList.services.recipe_extract_service import upload_file_suffix
from PushShoppingList.services.recipe_extract_service import upload_import_source_type
from PushShoppingList.services.recipe_extract_service import upload_is_word_document
from PushShoppingList.services.recipe_extract_service import upload_source_type_label
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_usage_service import record_openai_usage


COMMON_CUISINE_TAGS = (
    "Asian",
    "Japanese",
    "Ramen",
    "Sushi",
    "Thai",
    "Vietnamese",
    "Burmese",
    "Chinese",
    "Korean",
    "Indian",
    "Mexican",
    "Italian",
    "French",
    "American",
    "Mediterranean",
)


def menu_recipe_generation_model():
    resolution = menu_item_recipe_model_resolution()
    return {
        "model": resolution.model,
        "model_source": resolution.source,
    }


def build_menu_fact_extraction_prompt(source_label, page_text=""):
    page_text = str(page_text or "").strip()
    visible_text = page_text[:35000] if page_text else "No reliable text was extracted."
    return f"""
Extract restaurant menu facts only. Do not create recipes.

Source: {source_label}

Rules:
- Return only valid JSON.
- Extract restaurant metadata when present.
- Extract menu sections and menu item names.
- Preserve source menu descriptions only when present.
- Preserve source menu prices only when present.
- Preserve item order URLs only when present.
- Do not invent missing descriptions.
- Do not invent missing prices.
- Do not invent item order URLs.
- Use null for missing prices and descriptions.

Return this JSON shape:
{{
  "restaurant": {{
    "restaurant_name": "string or null",
    "restaurant_website_url": "string or null",
    "cuisine_tags": ["string"],
    "phone": "string or null",
    "full_address": "string or null",
    "hours_text": "string or null",
    "current_status": "string or null",
    "delivery_available": false,
    "online_payment_available": false,
    "rewards_text": "string or null",
    "promotions": []
  }},
  "menu": {{
    "menu_title": "string",
    "menu_subtitle": "string or null",
    "menu_description": "string or null",
    "menu_theme": "string or null",
    "menu_style": "string or null"
  }},
  "sections": [
    {{
      "section_name": "string",
      "section_description": "string or null",
      "display_order": 1,
      "items": [
        {{
          "item_name": "string",
          "menu_price": "$9.99 or null",
          "menu_description": "string or null",
          "menu_order_url": "https://example.com/order-item or null",
          "dietary_tags": [],
          "spice_level": "none",
          "chef_recommended": false,
          "display_order": 1
        }}
      ]
    }}
  ]
}}

Visible menu text:
{visible_text}
"""


def send_menu_fact_prompt_to_openai(prompt_text, action_name="menu-fact-extraction"):
    model = resolve_menu_model()
    model_source = resolve_menu_model_source()
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        model,
        action_name,
        [
            {
                "role": "system",
                "content": (
                    "You extract restaurant menu facts. Do not infer recipes, prices, "
                    "or menu descriptions. Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action={action_name} model={resolved_model} "
        f"model_source={model_source} temperature_included={temperature_included}"
    )
    response = throttled_chat_completion(
        get_openai_client(),
        payload,
        action_name=action_name,
        model=resolved_model,
        kind="menu",
    )
    record_openai_usage(response, action_name, model=resolved_model)
    return response.choices[0].message.content


def parse_menu_fact_response(response_text):
    payload = json.loads(clean_json_response(response_text))
    payload = payload if isinstance(payload, dict) else {}
    sections = payload.get("sections") or payload.get("menu_sections") or []
    normalized_sections = []
    for section_index, section in enumerate(sections if isinstance(sections, list) else []):
        if not isinstance(section, dict):
            continue
        section_name = clean_recipe_text(
            section.get("section_name")
            or section.get("name")
            or section.get("title")
            or f"Menu Section {section_index + 1}"
        )
        if not section_name:
            continue
        items = []
        raw_items = section.get("items") or section.get("menu_items") or []
        for item_index, item in enumerate(raw_items if isinstance(raw_items, list) else []):
            if not isinstance(item, dict):
                continue
            item_name = clean_recipe_text(
                item.get("item_name")
                or item.get("name")
                or item.get("title")
            )
            if not item_name:
                continue
            display_order = item.get("display_order")
            if display_order in (None, ""):
                display_order = item.get("index")
                display_order = int(display_order if display_order not in (None, "") else item_index) + 1
            else:
                display_order = int(display_order)
            items.append({
                "item_name": item_name,
                "menu_price": clean_menu_price(item.get("menu_price") or item.get("price")) or None,
                "menu_description": clean_recipe_text(
                    item.get("menu_description")
                    or item.get("description")
                    or ""
                ) or None,
                "menu_order_url": clean_recipe_text(
                    item.get("menu_order_url")
                    or item.get("deep_link_url")
                    or item.get("item_url")
                    or ""
                ) or None,
                "dietary_tags": item.get("dietary_tags") if isinstance(item.get("dietary_tags"), list) else [],
                "spice_level": clean_recipe_text(item.get("spice_level") or "none"),
                "chef_recommended": bool(item.get("chef_recommended")),
                "display_order": int(item.get("display_order") or item_index + 1),
                "source_type": "imported",
            })
        if items:
            normalized_sections.append({
                "section_name": section_name,
                "section_description": clean_recipe_text(
                    section.get("section_description")
                    or section.get("description")
                    or ""
                ) or None,
                "display_order": int(section.get("display_order") or section_index + 1),
                "items": items,
            })

    return {
        "restaurant": payload.get("restaurant") if isinstance(payload.get("restaurant"), dict) else {},
        "menu": payload.get("menu") if isinstance(payload.get("menu"), dict) else {},
        "sections": normalized_sections,
    }


def cuisine_tags_from_text(text):
    lowered = str(text or "").lower()
    tags = []
    for tag in COMMON_CUISINE_TAGS:
        if tag.lower() in lowered and tag not in tags:
            tags.append(tag)
    return tags


def extract_restaurant_metadata_from_html(menu_url, html_text, page_text=""):
    soup = BeautifulSoup(html_text or "", "html.parser")
    title_text = ""
    if soup.title and soup.title.string:
        title_text = clean_recipe_text(soup.title.string)
    title_text = re.split(r"\s+[-|]\s+", title_text)[0] if title_text else ""

    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    og_title = soup.find("meta", attrs={"property": "og:title"})
    name = clean_recipe_text(
        (og_site.get("content") if og_site else "")
        or (og_title.get("content") if og_title else "")
        or title_text
    )

    visible = page_text or menu_page_visible_text(html_text)
    phone_match = re.search(r"(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})", visible)
    address_match = re.search(
        r"(\d{2,6}\s+[^,]{3,80},\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)",
        visible,
    )
    promotions = re.findall(r"\$\d+\s+Off\s+[^.|\n\r]{0,80}", visible, flags=re.IGNORECASE)
    parsed = urlparse(menu_url)
    website = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""

    status = ""
    if re.search(r"\bclosed\b", visible, flags=re.IGNORECASE):
        status = "Closed"
    elif re.search(r"\bopen\b", visible, flags=re.IGNORECASE):
        status = "Open"

    return {
        "restaurant_name": name or "Restaurant Menu",
        "restaurant_website_url": website,
        "source_menu_url": menu_url,
        "cuisine_tags": cuisine_tags_from_text(visible),
        "phone": clean_recipe_text(phone_match.group(1)) if phone_match else None,
        "full_address": clean_recipe_text(address_match.group(1)) if address_match else None,
        "hours_text": None,
        "current_status": status or None,
        "delivery_available": "delivery available" in visible.lower(),
        "online_payment_available": "online payment" in visible.lower(),
        "rewards_text": "Reward" if "reward" in visible.lower() else None,
        "promotions": [clean_recipe_text(item) for item in promotions],
    }


def sections_to_fact_payload(sections):
    normalized_sections = []
    for section_index, section in enumerate(sections or []):
        if not isinstance(section, dict):
            continue
        section_name = clean_recipe_text(
            section.get("section_name")
            or section.get("name")
            or f"Menu Section {section_index + 1}"
        )
        if not section_name:
            continue
        items = []
        for item_index, item in enumerate(section.get("items") or []):
            if not isinstance(item, dict):
                continue
            item_name = clean_recipe_text(item.get("item_name") or item.get("name"))
            if not item_name:
                continue
            try:
                display_order = int(item.get("display_order"))
            except (TypeError, ValueError):
                try:
                    display_order = int(item.get("index")) + 1
                except (TypeError, ValueError):
                    display_order = item_index + 1
            items.append({
                "item_name": item_name,
                "menu_price": clean_menu_price(item.get("menu_price") or item.get("price")) or None,
                "menu_description": clean_recipe_text(
                    item.get("menu_description")
                    or item.get("description")
                    or ""
                ) or None,
                "dietary_tags": ["Vegetarian"] if item.get("is_veggie") else [],
                "spice_level": "hot" if item.get("is_spicy") else "none",
                "chef_recommended": bool(item.get("chef_recommended")),
                "display_order": display_order,
                "source_type": "imported",
                "menu_order_url": clean_recipe_text(
                    item.get("menu_order_url")
                    or item.get("deep_link_url")
                    or item.get("item_url")
                    or ""
                ) or None,
                "is_spicy": bool(item.get("is_spicy")),
                "is_veggie": bool(item.get("is_veggie")),
            })
        if items:
            normalized_sections.append({
                "section_name": section_name,
                "section_description": clean_recipe_text(
                    section.get("section_description")
                    or section.get("description")
                    or ""
                ) or None,
                "display_order": section_index + 1,
                "items": items,
            })
    return normalized_sections


def build_fact_result(
    source_url="",
    source_name="",
    source_input_type="menu_url",
    source_uploaded_file_path="",
    restaurant=None,
    menu=None,
    sections=None,
    extracted_text="",
    diagnostics=None,
    model_used="",
    model_source="",
):
    sections = sections_to_fact_payload(sections)
    recipe_model = menu_recipe_generation_model()
    item_count = sum(len(section.get("items") or []) for section in sections)
    if item_count <= 0:
        return {
            "ok": False,
            "success": False,
            "error": "No menu items were found.",
            "source_url": source_url,
            "source_name": source_name,
            "source_input_type": source_input_type,
            "sections": [],
            "menu_sections_found": 0,
            "menu_items_found": 0,
            "debug": diagnostics or {},
            "model_used": model_used or resolve_menu_model(),
            "model_source": model_source or resolve_menu_model_source(),
            "recipe_generation_model": recipe_model["model"],
            "recipe_generation_model_source": recipe_model["model_source"],
        }

    restaurant = restaurant if isinstance(restaurant, dict) else {}
    menu = menu if isinstance(menu, dict) else {}
    restaurant_name = clean_recipe_text(restaurant.get("restaurant_name") or restaurant.get("name") or "")
    if not restaurant_name:
        restaurant_name = "Restaurant Menu"

    return {
        "ok": True,
        "success": True,
        "source_url": source_url,
        "source_name": source_name,
        "source_input_type": source_input_type,
        "source_uploaded_file_path": source_uploaded_file_path,
        "restaurant": {
            **restaurant,
            "restaurant_name": restaurant_name,
        },
        "menu": {
            "menu_title": clean_recipe_text(menu.get("menu_title") or menu.get("title") or f"{restaurant_name} Menu"),
            "menu_subtitle": menu.get("menu_subtitle") or menu.get("subtitle") or None,
            "menu_description": menu.get("menu_description") or menu.get("description") or None,
            "menu_theme": menu.get("menu_theme") or menu.get("theme") or None,
            "menu_style": menu.get("menu_style") or menu.get("style") or None,
        },
        "sections": sections,
        "extracted_text": extracted_text,
        "menu_sections_found": len(sections),
        "menu_items_found": item_count,
        "debug": diagnostics or {},
        "model_used": model_used or resolve_menu_model(),
        "model_source": model_source or resolve_menu_model_source(),
        "recipe_generation_model": recipe_model["model"],
        "recipe_generation_model_source": recipe_model["model_source"],
    }


def extract_menu_facts_from_url(menu_url):
    menu_url = str(menu_url or "").strip()
    if not menu_url:
        return {"ok": False, "error": "Menu URL is required."}

    diagnostics = {
        "menu_page_fetched": False,
        "rendered_page_used": False,
        "menu_extraction_source": "",
        "cartana_menu_api_url": cartana_menu_api_url(menu_url),
    }
    html_text = ""
    page_text = ""
    sections = []

    try:
        html_text = fetch_menu_page_html(menu_url)
        diagnostics["menu_page_fetched"] = True
        page_text = menu_page_visible_text(html_text)
    except Exception as exc:
        diagnostics["menu_fetch_error"] = str(exc)

    if html_text:
        try:
            payload, cartana_debug = fetch_cartana_menu_payload(menu_url, html_text)
            diagnostics["cartana_menu_api"] = cartana_debug
            sections = parse_cartana_menu_sections(payload, menu_url)
            if sections:
                diagnostics["menu_extraction_source"] = "cartana_api"
        except Exception as exc:
            diagnostics["cartana_menu_api"] = {"ok": False, "error": str(exc)}

    if not flatten_menu_sections(sections) and html_text:
        sections, fallback_source = extract_structured_menu_items_from_html(html_text, menu_url)
        diagnostics["menu_extraction_source"] = fallback_source or diagnostics["menu_extraction_source"]

    if not flatten_menu_sections(sections) and html_text and os.getenv("DISABLE_BROWSER_RECIPE_FETCH") != "1":
        try:
            rendered_html = fetch_recipe_page_with_browser(menu_url)
            diagnostics["rendered_page_used"] = True
            rendered_text = menu_page_visible_text(rendered_html)
            page_text = rendered_text or page_text
            sections, fallback_source = extract_structured_menu_items_from_html(rendered_html, menu_url)
            diagnostics["menu_extraction_source"] = fallback_source or diagnostics["menu_extraction_source"]
            if rendered_html:
                html_text = rendered_html
        except Exception as exc:
            diagnostics["rendered_page_error"] = str(exc)

    restaurant = extract_restaurant_metadata_from_html(menu_url, html_text, page_text)
    if flatten_menu_sections(sections):
        return build_fact_result(
            source_url=menu_url,
            source_name=menu_url,
            source_input_type="menu_url",
            restaurant=restaurant,
            menu={"menu_title": f"{restaurant.get('restaurant_name') or 'Restaurant'} Menu"},
            sections=sections,
            extracted_text=page_text,
            diagnostics=diagnostics,
        )

    if not os.getenv("OPENAI_API_KEY"):
        return build_fact_result(
            source_url=menu_url,
            source_name=menu_url,
            source_input_type="menu_url",
            restaurant=restaurant,
            sections=[],
            extracted_text=page_text,
            diagnostics=diagnostics,
        )

    response_text = send_menu_fact_prompt_to_openai(
        build_menu_fact_extraction_prompt(menu_url, page_text),
        action_name="menu-url-fact-extraction",
    )
    parsed = parse_menu_fact_response(response_text)
    return build_fact_result(
        source_url=menu_url,
        source_name=menu_url,
        source_input_type="menu_url",
        restaurant={**restaurant, **parsed.get("restaurant", {})},
        menu=parsed.get("menu", {}),
        sections=parsed.get("sections", []),
        extracted_text=page_text,
        diagnostics={**diagnostics, "menu_extraction_source": "openai_fact_extraction"},
    )


def extract_menu_facts_from_upload(file_storage):
    filename = Path(file_storage.filename or "uploaded-menu").name
    safe_name = f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    upload_path = UPLOAD_FOLDER / safe_name
    file_storage.save(upload_path)

    source_url = f"uploaded-menu://{safe_name}"
    mime_type = (
        file_storage.mimetype
        or mimetypes.guess_type(str(upload_path))[0]
        or "application/octet-stream"
    )
    mime_type = normalize_upload_mime_type(mime_type, filename, upload_path)
    upload_suffix = upload_file_suffix(filename, upload_path)
    import_source_type = upload_import_source_type(mime_type, filename, upload_path)
    extracted_text = ""
    diagnostics = {
        "action": "menu-upload-fact-extraction",
        "source_type": import_source_type,
        "filename": filename,
        "mime_type": mime_type,
        "model": resolve_menu_model(),
        "model_source": resolve_menu_model_source(),
    }

    if import_source_type == "image":
        vision_debug = build_vision_debug(uploaded_file_path=str(upload_path), filename=filename, mime_type=mime_type)
        vision_result = call_openai_vision_image(
            str(upload_path),
            build_menu_fact_extraction_prompt(filename),
            "menu-image-fact-extraction",
            preferred_model=resolve_menu_model(),
            debug=vision_debug,
        )
        diagnostics.update(vision_debug)
        if not vision_result.ok:
            return {
                "ok": False,
                "success": False,
                "error": vision_result.error_message or "Unable to extract menu facts from this image.",
                "source_name": filename,
                "source_url": source_url,
                "source_uploaded_file_path": str(upload_path),
                "source_input_type": f"menu_{import_source_type}",
                "debug": diagnostics,
                "model_used": vision_result.model_used,
                "model_source": vision_result.model_source,
            }
        parsed = parse_menu_fact_response(vision_result.text)
        return build_fact_result(
            source_url=source_url,
            source_name=filename,
            source_input_type=f"menu_{import_source_type}",
            source_uploaded_file_path=str(upload_path),
            restaurant=parsed.get("restaurant", {}),
            menu=parsed.get("menu", {}),
            sections=parsed.get("sections", []),
            diagnostics=diagnostics,
            model_used=vision_result.model_used,
            model_source=vision_result.model_source,
        )

    if upload_is_word_document(mime_type, filename, upload_path):
        if upload_suffix == ".docx":
            try:
                extracted_text = extract_text_from_generic_document(upload_path, filename)
            except Exception:
                extracted_text = ""
    elif import_source_type == "pdf":
        try:
            extracted_text = extract_text_from_pdf(upload_path)
        except Exception:
            extracted_text = ""
    else:
        extracted_text = extract_text_from_generic_document(upload_path, filename)

    if extracted_text.strip():
        response_text = send_menu_fact_prompt_to_openai(
            build_menu_fact_extraction_prompt(filename, extracted_text),
            action_name="menu-upload-text-fact-extraction",
        )
    elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
        response_text = send_menu_file_prompt_to_openai(
            build_menu_fact_extraction_prompt(filename),
            upload_path,
            mime_type,
            filename,
        )
    else:
        return {
            "ok": False,
            "success": False,
            "error": "No readable menu text was found in this uploaded file.",
            "source_name": filename,
            "source_url": source_url,
            "source_uploaded_file_path": str(upload_path),
            "source_input_type": f"menu_{import_source_type}",
            "source_type_label": upload_source_type_label(import_source_type),
            "debug": diagnostics,
            "model_used": resolve_menu_model(),
            "model_source": resolve_menu_model_source(),
        }

    parsed = parse_menu_fact_response(response_text)
    return build_fact_result(
        source_url=source_url,
        source_name=filename,
        source_input_type=f"menu_{import_source_type}",
        source_uploaded_file_path=str(upload_path),
        restaurant=parsed.get("restaurant", {}),
        menu=parsed.get("menu", {}),
        sections=parsed.get("sections", []),
        extracted_text=extracted_text,
        diagnostics=diagnostics,
    )
