import os
from pathlib import Path
from uuid import uuid4

from flask import Blueprint
from flask import jsonify
from flask import request
from werkzeug.utils import secure_filename

from PushShoppingList.services.job_queue_service import cancel_queued_rq_job
from PushShoppingList.services.job_queue_service import enqueue_job
from PushShoppingList.services.job_queue_service import queue_name_for_job
from PushShoppingList.services.job_service import active_limit_for_job
from PushShoppingList.services.job_service import active_limit_wait_message
from PushShoppingList.services.job_service import cancel_job
from PushShoppingList.services.job_service import clear_recent_jobs
from PushShoppingList.services.job_service import create_job
from PushShoppingList.services.job_service import create_retry_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_limit_key
from PushShoppingList.services.job_service import job_for_client
from PushShoppingList.services.job_service import owner_job_count_for_limit_key
from PushShoppingList.services.job_service import queued_limit_status
from PushShoppingList.services.job_service import recent_jobs
from PushShoppingList.services.job_service import retryable_job_type
from PushShoppingList.services.job_service import update_job
from PushShoppingList.services.job_service import user_can_access_job
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import resolve_menu_cleanup_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_cleanup_model_source
from PushShoppingList.services.recipe_extract_service import resolve_menu_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_model_source
from PushShoppingList.services.recipe_extract_service import resolve_vision_model
from PushShoppingList.services.recipe_extract_service import resolve_vision_model_source
from PushShoppingList.services.openai_model_service import model_value_for_env as active_model_value_for_env
from PushShoppingList.services.storage_service import active_guest_session_id
from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import workspace_data_root
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.user_account_service import is_admin_user


job_bp = Blueprint("job_bp", __name__)


def actor_context():
    user = current_user()
    user_id = str((user or {}).get("user_id") or active_user_id() or "").strip()
    guest_session_id = str(active_guest_session_id() or "").strip()
    return {
        "user": user,
        "user_id": user_id,
        "guest_session_id": guest_session_id,
        "is_admin": is_admin_user(user),
    }


def json_payload():
    return request.get_json(silent=True) or {}


def form_or_json_payload():
    if request.is_json:
        return json_payload()

    payload = dict(request.form.items())
    recipe_urls = payload.get("recipe_urls", "")
    if recipe_urls:
        payload["urls"] = [
            line.strip()
            for line in recipe_urls.splitlines()
            if line.strip()
        ]
    return payload


def urls_from_payload(payload, *fallback_keys):
    urls = payload.get("urls")
    if isinstance(urls, str):
        urls = [line.strip() for line in urls.splitlines() if line.strip()]
    if not isinstance(urls, list):
        urls = []

    for key in fallback_keys:
        value = str(payload.get(key) or "").strip()
        if value:
            urls.append(value)

    return [str(url or "").strip() for url in urls if str(url or "").strip()]


def with_model_metadata(payload, model_used="", model_source="", model_env_var=""):
    payload = payload if isinstance(payload, dict) else {}
    return {
        **payload,
        "model_used": str(model_used or "").strip(),
        "model_source": str(model_source or "").strip(),
        "model_env_var": str(model_env_var or "").strip(),
        "model_env_var_used": str(model_env_var or "").strip(),
    }


def active_model_metadata_for_env(env_var, default_model="", default_source=""):
    model, source = active_model_value_for_env(env_var, default_model)
    return with_model_metadata(
        {},
        model_used=model,
        model_source=source or default_source,
        model_env_var=env_var,
    )


def with_active_model_metadata(payload, env_var, default_model="", default_source=""):
    model, source = active_model_value_for_env(env_var, default_model)
    return with_model_metadata(
        payload,
        model_used=model,
        model_source=source or default_source,
        model_env_var=env_var,
    )


