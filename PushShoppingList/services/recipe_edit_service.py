import base64
import json
import mimetypes
import os
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlparse

import requests

from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.cookbook_service import ensure_unclassified_cookbook_for_recipes
from PushShoppingList.services.cookbook_service import recipe_cookbook_assignments
from PushShoppingList.services.ingredient_text_review_service import annotate_ingredients_for_food_review
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import RAW_FOLDER
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import UPLOAD_FOLDER
from PushShoppingList.services.recipe_extract_service import build_video_text_pdf_html
from PushShoppingList.services.recipe_extract_service import classify_store_section
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import extract_recipe_cover_image_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_info_from_text
from PushShoppingList.services.recipe_extract_service import extract_ingredients_from_result
from PushShoppingList.services.recipe_extract_service import fetch_recipe_page
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import normalize_recipe_cover_image
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import normalize_recipe_scaling_metadata
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import safe_filename
from PushShoppingList.services.recipe_extract_service import write_recipe_page_pdf
from PushShoppingList.services.purchase_mapping_service import apply_purchase_mapping_to_ingredient
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import recipe_ingredients_for_key
from PushShoppingList.services.recipe_ingredient_service import remove_unused_ingredients_from_shopping_list
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.recipe_url_service import load_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import recipe_url_type
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_url_quantity
from PushShoppingList.services.recipe_quantity_service import update_recipe_quantity
from PushShoppingList.services.recipe_image_progress_service import finish_recipe_image_progress
from PushShoppingList.services.recipe_image_progress_service import start_recipe_image_progress
from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients


