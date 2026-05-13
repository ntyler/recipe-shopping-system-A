from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.extraction_progress_service import batch_has_success
from PushShoppingList.services.extraction_progress_service import batch_is_finished
from PushShoppingList.services.extraction_progress_service import finish_progress
from PushShoppingList.services.extraction_progress_service import is_cancel_requested
from PushShoppingList.services.extraction_progress_service import is_current_job
from PushShoppingList.services.extraction_progress_service import load_progress
from PushShoppingList.services.extraction_progress_service import mark_url_done
from PushShoppingList.services.extraction_progress_service import mark_url_failed
from PushShoppingList.services.extraction_progress_service import mark_url_message
from PushShoppingList.services.extraction_progress_service import mark_url_running
from PushShoppingList.services.extraction_progress_service import new_job_id
from PushShoppingList.services.extraction_progress_service import request_cancel
from PushShoppingList.services.extraction_progress_service import start_progress
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url
from PushShoppingList.services.recipe_ingredient_service import remove_recipe_and_unused_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_ingredients_for_recipe
from PushShoppingList.services.recipe_url_service import add_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import remove_recipe_url
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_quantity_service import update_recipe_ingredient_quantity
from PushShoppingList.services.recipe_quantity_service import update_recipe_quantity
from PushShoppingList.services.shopping_list_service import add_items

recipe_bp = Blueprint("recipe_bp", __name__)


@recipe_bp.route("/extract_recipe", methods=["POST"])
def extract_recipe_route():
    recipe_urls = request.form.get("recipe_urls", "")

    urls = [
        line.strip()
        for line in recipe_urls.splitlines()
        if line.strip()
    ]

    job_id = new_job_id()
    start_progress(urls, job_id=job_id)

    extracted_any = False

    for index, url in enumerate(urls):
        if is_cancel_requested(job_id):
            break

        mark_url_running(job_id, urls, index)
        result = extract_recipe_from_url(
            url,
            progress_callback=lambda message, summary=None, idx=index: mark_url_message(
                job_id,
                urls,
                idx,
                message,
                summary,
            ),
        )

        if is_cancel_requested(job_id):
            break

        if result.get("ok"):
            ingredients = result.get("ingredients", [])
            add_items(ingredients)
            save_ingredients_for_recipe(url, ingredients)
            add_recipe_urls([url])
            extracted_any = True
            mark_url_done(job_id, urls, index, len(ingredients))
        else:
            mark_url_failed(job_id, urls, index, result.get("error"))

    if extracted_any:
        sort_ingredients()

    finish_progress(job_id, ok=extracted_any)

    return redirect("/")


@recipe_bp.route("/upload_recipe_media", methods=["POST"])
def upload_recipe_media_route():
    uploaded_file = request.files.get("recipe_media")
    wants_json = (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )

    if not uploaded_file or not uploaded_file.filename:
        if wants_json:
            return jsonify({"ok": False, "error": "No file was selected."}), 400

        return redirect("/")

    result = extract_recipe_from_upload(uploaded_file)

    if result.get("ok"):
        recipe_url = result.get("source_url")
        ingredients = result.get("ingredients", [])
        add_items(ingredients)
        save_ingredients_for_recipe(recipe_url, ingredients)
        add_recipe_urls([recipe_url])
        sort_ingredients()

    if wants_json:
        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    return redirect("/")


@recipe_bp.route("/api/extract_recipe", methods=["POST"])
def api_extract_recipe_route():
    data = request.get_json(force=True)

    url = str(data.get("url", "")).strip()
    urls = [
        str(item).strip()
        for item in data.get("urls", [url])
        if str(item).strip()
    ]
    job_id = str(data.get("job_id") or new_job_id())
    index = int(data.get("index", 0))

    if not urls:
        urls = [url]

    if is_cancel_requested(job_id):
        return jsonify({"ok": False, "cancelled": True, "error": "Extraction cancelled."}), 409

    mark_url_running(job_id, urls, index)

    if not is_current_job(job_id):
        return jsonify({"ok": False, "cancelled": True, "error": "Extraction superseded."}), 409

    result = extract_recipe_from_url(
        url,
        progress_callback=lambda message, summary=None: mark_url_message(
            job_id,
            urls,
            index,
            message,
            summary,
        ),
    )

    if is_cancel_requested(job_id) or not is_current_job(job_id):
        return jsonify({"ok": False, "cancelled": True, "error": "Extraction cancelled."}), 409

    if not result.get("ok"):
        progress = mark_url_failed(job_id, urls, index, result.get("error"))
        finish_batch_if_ready(job_id, progress)

        return jsonify(result), 400

    ingredients = result.get("ingredients", [])
    add_items(ingredients)
    save_ingredients_for_recipe(url, ingredients)
    add_recipe_urls([url])
    progress = mark_url_done(job_id, urls, index, len(ingredients))
    finish_batch_if_ready(job_id, progress)

    return jsonify(result)


@recipe_bp.route("/api/start_extract_progress", methods=["POST"])
def api_start_extract_progress_route():
    data = request.get_json(force=True)
    urls = [
        str(item).strip()
        for item in data.get("urls", [])
        if str(item).strip()
    ]
    job_id = str(data.get("job_id") or new_job_id())

    return jsonify(start_progress(urls, job_id=job_id))


@recipe_bp.route("/api/extract_progress", methods=["GET"])
def api_extract_progress_route():
    return jsonify(load_progress())


@recipe_bp.route("/api/cancel_extract", methods=["POST"])
def api_cancel_extract_route():
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or "").strip() or None

    progress = request_cancel(job_id)

    return jsonify(progress)


@recipe_bp.route("/api/recipe_quantity", methods=["POST"])
def api_recipe_quantity_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    quantity = data.get("quantity", 1)
    quantity = normalize_recipe_quantity(quantity)

    return jsonify(update_recipe_quantity(url, quantity))


@recipe_bp.route("/api/recipe_ingredient_quantity", methods=["POST"])
def api_recipe_ingredient_quantity_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    ingredient = str(data.get("ingredient", "") or "").strip()
    quantity = str(data.get("quantity", "") or "").strip()
    unit = str(data.get("unit", "") or "").strip()

    result = update_recipe_ingredient_quantity(url, ingredient, quantity, unit)
    status = 200 if result.get("ok") else 404

    return jsonify(result), status


@recipe_bp.route("/api/recipe_name", methods=["POST"])
def api_recipe_name_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    name = str(data.get("name", "") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    save_recipe_url_name(url, name)

    return jsonify({
        "ok": True,
        "url": url,
        "name": name,
    })


@recipe_bp.route("/remove_recipe", methods=["POST"])
def remove_recipe_route():
    data = request.get_json(silent=True) or {}
    url = request.form.get("url") or data.get("url", "")

    remove_recipe_and_unused_ingredients(url)
    remove_recipe_url(url)

    return redirect("/")


def finish_batch_if_ready(job_id, progress):
    if progress.get("cancel_requested"):
        return

    if not batch_is_finished(progress):
        return

    if batch_has_success(progress):
        sort_ingredients()

    finish_progress(job_id, ok=not any(
        item.get("state") == "failed"
        for item in progress.get("urls", [])
    ))
