from pathlib import Path

from flask import render_template

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services.menu_store_service import get_menu
from PushShoppingList.services.menu_store_service import latest_menu_pdf_log
from PushShoppingList.services.menu_store_service import record_menu_pdf_generated
from PushShoppingList.services.menu_store_service import update_menu_pdf_log
from PushShoppingList.services.menu_store_service import utc_now_iso
from PushShoppingList.services.recipe_extract_service import safe_filename
from PushShoppingList.services.recipe_extract_service import write_recipe_page_pdf
from PushShoppingList.services.storage_service import scoped_extractor_data_path


MENU_PDF_DIR = scoped_extractor_data_path("menu_pdf")


def menu_pdf_storage_dir():
    path = Path(MENU_PDF_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def menu_pdf_filename(detail):
    menu = detail.get("menu", {}) if isinstance(detail, dict) else {}
    restaurant = detail.get("restaurant", {}) if isinstance(detail, dict) else {}
    label = (
        menu.get("menu_title")
        or restaurant.get("restaurant_name")
        or menu.get("id")
        or "restaurant-menu"
    )
    return f"{safe_filename(label)}_menu.pdf"


def menu_pdf_path(menu_id):
    detail = get_menu(menu_id)
    if not detail:
        return menu_pdf_storage_dir() / f"{safe_filename(menu_id)}_menu.pdf"
    return menu_pdf_storage_dir() / menu_pdf_filename(detail)


def render_menu_pdf_html(menu_id):
    detail = get_menu(menu_id)
    if not detail:
        raise ValueError("Menu was not found.")
    return render_template("menus/menu_pdf.html", menu_detail=detail)


def generate_menu_pdf(menu_id):
    detail = get_menu(menu_id)
    if not detail:
        return {"ok": False, "success": False, "error": "Menu was not found."}

    menu = detail.get("menu", {})
    pdf_path = menu_pdf_path(menu_id)
    html_text = render_menu_pdf_html(menu_id)
    try:
        saved_path = write_recipe_page_pdf(
            f"menu://{menu_id}",
            html_text,
            None,
            pdf_path,
        )
        log = record_menu_pdf_generated(
            menu_id,
            menu.get("menu_title") or "Restaurant Menu",
            saved_path,
            generated_by_model=menu.get("generated_by_model", ""),
            status="generated",
        )
        return {
            "ok": True,
            "success": True,
            "menu_id": menu_id,
            "pdf_path": str(saved_path),
            "local_pdf_path": str(saved_path),
            "pdf_log": log,
            "pdf_log_id": log.get("id", ""),
        }
    except Exception as exc:
        log = record_menu_pdf_generated(
            menu_id,
            menu.get("menu_title") or "Restaurant Menu",
            pdf_path,
            generated_by_model=menu.get("generated_by_model", ""),
            status="failed",
            error_message=str(exc),
        )
        return {
            "ok": False,
            "success": False,
            "menu_id": menu_id,
            "pdf_path": str(pdf_path),
            "local_pdf_path": str(pdf_path),
            "pdf_log": log,
            "pdf_log_id": log.get("id", ""),
            "error": str(exc) or "Unable to generate menu PDF.",
        }


def upload_menu_pdf(menu_id, log_id=""):
    detail = get_menu(menu_id)
    if not detail:
        return {"ok": False, "success": False, "error": "Menu was not found."}

    log = {}
    if log_id:
        log = next(
            (candidate for candidate in detail.get("pdf_logs", []) if candidate.get("id") == log_id),
            {},
        )
    if not log:
        log = latest_menu_pdf_log(menu_id)

    local_pdf_path = Path(str(log.get("local_pdf_path") or menu_pdf_path(menu_id)))
    if not local_pdf_path.exists():
        generated = generate_menu_pdf(menu_id)
        if not generated.get("ok"):
            return generated
        log = generated.get("pdf_log", {})
        local_pdf_path = Path(generated.get("local_pdf_path") or menu_pdf_path(menu_id))

    upload_result = cloudflare_r2_storage.upload_pdf(
        local_pdf_path,
        object_prefix=cloudflare_r2_storage.MENU_PDF_OBJECT_PREFIX,
    )
    if not upload_result.get("ok"):
        updated = update_menu_pdf_log(
            log.get("id", ""),
            status="failed",
            error_message=upload_result.get("error", "Unable to upload menu PDF to Cloudflare R2."),
        )
        return {
            "ok": False,
            "success": False,
            "menu_id": menu_id,
            "pdf_path": str(local_pdf_path),
            "local_pdf_path": str(local_pdf_path),
            "pdf_log": updated or log,
            "pdf_log_id": (updated or log).get("id", ""),
            "cloudflare_upload": upload_result,
            "error": upload_result.get("error", "Unable to upload menu PDF to Cloudflare R2."),
        }

    updated = update_menu_pdf_log(
        log.get("id", ""),
        cloudflare_pdf_path=upload_result.get("object_key", ""),
        cloudflare_pdf_url=upload_result.get("public_url", ""),
        uploaded_at=upload_result.get("uploaded_at") or utc_now_iso(),
        status="uploaded",
        error_message="",
    )
    return {
        "ok": True,
        "success": True,
        "menu_id": menu_id,
        "pdf_path": str(local_pdf_path),
        "local_pdf_path": str(local_pdf_path),
        "cloudflare_pdf_path": upload_result.get("object_key", ""),
        "cloudflare_pdf_url": upload_result.get("public_url", ""),
        "pdf_log": updated or log,
        "pdf_log_id": (updated or log).get("id", ""),
        "cloudflare_upload": upload_result,
    }


def export_upload_menu_pdf(menu_id):
    generated = generate_menu_pdf(menu_id)
    if not generated.get("ok"):
        return generated
    uploaded = upload_menu_pdf(menu_id, log_id=generated.get("pdf_log_id", ""))
    return {
        **generated,
        **uploaded,
        "generated": generated,
        "uploaded": uploaded,
        "ok": bool(generated.get("ok") and uploaded.get("ok")),
        "success": bool(generated.get("ok") and uploaded.get("ok")),
        "error": uploaded.get("error", "") if not uploaded.get("ok") else "",
    }