NUTRITION_FIELDS = [
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
DEFAULT_MANUAL_NUTRITION_FIELDS = [
    "serving_basis",
    "calories",
    "carbohydrates",
    "protein",
    "fat",
    "saturated_fat",
    "cholesterol",
    "sodium",
    "fiber",
    "sugar",
]
NUTRITION_ESTIMATE_FIELDS = [
    field
    for field in DEFAULT_MANUAL_NUTRITION_FIELDS
    if field != "serving_basis"
]
STEP_IMAGE_FOLDER = Path(__file__).resolve().parents[1] / "static" / "generated" / "recipe_steps"
STEP_IMAGE_URL_PREFIX = "/static/generated/recipe_steps"
COVER_IMAGE_UPLOAD_FOLDER = UPLOAD_FOLDER / "recipe_covers"
COVER_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
COVER_IMAGE_MIME_EXTENSIONS = {
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def create_new_recipe():
    source_url = f"manual://recipe/{uuid.uuid4().hex}"
    recipe_data = {
        "source_url": source_url,
        "recipe_title": "New Recipe",
        "servings": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "ingredients": [],
        "equipment": [],
        "instructions": [],
        "nutrition": empty_recipe_nutrition(),
        "scaling": normalize_recipe_scaling_metadata(),
    }

    save_recipe_output(source_url, recipe_data)
    save_recipe_urls(load_recipe_urls() + [source_url])
    save_recipe_url_quantity(source_url, 1)
    save_recipe_url_name(source_url, "New Recipe")
    update_recipe_ingredient_record(source_url, 1, recipe_data)
    ensure_unclassified_cookbook_for_recipes([{
        "url": source_url,
        "name": "New Recipe",
        "source_href": source_url,
        "source_display_url": source_url,
        "quantity": 1,
        "base_servings": "",
    }])

    result = load_editable_recipe(source_url)
    result["url"] = source_url
    return result


def empty_recipe_nutrition():
    return {
        **{field: "" for field in DEFAULT_MANUAL_NUTRITION_FIELDS},
        "serving_basis": "per serving",
        "other": [],
    }


def load_editable_recipe(url):
    url = str(url or "").strip()
    recipe_data = load_recipe_output(url) or {"source_url": url}
    meta = load_recipe_ingredients().get(normalize_recipe_url_key(url), {})
    cookbook_assignment = recipe_cookbook_assignments().get(normalize_recipe_url_key(url), {})
    pdf = editable_recipe_pdf_info(url)
    scaling = normalize_recipe_scaling_metadata(recipe_data.get("scaling"))
    if recipe_data.get("servings") and not scaling.get("base_servings"):
        scaling["base_servings"] = str(recipe_data.get("servings") or "").strip()
    recipe_info = recipe_information_fields(recipe_data, url)
    cover_image = editable_recipe_cover_image(url, recipe_data, meta)

    return {
        "ok": True,
        "recipe": {
            "source_url": recipe_data.get("source_url") or url,
            "source_display_url": editable_recipe_source_display_url(recipe_data.get("source_url") or url),
            "type": recipe_url_type(url),
            "display_name": meta.get("name") or recipe_data.get("recipe_title") or "",
            "quantity": normalize_recipe_quantity(meta.get("quantity", 1)),
            "cookbook_id": cookbook_assignment.get("cookbook_id", ""),
            "cookbook_name": cookbook_assignment.get("cookbook_name", ""),
            "cookbook_is_unclassified": cookbook_assignment.get("cookbook_is_unclassified", False),
            "recipe_title": recipe_data.get("recipe_title") or "",
            "servings": recipe_data.get("servings") or "",
            "cover_image": cover_image,
            **recipe_info,
            "scaling": scaling,
            "ingredients": annotate_ingredients_for_food_review(
                normalize_edit_ingredients(recipe_data.get("ingredients", []))
            ),
            "equipment": normalize_equipment_records(recipe_data.get("equipment", [])),
            "instructions": normalize_instruction_rows(recipe_data.get("instructions", [])),
            "nutrition": normalize_nutrition_rows(
                recipe_data.get("nutrition", {}),
                include_defaults=recipe_url_type(url) == "Manual",
            ),
            "pdf_path": pdf["path"],
            "pdf_available": pdf["available"],
        },
        "food_rules": load_food_rules(),
        "store_sections": list(STORE_SECTION_ORDER.keys()),
    }


def editable_recipe_cover_image(url, recipe_data, recipe_meta=None):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    cover_image = recipe_data.get("cover_image")

    if not isinstance(cover_image, dict) or not cover_image:
        cover_image = recipe_meta.get("cover_image")

    if not isinstance(cover_image, dict) or not cover_image:
        return {}

    source_url = str(recipe_data.get("source_url") or url or "").strip()
    fallback_alt = (
        str(cover_image.get("alt") or "").strip()
        or str(recipe_data.get("recipe_title") or recipe_meta.get("name") or "Recipe title image").strip()
    )
    normalized = normalize_recipe_cover_image(
        cover_image,
        base_url=source_url,
        fallback_alt=fallback_alt,
    )

    if not normalized:
        return {}

    src = ""
    if normalized.get("path") and source_url:
        src = f"/recipe_cover_image?url={quote(source_url, safe='')}"
    elif normalized.get("url"):
        src = normalized.get("url")

    return {
        **normalized,
        "alt": normalized.get("alt") or fallback_alt,
        "src": src,
    }


def editable_recipe_pdf_info(url):
    pdf_path = recipe_archive_pdf_path(url)

    return {
        "path": str(pdf_path),
        "available": pdf_path.exists(),
    }


def editable_recipe_source_display_url(url):
    if recipe_url_type(url) == "File":
        return str(recipe_archive_pdf_path(url))

    return url


def recipe_information_fields(recipe_data, url=""):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    parsed = {}

    if not all(recipe_info_value(recipe_data, key) for key in recipe_information_keys()):
        parsed = extract_recipe_info_from_saved_text(url)

    return {
        key: recipe_info_value(recipe_data, key) or parsed.get(key, "")
        for key in recipe_information_keys()
    }


def recipe_information_keys():
    return ("level", "total_time", "prep_time", "inactive_time", "cook_time")


def recipe_info_value(recipe_data, key):
    aliases = {
        "level": ("level", "difficulty", "recipe_difficulty"),
        "total_time": ("total_time", "total", "recipe_total_time"),
        "prep_time": ("prep_time", "prep", "recipe_prep_time"),
        "inactive_time": ("inactive_time", "inactive", "recipe_inactive_time"),
        "cook_time": ("cook_time", "cook", "recipe_cook_time"),
    }

    for alias in aliases.get(key, (key,)):
        value = str(recipe_data.get(alias) or "").strip()
        if value:
            return value

    return ""


def extract_recipe_info_from_saved_text(url):
    url = str(url or "").strip()
    if not url:
        return {}

    text_path = RAW_FOLDER / f"{safe_filename(url)}_PAGE_TEXT.txt"

    if not text_path.exists():
        return {}

    try:
        return extract_recipe_info_from_text(text_path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}


def create_editable_recipe_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(url)

    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    title = (
        recipe_data.get("recipe_title")
        or load_recipe_ingredients().get(normalize_recipe_url_key(url), {}).get("name")
        or "Recipe"
    )
    html_text = build_video_text_pdf_html(
        url,
        "",
        title,
        recipe_data=recipe_data,
    )
    pdf_path = recipe_archive_pdf_path(url)
    saved_path = write_recipe_page_pdf(url, html_text, None, pdf_path)

    return {
        "ok": True,
        "url": url,
        "pdf_path": str(saved_path),
        "pdf_available": True,
    }


def create_source_url_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Source URL is required."}

    if not is_web_source_url(url):
        return create_editable_recipe_pdf(url)

    try:
        fetch_recipe_page(url)
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "error": f"Webpage PDF creation failed: {exc}",
        }

    pdf_path = recipe_archive_pdf_path(url)

    return {
        "ok": pdf_path.exists(),
        "url": url,
        "pdf_path": str(pdf_path),
        "pdf_available": pdf_path.exists(),
        "error": None if pdf_path.exists() else "PDF file was not created.",
    }


def is_web_source_url(url):
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def delete_editable_recipe_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    pdf_path = recipe_archive_pdf_path(url)

    try:
        pdf_path.unlink(missing_ok=True)
    except PermissionError:
        return {
            "ok": False,
            "error": "Close the PDF before deleting it.",
            "url": url,
            "pdf_path": str(pdf_path),
            "pdf_available": pdf_path.exists(),
        }

    return {
        "ok": True,
        "url": url,
        "pdf_path": str(pdf_path),
        "pdf_available": False,
    }


def save_editable_recipe(original_url, payload):
    original_url = str(original_url or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    source_url = str(payload.get("source_url") or original_url).strip()

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not source_url:
        source_url = original_url

    previous_recipe_data = load_recipe_ingredients()
    previous_ingredients = recipe_ingredients_for_key(
        normalize_recipe_url_key(original_url),
        previous_recipe_data,
    )
    existing_data = load_recipe_output(original_url) or {"source_url": original_url}
    cover_image = sanitize_recipe_cover_image(
        payload.get("cover_image") or existing_data.get("cover_image"),
        source_url,
        payload.get("recipe_title") or existing_data.get("recipe_title") or "",
    )
    recipe_data = {
        **existing_data,
        "source_url": source_url,
        "recipe_title": str(payload.get("recipe_title") or "").strip(),
        "servings": str(payload.get("servings") or "").strip(),
        "level": str(payload.get("level") or "").strip(),
        "total_time": str(payload.get("total_time") or "").strip(),
        "prep_time": str(payload.get("prep_time") or "").strip(),
        "inactive_time": str(payload.get("inactive_time") or "").strip(),
        "cook_time": str(payload.get("cook_time") or "").strip(),
        "scaling": normalize_recipe_scaling_metadata(
            payload.get("scaling") or existing_data.get("scaling")
        ),
        "ingredients": sanitize_ingredients(payload.get("ingredients", [])),
        "equipment": sanitize_equipment_list(
            payload.get("equipment", []),
            existing_data.get("equipment", []),
        ),
        "instructions": sanitize_instruction_list(
            payload.get("instructions", []),
            existing_data.get("instructions", []),
        ),
        "nutrition": sanitize_nutrition(payload.get("nutrition", [])),
    }
    if cover_image:
        recipe_data["cover_image"] = cover_image
    else:
        recipe_data.pop("cover_image", None)
    if recipe_data["servings"] and not recipe_data["scaling"].get("base_servings"):
        recipe_data["scaling"]["base_servings"] = recipe_data["servings"]

    normalize_extracted_ingredient_fields(recipe_data)
    normalize_extracted_equipment_fields(recipe_data)
    save_recipe_output(source_url, recipe_data)

    if normalize_recipe_url_key(source_url) != normalize_recipe_url_key(original_url):
        replace_recipe_url(original_url, source_url)
        move_recipe_meta(original_url, source_url)

    quantity = normalize_recipe_quantity(payload.get("quantity", 1))
    display_name = str(payload.get("display_name") or "").strip()

    save_recipe_url_quantity(source_url, quantity)
    save_recipe_url_name(source_url, display_name)
    update_recipe_ingredient_record(source_url, quantity, recipe_data)
    update_recipe_quantity(source_url, quantity)
    sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients)

    return load_editable_recipe(source_url)


def save_recipe_cover_image_upload(original_url, uploaded_file, source_url="", fallback_alt=""):
    original_url = str(original_url or "").strip()
    source_url = str(source_url or original_url).strip() or original_url

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not uploaded_file or not uploaded_file.filename:
        return {"ok": False, "error": "No title image was selected."}

    mime_type = str(
        uploaded_file.mimetype
        or mimetypes.guess_type(uploaded_file.filename or "")[0]
        or ""
    ).split(";", 1)[0].strip().lower()
    guessed_mime_type = str(mimetypes.guess_type(uploaded_file.filename or "")[0] or "").lower()
    if not mime_type.startswith("image/") and guessed_mime_type.startswith("image/"):
        mime_type = guessed_mime_type
    extension = recipe_cover_upload_extension(uploaded_file.filename, mime_type)

    if not extension or not mime_type.startswith("image/"):
        return {"ok": False, "error": "Choose a PNG, JPG, WebP, GIF, BMP, or AVIF image."}

    COVER_IMAGE_UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    upload_path = COVER_IMAGE_UPLOAD_FOLDER / (
        f"{safe_filename(source_url or original_url)}_title_{uuid.uuid4().hex}{extension}"
    )
    uploaded_file.save(upload_path)

    existing_data = load_recipe_output(original_url) or {"source_url": source_url}
    recipe_source_url = str(existing_data.get("source_url") or source_url or original_url).strip()
    alt = str(fallback_alt or existing_data.get("recipe_title") or "Recipe title image").strip()
    cover_image = extract_recipe_cover_image_from_upload(
        upload_path,
        mime_type,
        uploaded_file.filename,
        recipe_source_url,
        fallback_alt=alt,
    )

    if not cover_image:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": "Unable to save this title image."}

    existing_data["source_url"] = recipe_source_url
    existing_data["cover_image"] = cover_image
    save_recipe_output(recipe_source_url, existing_data)

    recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(recipe_source_url), {})
    quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
    update_recipe_ingredient_record(recipe_source_url, quantity, existing_data)

    loaded = load_editable_recipe(recipe_source_url)
    response_recipe = loaded.get("recipe", {})
    response_cover_image = response_recipe.get("cover_image") or editable_recipe_cover_image(
        recipe_source_url,
        existing_data,
        recipe_meta,
    )

    return {
        "ok": True,
        "cover_image": response_cover_image,
        "recipe": response_recipe,
    }


