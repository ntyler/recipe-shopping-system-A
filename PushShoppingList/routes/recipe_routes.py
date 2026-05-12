from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.extraction_progress_service import finish_progress
from PushShoppingList.services.extraction_progress_service import load_progress
from PushShoppingList.services.extraction_progress_service import mark_url_done
from PushShoppingList.services.extraction_progress_service import mark_url_failed
from PushShoppingList.services.extraction_progress_service import mark_url_running
from PushShoppingList.services.extraction_progress_service import new_job_id
from PushShoppingList.services.extraction_progress_service import start_progress
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url
from PushShoppingList.services.recipe_url_service import add_recipe_urls
from PushShoppingList.services.recipe_url_service import remove_recipe_url
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

    add_recipe_urls(urls)
    job_id = new_job_id()
    start_progress(urls, job_id=job_id)

    extracted_any = False

    for index, url in enumerate(urls):
        mark_url_running(job_id, urls, index)
        result = extract_recipe_from_url(url)

        if result.get("ok"):
            add_items(result.get("ingredients", []))
            extracted_any = True
            mark_url_done(job_id, urls, index, len(result.get("ingredients", [])))
        else:
            mark_url_failed(job_id, urls, index, result.get("error"))

    if extracted_any:
        sort_ingredients()

    finish_progress(job_id, ok=extracted_any)

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

    add_recipe_urls([url])
    mark_url_running(job_id, urls, index)

    result = extract_recipe_from_url(url)

    if not result.get("ok"):
        mark_url_failed(job_id, urls, index, result.get("error"))

        if index >= len(urls) - 1:
            finish_progress(job_id, ok=False)

        return jsonify(result), 400

    add_items(result.get("ingredients", []))
    mark_url_done(job_id, urls, index, len(result.get("ingredients", [])))
    sort_ingredients()

    if index >= len(urls) - 1:
        finish_progress(job_id, ok=True)

    return jsonify(result)


@recipe_bp.route("/api/extract_progress", methods=["GET"])
def api_extract_progress_route():
    return jsonify(load_progress())


@recipe_bp.route("/remove_recipe", methods=["POST"])
def remove_recipe_route():
    data = request.get_json(silent=True) or {}
    url = request.form.get("url") or data.get("url", "")

    remove_recipe_url(url)

    return redirect("/")