def payload_truthy(payload, key, default=False):
    value = (payload if isinstance(payload, dict) else {}).get(key, default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def create_and_enqueue(job_type, payload, total_items=0):
    actor = actor_context()
    queue_name = queue_name_for_job(job_type, payload)
    queued_status = queued_limit_status(
        user_id=actor["user_id"],
        guest_session_id=actor["guest_session_id"],
        job_type=job_type,
        input_payload=payload,
    )
    if not queued_status.get("ok"):
        return jsonify({
            "ok": False,
            "error": queued_status.get("message") or "Too many queued jobs for this import type.",
            "limit": queued_status.get("limit"),
            "queued_count": queued_status.get("queued_count"),
            "job_type": job_type,
            "queue_name": queue_name,
        }), 429

    limit_key = job_limit_key(job_type, payload)
    active_limit = active_limit_for_job(job_type, payload)
    active_count = owner_job_count_for_limit_key(
        user_id=actor["user_id"],
        guest_session_id=actor["guest_session_id"],
        limit_key=limit_key,
        statuses=["running"],
    ) if active_limit else 0

    job = create_job(
        job_type,
        input_payload=payload,
        user_id=actor["user_id"],
        guest_session_id=actor["guest_session_id"],
        total_items=total_items,
        queue_name=queue_name,
    )
    if active_limit and active_count >= active_limit:
        job = update_job(job["id"], current_step=active_limit_wait_message(limit_key), queue_name=queue_name) or job

    queue_result = enqueue_job(job["id"], queue_name_override=queue_name)
    job = get_job(job["id"]) or job

    response = {
        "ok": bool(queue_result.get("ok")),
        "job_id": job["id"],
        "job": job_for_client(job),
        "queue": {
            key: value
            for key, value in queue_result.items()
            if key not in {"details"}
        },
        "message": job.get("current_step") if active_limit and active_count >= active_limit else "",
    }
    status = 202 if queue_result.get("ok") else 503
    return jsonify(response), status


def job_access_or_404(job_id):
    actor = actor_context()
    job = get_job(job_id)
    if not job:
        return None, (jsonify({"ok": False, "error": "Job not found."}), 404)
    if not user_can_access_job(
        job,
        user_id=actor["user_id"],
        guest_session_id=actor["guest_session_id"],
        is_admin=actor["is_admin"],
    ):
        return None, (jsonify({"ok": False, "error": "Job not found."}), 404)
    return job, None


@job_bp.route("/api/jobs/menu-import", methods=["POST"])
def start_menu_import_job_route():
    payload = form_or_json_payload()
    urls = urls_from_payload(payload, "menu_url", "url", "recipe_url")
    if not urls:
        return jsonify({"ok": False, "error": "At least one menu URL is required."}), 400

    payload = {
        **payload,
        "urls": urls,
        "extraction_mode": "menu_extract",
    }
    payload = with_model_metadata(
        payload,
        model_used=resolve_menu_cleanup_model(),
        model_source=resolve_menu_cleanup_model_source(),
        model_env_var="OPENAI_MENU_CLEANUP_MODEL",
    )
    return create_and_enqueue("menu-import", payload, total_items=len(urls))


@job_bp.route("/api/jobs/menu-generate-recipes", methods=["POST"])
def start_menu_generate_recipes_job_route():
    payload = json_payload()
    urls = urls_from_payload(payload, "recipe_url", "url", "source_url")
    recipe_urls = payload.get("recipe_urls")
    if isinstance(recipe_urls, str):
        urls.extend(line.strip() for line in recipe_urls.splitlines() if line.strip())
    elif isinstance(recipe_urls, list):
        urls.extend(str(url or "").strip() for url in recipe_urls if str(url or "").strip())
    urls = list(dict.fromkeys([url for url in urls if url]))
    if not urls:
        return jsonify({"ok": False, "error": "At least one menu item stub URL is required."}), 400

    payload = {
        **payload,
        "recipe_urls": urls,
        "force_reprocess": payload_truthy(payload, "force_reprocess", False),
    }
    payload = with_model_metadata(
        payload,
        model_used=resolve_menu_model(),
        model_source=resolve_menu_model_source(),
        model_env_var="OPENAI_MENU_MODEL",
    )
    return create_and_enqueue("menu-generate-recipes", payload, total_items=len(urls))


@job_bp.route("/api/jobs/menu-deferred-heavy-tasks", methods=["POST"])
def start_menu_deferred_heavy_tasks_job_route():
    payload = json_payload()
    urls = urls_from_payload(payload, "recipe_url", "url", "source_url")
    recipe_urls = payload.get("recipe_urls")
    if isinstance(recipe_urls, str):
        urls.extend(line.strip() for line in recipe_urls.splitlines() if line.strip())
    elif isinstance(recipe_urls, list):
        urls.extend(str(url or "").strip() for url in recipe_urls if str(url or "").strip())
    urls = list(dict.fromkeys([url for url in urls if url]))
    if not urls:
        return jsonify({"ok": False, "error": "At least one recipe URL is required."}), 400

    payload = {
        **payload,
        "recipe_urls": urls,
        "force_reprocess": payload_truthy(payload, "force_reprocess", False),
    }
    payload = with_active_model_metadata(
        payload,
        "OPENAI_NUTRITION_MODEL",
        MODEL,
        "fallback:OPENAI_RECIPE_MODEL",
    )
    return create_and_enqueue("menu-deferred-heavy-tasks", payload, total_items=len(urls))


@job_bp.route("/api/jobs/cookbook-infer-missing-details", methods=["POST"])
def start_cookbook_infer_missing_details_job_route():
    from PushShoppingList.services.cookbook_item_inference_service import COOKBOOK_ITEM_MODEL_ENV_VAR
    from PushShoppingList.services.cookbook_item_inference_service import recipe_context_from_cookbook
    from PushShoppingList.services.cookbook_item_inference_service import resolve_cookbook_item_model

    payload = json_payload()
    cookbook_id = str(payload.get("cookbook_id") or "").strip()
    if not cookbook_id:
        return jsonify({"ok": False, "error": "Cookbook is required."}), 400

    try:
        cookbook = recipe_context_from_cookbook(cookbook_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc) or "Cookbook was not found."}), 404

    recipe_names = {}
    recipe_urls = []
    for recipe in cookbook.get("recipes", []):
        if not isinstance(recipe, dict):
            continue
        recipe_url = str(recipe.get("url") or "").strip()
        if not recipe_url:
            continue
        recipe_urls.append(recipe_url)
        recipe_name = str(
            recipe.get("name")
            or recipe.get("display_name")
            or recipe.get("recipe_title")
            or recipe.get("menu_item_name")
            or ""
        ).strip()
        if recipe_name:
            recipe_names[recipe_url] = recipe_name
    recipe_urls = list(dict.fromkeys(recipe_urls))
    model, model_source = resolve_cookbook_item_model()
    payload = with_model_metadata(
        {
            **payload,
            "cookbook_id": cookbook_id,
            "cookbook_name": str(payload.get("cookbook_name") or cookbook.get("name") or "").strip(),
            "recipe_urls": recipe_urls,
            "recipe_names": recipe_names,
            "overwrite_ai_fields": payload_truthy(payload, "overwrite_ai_fields", False),
            "preview_only": payload_truthy(payload, "preview_only", False),
        },
        model,
        model_source,
        COOKBOOK_ITEM_MODEL_ENV_VAR,
    )
    return create_and_enqueue("cookbook-infer-missing-details", payload, total_items=len(recipe_urls))