def recipe_cover_upload_extension(filename, mime_type=""):
    suffix = Path(str(filename or "")).suffix.lower()

    if suffix in COVER_IMAGE_EXTENSIONS:
        return suffix

    normalized_mime_type = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime_type in COVER_IMAGE_MIME_EXTENSIONS:
        return COVER_IMAGE_MIME_EXTENSIONS[normalized_mime_type]

    guessed_extension = mimetypes.guess_extension(normalized_mime_type or "")
    guessed_extension = ".jpg" if guessed_extension == ".jpe" else guessed_extension

    if guessed_extension in COVER_IMAGE_EXTENSIONS:
        return guessed_extension

    return ""


def sanitize_recipe_cover_image(value, source_url="", fallback_alt=""):
    cover_image = normalize_recipe_cover_image(
        value,
        base_url=str(source_url or ""),
        fallback_alt=str(fallback_alt or "Recipe title image"),
    )

    if not cover_image:
        return {}

    return cover_image


def estimate_recipe_nutrition(payload):
    payload = payload if isinstance(payload, dict) else {}

    if not payload.get("ingredients"):
        return {
            "ok": False,
            "error": "Add at least one ingredient before estimating nutrition.",
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    serving_basis = recipe_nutrition_serving_basis(payload.get("nutrition"))
    prompt = build_nutrition_estimate_prompt(payload, serving_basis)

    try:
        response = get_openai_client().chat.completions.create(
            model=os.getenv("OPENAI_NUTRITION_MODEL", MODEL),
            messages=[
                {
                    "role": "system",
                    "content": "You estimate recipe nutrition and return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        data = json.loads(clean_json_response(content))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Nutrition estimate failed: {exc}",
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "Nutrition estimate returned an unexpected response.",
        }

    nutrition = data.get("nutrition") if isinstance(data.get("nutrition"), dict) else data

    rows = [{"key": "serving_basis", "value": serving_basis}]
    for key in NUTRITION_ESTIMATE_FIELDS:
        value = normalize_estimated_nutrition_value(key, nutrition.get(key))
        rows.append({"key": key, "value": value})

    return {
        "ok": True,
        "nutrition": rows,
    }


def generate_recipe_step_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    requested_step = payload.get("step_number")

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"ok": False, "error": "Image generation is not set up yet."}

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_title = str(recipe_data.get("recipe_title") or "").strip()
    if not recipe_title:
        return {"ok": False, "error": "Add a recipe title before generating a step image."}

    instructions = sorted(
        normalize_instruction_records(recipe_data.get("instructions", [])),
        key=lambda item: item["step_number"],
    )
    target_index, target_instruction = find_instruction_for_step(instructions, requested_step)

    if target_instruction is None:
        return {"ok": False, "error": "Instruction step was not found."}

    instruction_text = str(target_instruction.get("instruction") or target_instruction.get("text") or "").strip()
    if not instruction_text:
        return {"ok": False, "error": "Add instruction text before generating a step image."}

    prompt = build_recipe_step_image_prompt(
        recipe_title=recipe_title,
        servings=str(recipe_data.get("servings") or "").strip(),
        ingredients=recipe_step_image_prompt_ingredients(recipe_data.get("ingredients", [])),
        equipment=recipe_step_image_prompt_equipment(recipe_data.get("equipment", [])),
        step_number=target_instruction.get("step_number"),
        instruction_step=instruction_text,
    )

    progress_target = target_instruction.get("step_number")
    start_recipe_image_progress("step", url, progress_target, "Generating step image...")

    try:
        image_bytes = request_recipe_step_image_bytes(prompt)
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    step_image_url = save_recipe_step_image_file(url, target_instruction.get("step_number"), image_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()
    target_instruction["step_image_url"] = step_image_url
    target_instruction["step_image_generated_at"] = generated_at

    instructions[target_index] = {
        **target_instruction,
        "instruction": instruction_text,
        "text": instruction_text,
    }
    recipe_data["instructions"] = instructions
    save_recipe_output(url, recipe_data)
    finish_recipe_image_progress(
        "step",
        url,
        progress_target,
        ok=True,
        image_url=step_image_url,
        generated_at=generated_at,
    )

    return {
        "ok": True,
        "url": url,
        "step_number": target_instruction.get("step_number"),
        "step_image_url": step_image_url,
        "step_image_generated_at": generated_at,
    }


def generate_recipe_equipment_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    requested_index = payload.get("equipment_index") or payload.get("equipment_number")

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"ok": False, "error": "Image generation is not set up yet."}

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_title = str(recipe_data.get("recipe_title") or "").strip()
    if not recipe_title:
        return {"ok": False, "error": "Add a recipe title before generating an equipment image."}

    equipment_items = normalize_equipment_records(recipe_data.get("equipment", []))
    target_index, target_equipment = find_equipment_for_index(equipment_items, requested_index)

    if target_equipment is None:
        return {"ok": False, "error": "Equipment item was not found."}

    equipment_text = str(
        target_equipment.get("equipment")
        or target_equipment.get("text")
        or target_equipment.get("name")
        or ""
    ).strip()
    if not equipment_text:
        return {"ok": False, "error": "Add equipment text before generating an image."}

    prompt = build_recipe_equipment_image_prompt(
        recipe_title=recipe_title,
        servings=str(recipe_data.get("servings") or "").strip(),
        ingredients=recipe_step_image_prompt_ingredients(recipe_data.get("ingredients", [])),
        equipment_item_number=target_index + 1,
        equipment_item=equipment_text,
    )

    progress_target = target_index + 1
    start_recipe_image_progress("equipment", url, progress_target, "Generating equipment image...")

    try:
        image_bytes = request_recipe_step_image_bytes(prompt)
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    equipment_image_url = save_recipe_equipment_image_file(url, target_index + 1, image_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()
    target_equipment["equipment_image_url"] = equipment_image_url
    target_equipment["equipment_image_generated_at"] = generated_at

    equipment_items[target_index] = {
        **target_equipment,
        "equipment": equipment_text,
        "text": equipment_text,
    }
    recipe_data["equipment"] = equipment_items
    save_recipe_output(url, recipe_data)
    finish_recipe_image_progress(
        "equipment",
        url,
        progress_target,
        ok=True,
        image_url=equipment_image_url,
        generated_at=generated_at,
    )

    return {
        "ok": True,
        "url": url,
        "equipment_index": target_index + 1,
        "equipment_image_url": equipment_image_url,
        "equipment_image_generated_at": generated_at,
    }


def find_equipment_for_index(equipment_items, requested_index):
    try:
        index = int(float(requested_index)) - 1
    except (TypeError, ValueError):
        index = -1

    if 0 <= index < len(equipment_items):
        return index, equipment_items[index]

    return -1, None


def find_instruction_for_step(instructions, requested_step):
    requested_key = instruction_match_step_key(requested_step)

    for index, instruction in enumerate(instructions):
        if instruction_match_step_key(instruction.get("step_number")) == requested_key:
            return index, instruction

    try:
        requested_index = int(float(requested_step)) - 1
    except (TypeError, ValueError):
        requested_index = -1

    if 0 <= requested_index < len(instructions):
        return requested_index, instructions[requested_index]

    return -1, None


def build_recipe_step_image_prompt(
    recipe_title,
    servings,
    ingredients,
    equipment,
    step_number,
    instruction_step,
):
    return f"""Generate a realistic cookbook-style image for one recipe instruction step.

Recipe title:
{recipe_title}

Servings:
{servings or "Not specified"}

Ingredients:
{ingredients or "Not specified"}

Equipment:
{equipment or "Not specified"}

Step number:
{step_number}

Instruction step:
{instruction_step}

Visual requirements:
- Show only this specific cooking step
- Use the actual ingredients from the recipe
- Bright natural kitchen lighting
- Realistic food photography
- Clean kitchen counter background
- High-end cookbook style
- No text inside the image
- No numbered badges
- No labels
- Make the cooking action visually clear
- Final step should show the finished dish if the instruction is about serving or garnish
"""


def build_recipe_equipment_image_prompt(
    recipe_title,
    servings,
    ingredients,
    equipment_item_number,
    equipment_item,
):
    return f"""Generate a realistic cookbook-style image for one recipe equipment item.

Recipe title:
{recipe_title}

Servings:
{servings or "Not specified"}

Ingredients:
{ingredients or "Not specified"}

Equipment item number:
{equipment_item_number}

Equipment item:
{equipment_item}

Visual requirements:
- Show only this specific equipment item
- Make the equipment visually clear and easy to identify
- It should look ready to use for this recipe
- Include actual recipe ingredients nearby only if they help communicate scale or use
- Bright natural kitchen lighting
- Realistic food photography
- Clean kitchen counter background
- High-end cookbook style
- No text inside the image
- No numbered badges
- No labels
"""


def recipe_step_image_prompt_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return ""

    rows = []
    for item in ingredients:
        if not isinstance(item, dict):
            text = str(item or "").strip()
            if text:
                rows.append(f"- {text}")
            continue

        name = str(item.get("ingredient") or item.get("original_text") or "").strip()
        quantity = str(item.get("quantity") or item.get("recipe_qty") or "").strip()
        unit = str(item.get("unit") or "").strip()
        preparation = str(item.get("preparation") or "").strip()
        text = " ".join(part for part in [quantity, unit, name] if part).strip()
        if preparation:
            text = f"{text}, {preparation}" if text else preparation

        if text:
            rows.append(f"- {text}")

    return "\n".join(rows[:80])


def recipe_step_image_prompt_equipment(equipment):
    rows = normalize_text_rows(equipment)
    return "\n".join(f"- {item}" for item in rows[:40])


def request_recipe_step_image_bytes(prompt):
    timeout_seconds = int(os.getenv("OPENAI_STEP_IMAGE_TIMEOUT_SECONDS", "90"))
    model = os.getenv("OPENAI_STEP_IMAGE_MODEL", "gpt-image-1")
    size = os.getenv("OPENAI_STEP_IMAGE_SIZE", "1024x1024")
    quality = os.getenv("OPENAI_STEP_IMAGE_QUALITY", "medium")

    client = get_openai_client()
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_seconds)

    try:
        response = client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )
    except Exception as exc:
        if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
            raise TimeoutError() from exc
        raise

    image_record = first_openai_image_record(response)
    if not image_record:
        return b""

    b64_json = openai_image_field(image_record, "b64_json")
    if b64_json:
        encoded = str(b64_json).split(",", 1)[-1]
        return base64.b64decode(encoded)

    image_url = openai_image_field(image_record, "url")
    if image_url:
        try:
            result = requests.get(image_url, timeout=timeout_seconds)
            result.raise_for_status()
        except requests.Timeout as exc:
            raise TimeoutError() from exc
        return result.content

    return b""


def first_openai_image_record(response):
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")

    if not data:
        return None

    return data[0]


def openai_image_field(image_record, field_name):
    if isinstance(image_record, dict):
        return image_record.get(field_name)

    return getattr(image_record, field_name, None)


def save_recipe_step_image_file(recipe_url, step_number, image_bytes):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    step_key = safe_filename(str(step_number or "step"))
    filename = f"{safe_filename(recipe_url)}_step_{step_key}_{uuid.uuid4().hex[:12]}.png"
    image_path = STEP_IMAGE_FOLDER / filename
    image_path.write_bytes(image_bytes)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}"


def save_recipe_equipment_image_file(recipe_url, equipment_index, image_bytes):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    equipment_key = safe_filename(str(equipment_index or "equipment"))
    filename = f"{safe_filename(recipe_url)}_equipment_{equipment_key}_{uuid.uuid4().hex[:12]}.png"
    image_path = STEP_IMAGE_FOLDER / filename
    image_path.write_bytes(image_bytes)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}"


def recipe_nutrition_serving_basis(nutrition_rows):
    if isinstance(nutrition_rows, dict):
        return str(nutrition_rows.get("serving_basis") or "per serving").strip() or "per serving"

    if isinstance(nutrition_rows, list):
        for row in nutrition_rows:
            if not isinstance(row, dict):
                continue

            key = str(row.get("key") or row.get("label") or "").strip().lower()
            if key == "serving_basis":
                return str(row.get("value") or "per serving").strip() or "per serving"

    return "per serving"


def build_nutrition_estimate_prompt(recipe, serving_basis):
    recipe_payload = {
        "title": str(recipe.get("recipe_title") or recipe.get("display_name") or "").strip(),
        "servings": str(recipe.get("servings") or "").strip(),
        "serving_basis": serving_basis,
        "ingredients": nutrition_prompt_ingredients(recipe.get("ingredients", [])),
        "equipment": sanitize_text_list(recipe.get("equipment", [])),
        "instructions": nutrition_prompt_instructions(recipe.get("instructions", [])),
    }

    return f"""
Estimate the nutrition values for this recipe.

Return ONLY valid JSON with this exact shape:
{{
  "nutrition": {{
    "calories": "659 kcal",
    "carbohydrates": "57 g",
    "protein": "17 g",
    "fat": "40 g",
    "saturated_fat": "16 g",
    "cholesterol": "37 mg",
    "sodium": "649 mg",
    "fiber": "3 g",
    "sugar": "0.2 g"
  }}
}}

Rules:
- Estimate values for the serving basis: {serving_basis}.
- Use the recipe servings to divide the full recipe when servings are available.
- Use the provided ingredient quantities, units, and preparation details.
- Use common USDA-style approximations when exact brands are unknown.
- Do not invent extra ingredients.
- Return strings with units.
- calories must use kcal.
- carbohydrates, protein, fat, saturated_fat, fiber, and sugar must use g.
- cholesterol and sodium must use mg.
- If a value cannot be estimated, use an empty string.

Recipe JSON:
{json.dumps(recipe_payload, ensure_ascii=False, indent=2)}
"""