@job_bp.route("/api/jobs/recipe-import", methods=["POST"])
def start_recipe_import_job_route():
    payload = form_or_json_payload()
    urls = urls_from_payload(payload, "url", "recipe_url")
    if not urls:
        return jsonify({"ok": False, "error": "At least one recipe URL is required."}), 400

    payload = {
        **payload,
        "urls": urls,
        "extraction_mode": "recipe",
    }
    payload = with_active_model_metadata(
        payload,
        "OPENAI_RECIPE_MODEL",
        MODEL,
        "recipe",
    )
    return create_and_enqueue("recipe-import", payload, total_items=len(urls))


def save_job_upload(uploaded_file):
    filename = secure_filename(uploaded_file.filename or "upload")
    suffix = Path(filename).suffix
    staging_dir = workspace_data_root() / "job_uploads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / f"{uuid4().hex}_{filename or ('upload' + suffix)}"
    uploaded_file.save(path)
    return path


@job_bp.route("/api/jobs/doc-photo-import", methods=["POST"])
def start_doc_photo_import_job_route():
    uploaded_file = (
        request.files.get("recipe_media")
        or request.files.get("menu_media")
        or request.files.get("file")
        or request.files.get("upload")
    )
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"ok": False, "error": "No file was selected."}), 400

    payload = form_or_json_payload()
    source_path = save_job_upload(uploaded_file)
    import_mode = str(
        payload.get("import_mode")
        or payload.get("extraction_mode")
        or payload.get("mode")
        or "recipe"
    ).strip().lower()
    payload = {
        **payload,
        "source_path": str(source_path),
        "filename": uploaded_file.filename,
        "content_type": uploaded_file.content_type or "",
        "import_mode": import_mode,
        "extraction_mode": import_mode,
        "manual_description": payload.get("photo_description") or payload.get("recipe_description") or "",
    }
    upload_mode = str(payload.get("upload_mode") or "auto").strip().lower()
    if import_mode in {"menu", "menu_extract", "menu-extract"}:
        payload = with_model_metadata(payload, resolve_menu_model(), resolve_menu_model_source(), "OPENAI_MENU_MODEL")
    elif upload_mode == "image":
        payload = with_model_metadata(payload, resolve_vision_model(), resolve_vision_model_source(), "OPENAI_VISION_MODEL")
    else:
        payload = with_active_model_metadata(payload, "OPENAI_RECIPE_MODEL", MODEL, "recipe")
    return create_and_enqueue("doc-photo-import", payload, total_items=1)


@job_bp.route("/api/jobs/estimate-per-serving", methods=["POST"])
def start_estimate_per_serving_job_route():
    payload = json_payload()
    if not payload.get("recipe") and not (payload.get("url") or payload.get("recipe_url") or payload.get("source_url")):
        return jsonify({"ok": False, "error": "Recipe payload or URL is required."}), 400
    payload = with_active_model_metadata(
        payload,
        "OPENAI_NUTRITION_MODEL",
        MODEL,
        "fallback:OPENAI_RECIPE_MODEL",
    )
    return create_and_enqueue("estimate-per-serving", payload, total_items=1)