def nutrition_prompt_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    rows = []
    for item in ingredients:
        if not isinstance(item, dict):
            continue

        rows.append({
            "ingredient": str(item.get("ingredient") or "").strip(),
            "quantity": str(item.get("quantity") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "preparation": str(item.get("preparation") or "").strip(),
            "original_text": str(item.get("original_text") or "").strip(),
        })

    return [
        row
        for row in rows
        if row["ingredient"] or row["original_text"]
    ]


def nutrition_prompt_instructions(instructions):
    if not isinstance(instructions, list):
        return []

    rows = []
    for item in instructions:
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_estimated_nutrition_value(key, value):
    if value is None:
        return ""

    if isinstance(value, dict):
        amount = str(value.get("amount") or value.get("value") or "").strip()
        unit = str(value.get("unit") or "").strip()
        return f"{amount} {unit}".strip()

    if isinstance(value, (int, float)):
        if key == "calories":
            return f"{value:g} kcal"

        if key in {"cholesterol", "sodium"}:
            return f"{value:g} mg"

        return f"{value:g} g"

    return str(value or "").strip()


def sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients):
    ingredients = extract_ingredients_from_result(recipe_data)

    if ingredients:
        add_items(ingredients)

    remove_unused_ingredients_from_shopping_list(
        previous_ingredients,
        load_recipe_ingredients(),
    )
    sort_ingredients()