@job_bp.route("/api/jobs/create-recipe-pdf", methods=["POST"])
def start_create_recipe_pdf_job_route():
    payload = json_payload()
    if not (payload.get("url") or payload.get("recipe_url") or payload.get("source_url")):
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400
    return create_and_enqueue("create-recipe-pdf", payload, total_items=1)


@job_bp.route("/api/jobs/upload-source-pdf", methods=["POST"])
def start_upload_source_pdf_job_route():
    payload = json_payload()
    if not (payload.get("url") or payload.get("recipe_url") or payload.get("source_url")):
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400
    payload = {
        **payload,
        "pdf_kind": "webpage_backup",
    }
    return create_and_enqueue("upload-source-pdf", payload, total_items=1)


@job_bp.route("/api/jobs/upload-generated-pdf", methods=["POST"])
def start_upload_generated_pdf_job_route():
    payload = json_payload()
    if not (payload.get("url") or payload.get("recipe_url") or payload.get("source_url")):
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400
    payload = {
        **payload,
        "pdf_kind": "generated_recipe",
    }
    return create_and_enqueue("upload-generated-pdf", payload, total_items=1)


@job_bp.route("/api/jobs/product-matching", methods=["POST"])
def start_product_matching_job_route():
    payload = json_payload()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    payload = with_active_model_metadata(
        payload,
        "OPENAI_PRODUCT_ANALYSIS_MODEL",
        MODEL,
        "fallback:OPENAI_RECIPE_MODEL",
    )
    return create_and_enqueue("product-matching", payload, total_items=len(items))


@job_bp.route("/api/jobs/recipe-category-decision", methods=["POST"])
def start_recipe_category_decision_job_route():
    payload = json_payload()
    if not payload:
        return jsonify({"ok": False, "error": "Recipe payload is required."}), 400
    payload = with_active_model_metadata(payload, "OPENAI_RECIPE_CATEGORY_MODEL", MODEL, "fallback:OPENAI_RECIPE_MODEL")
    return create_and_enqueue("recipe-category-decision", payload, total_items=1)


@job_bp.route("/api/jobs/<job_id>", methods=["GET"])
def job_status_route(job_id):
    job, error_response = job_access_or_404(job_id)
    if error_response:
        return error_response
    return jsonify({"ok": True, "job": job_for_client(job, include_input=actor_context()["is_admin"])})


@job_bp.route("/api/jobs/recent", methods=["GET", "DELETE"])
def recent_jobs_route():
    actor = actor_context()
    include_all = actor["is_admin"] and request.args.get("scope") == "all"
    try:
        limit = int(request.args.get("limit", "25"))
    except ValueError:
        limit = 25

    deleted_count = 0
    if request.method == "DELETE":
        deleted_count = clear_recent_jobs(
            user_id=actor["user_id"],
            guest_session_id=actor["guest_session_id"],
            include_all=include_all,
        )

    jobs = recent_jobs(
        user_id=actor["user_id"],
        guest_session_id=actor["guest_session_id"],
        include_all=include_all,
        limit=limit,
    )
    return jsonify({
        "ok": True,
        "jobs": [job_for_client(job, include_input=include_all) for job in jobs],
        "scope": "all" if include_all else "mine",
        "is_admin": actor["is_admin"],
        "deleted_count": deleted_count,
    })


@job_bp.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job_route(job_id):
    job, error_response = job_access_or_404(job_id)
    if error_response:
        return error_response

    cancel_queued_rq_job(job.get("rq_job_id"))
    job = cancel_job(job_id)
    return jsonify({"ok": True, "job": job_for_client(job)})


@job_bp.route("/api/jobs/<job_id>/retry", methods=["POST"])
def retry_job_route(job_id):
    job, error_response = job_access_or_404(job_id)
    if error_response:
        return error_response

    if not retryable_job_type(job.get("job_type")):
        return jsonify({
            "ok": False,
            "error": "This job type cannot be retried safely. Start it again from the original workflow.",
        }), 400

    retry = create_retry_job(job)
    if not retry:
        return jsonify({"ok": False, "error": "Unable to create retry job."}), 400

    queue_result = enqueue_job(retry["id"])
    retry = get_job(retry["id"]) or retry
    status = 202 if queue_result.get("ok") else 503
    return jsonify({
        "ok": bool(queue_result.get("ok")),
        "job_id": retry["id"],
        "job": job_for_client(retry),
        "queue": {
            key: value
            for key, value in queue_result.items()
            if key not in {"details"}
        },
    }), status