def load_recipe_output(url):
    recipe_key = normalize_recipe_url_key(url)

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if normalize_recipe_url_key(data.get("source_url", "")) == recipe_key:
            return data

    return None


def save_recipe_output(url, recipe_data):
    json_path = OUTPUT_FOLDER / f"{safe_filename(url)}.json"
    json_path.write_text(
        json.dumps(recipe_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


def replace_recipe_url(original_url, source_url):
    original_key = normalize_recipe_url_key(original_url)
    source_key = normalize_recipe_url_key(source_url)
    next_urls = []
    replaced = False

    for url in load_recipe_urls():
        if normalize_recipe_url_key(url) == original_key:
            if not any(normalize_recipe_url_key(item) == source_key for item in next_urls):
                next_urls.append(source_url)
            replaced = True
        else:
            next_urls.append(url)

    if not replaced:
        next_urls.append(source_url)

    save_recipe_urls(next_urls)


def move_recipe_meta(original_url, source_url):
    data = load_recipe_ingredients()
    original_key = normalize_recipe_url_key(original_url)
    source_key = normalize_recipe_url_key(source_url)

    if original_key == source_key or original_key not in data:
        return

    existing = data.pop(original_key)
    destination = data.get(source_key, {})
    destination.update(existing)
    destination["url"] = source_url
    data[source_key] = destination
    save_recipe_ingredients(data)


def update_recipe_ingredient_record(url, quantity, recipe_data):
    data = load_recipe_ingredients()
    key = normalize_recipe_url_key(url)
    existing = data.get(key, {})
    cover_image = recipe_data.get("cover_image") or existing.get("cover_image")
    record = {
        "url": url,
        "quantity": quantity,
        "name": existing.get("name"),
        "scaled_servings": existing.get("scaled_servings"),
        "scaled_ingredients": existing.get("scaled_ingredients", {}),
        "ingredients": extract_ingredients_from_result(recipe_data),
    }

    if cover_image:
        record["cover_image"] = cover_image

    data[key] = record
    save_recipe_ingredients(data)


def normalize_edit_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    rows = [
        apply_purchase_mapping_to_ingredient({
            "section": item.get("section") or "",
            "original_text": item.get("original_text") or "",
            "quantity": item.get("quantity") or "",
            "recipe_qty": item.get("recipe_qty") or item.get("quantity") or "",
            "unit": item.get("unit") or "",
            "base_quantity": item.get("base_quantity") or item.get("quantity") or "",
            "base_unit": item.get("base_unit") or item.get("unit") or "",
            "ingredient": item.get("ingredient") or "",
            "preparation": item.get("preparation") or "",
            "optional": bool(item.get("optional")),
            "store_section": item.get("store_section") or classify_store_section(item.get("ingredient") or ""),
            "purchasable_item": item.get("purchasable_item") or item.get("buy_as") or "",
            "purchase_group": item.get("purchase_group") or "",
        })
        for item in ingredients
        if isinstance(item, dict)
    ]
    return rows


def normalize_text_rows(value):
    if isinstance(value, str):
        return [value] if value.strip() else []

    if not isinstance(value, list):
        return []

    rows = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("name") or item.get("text") or item.get("equipment") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_equipment_records(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_rows(value)

    records = []
    for index, item in enumerate(value, start=1):
        record = dict(item) if isinstance(item, dict) else {}
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
            equipment_image_url = str(item.get("equipment_image_url") or item.get("image_url") or "").strip()
            equipment_image_generated_at = str(
                item.get("equipment_image_generated_at") or item.get("image_generated_at") or ""
            ).strip()
        else:
            text = str(item or "").strip()
            equipment_image_url = ""
            equipment_image_generated_at = ""

        if not text:
            continue

        record.update({
            "equipment": text,
            "text": text,
            "equipment_image_url": equipment_image_url,
            "equipment_image_generated_at": equipment_image_generated_at,
        })
        records.append(record)

    return records


def normalize_instruction_rows(value):
    return sorted(
        normalize_instruction_records(value),
        key=lambda item: item["step_number"],
    )


def normalize_nutrition_rows(nutrition, include_defaults=False):
    if not isinstance(nutrition, dict):
        return []

    rows = []
    included = set()

    if include_defaults:
        for key in DEFAULT_MANUAL_NUTRITION_FIELDS:
            fallback = "per serving" if key == "serving_basis" else ""
            rows.append({"key": key, "value": str(nutrition.get(key) or fallback)})
            included.add(key)

    for key in NUTRITION_FIELDS:
        if key in included or not nutrition.get(key):
            continue

        rows.append({"key": key, "value": str(nutrition.get(key) or "")})
        included.add(key)

    other = nutrition.get("other", [])
    if isinstance(other, list):
        for item in other:
            if isinstance(item, dict):
                key = str(item.get("label") or item.get("name") or "").strip()
                value = str(item.get("value") or item.get("amount") or "").strip()
                if key or value:
                    rows.append({"key": key, "value": value})

    return rows


def sanitize_ingredients(value):
    if not isinstance(value, list):
        return []

    ingredients = []
    for item in value:
        if not isinstance(item, dict):
            continue

        name = str(item.get("ingredient") or "").strip()
        original_text = str(item.get("original_text") or "").strip()

        if not name and not original_text:
            continue

        store_section = classify_store_section(name or original_text)
        base_quantity = nullable_string(item.get("base_quantity"))
        base_unit = nullable_string(item.get("base_unit"))

        row = {
            "section": nullable_string(item.get("section")),
            "original_text": original_text,
            "quantity": nullable_string(item.get("quantity")),
            "recipe_qty": nullable_string(item.get("recipe_qty") or item.get("quantity")),
            "unit": nullable_string(item.get("unit")),
            "base_quantity": base_quantity or nullable_string(item.get("quantity")),
            "base_unit": base_unit or nullable_string(item.get("unit")),
            "ingredient": name or original_text,
            "preparation": nullable_string(item.get("preparation")),
            "optional": bool(item.get("optional")),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER.get(store_section, STORE_SECTION_ORDER["MISC"]),
            "purchasable_item": nullable_string(item.get("purchasable_item") or item.get("buy_as")),
            "purchase_group": nullable_string(item.get("purchase_group")),
        }
        ingredients.append(apply_purchase_mapping_to_ingredient(row))

    return ingredients


def sanitize_text_list(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    rows = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def sanitize_equipment_list(value, existing_value=None):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    existing_rows = normalize_equipment_records(existing_value or [])
    existing_by_text = {
        instruction_match_text_key(item.get("equipment") or item.get("text")): item
        for item in existing_rows
        if instruction_match_text_key(item.get("equipment") or item.get("text"))
    }
    equipment = []

    for index, item in enumerate(value):
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
            equipment_image_url = nullable_string(item.get("equipment_image_url") or item.get("image_url"))
            equipment_image_generated_at = nullable_string(
                item.get("equipment_image_generated_at") or item.get("image_generated_at")
            )
        else:
            text = str(item or "").strip()
            equipment_image_url = ""
            equipment_image_generated_at = ""

        if not text:
            continue

        existing = existing_by_text.get(instruction_match_text_key(text))
        if existing is None and index < len(existing_rows):
            existing = existing_rows[index]
        existing = existing or {}
        equipment_image_url = equipment_image_url or nullable_string(existing.get("equipment_image_url")) or ""
        equipment_image_generated_at = (
            equipment_image_generated_at
            or nullable_string(existing.get("equipment_image_generated_at"))
            or ""
        )

        equipment.append({
            "equipment": text,
            "text": text,
            "equipment_image_url": equipment_image_url,
            "equipment_image_generated_at": equipment_image_generated_at,
        })

    return equipment


def sanitize_instruction_list(value, existing_value=None):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    existing_rows = normalize_instruction_records(existing_value or [])
    existing_by_step = {
        instruction_match_step_key(item.get("step_number")): item
        for item in existing_rows
    }
    existing_by_text = {
        instruction_match_text_key(item.get("instruction")): item
        for item in existing_rows
        if instruction_match_text_key(item.get("instruction"))
    }
    instructions = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
            step_number = normalize_step_number(item.get("step_number"), index)
            step_image_url = nullable_string(item.get("step_image_url") or item.get("image_url"))
            step_image_generated_at = nullable_string(
                item.get("step_image_generated_at") or item.get("image_generated_at")
            )
        else:
            text = str(item or "").strip()
            step_number = index
            step_image_url = ""
            step_image_generated_at = ""

        if not text:
            continue

        existing = (
            existing_by_step.get(instruction_match_step_key(step_number))
            or existing_by_text.get(instruction_match_text_key(text))
            or {}
        )
        step_image_url = step_image_url or nullable_string(existing.get("step_image_url")) or ""
        step_image_generated_at = (
            step_image_generated_at
            or nullable_string(existing.get("step_image_generated_at"))
            or ""
        )

        instructions.append({
            "section": None,
            "step_number": step_number,
            "instruction": text,
            "text": text,
            "temperature": None,
            "time": None,
            "equipment_used": [],
            "step_image_url": step_image_url,
            "step_image_generated_at": step_image_generated_at,
        })

    return sorted(instructions, key=lambda item: item["step_number"])


def normalize_instruction_records(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_rows(value)

    records = []
    for index, item in enumerate(value, start=1):
        record = dict(item) if isinstance(item, dict) else {}
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
            step_number = normalize_step_number(item.get("step_number"), index)
            step_image_url = str(item.get("step_image_url") or item.get("image_url") or "").strip()
            step_image_generated_at = str(
                item.get("step_image_generated_at") or item.get("image_generated_at") or ""
            ).strip()
        else:
            text = str(item or "").strip()
            step_number = index
            step_image_url = ""
            step_image_generated_at = ""

        if not text:
            continue

        record.update({
            "step_number": step_number,
            "instruction": text,
            "text": text,
            "step_image_url": step_image_url,
            "step_image_generated_at": step_image_generated_at,
        })
        records.append(record)

    return records


def instruction_match_step_key(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()

    if number.is_integer():
        return str(int(number))

    return f"{number:g}"


def instruction_match_text_key(value):
    return " ".join(str(value or "").strip().lower().split())


def normalize_step_number(value, fallback):
    try:
        step_number = float(value)
    except (TypeError, ValueError):
        return fallback

    if step_number <= 0:
        return fallback

    if step_number.is_integer():
        return int(step_number)

    return step_number


def sanitize_nutrition(value):
    if not isinstance(value, list):
        return {}

    nutrition = {}
    other = []

    for item in value:
        if not isinstance(item, dict):
            continue

        key = str(item.get("key") or "").strip()
        value_text = str(item.get("value") or "").strip()

        if not key or not value_text:
            continue

        normalized_key = key.lower().replace(" ", "_").replace("-", "_")
        if normalized_key in NUTRITION_FIELDS:
            nutrition[normalized_key] = value_text
        else:
            other.append({"label": key, "value": value_text})

    if other:
        nutrition["other"] = other

    return nutrition


def nullable_string(value):
    text = str(value or "").strip()
    return text or None
