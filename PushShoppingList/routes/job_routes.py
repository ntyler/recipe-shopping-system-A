from pathlib import Path
from uuid import uuid4

from flask import Blueprint
from flask import jsonify
from flask import request
from werkzeug.utils import secure_filename

from PushShoppingList.services.job_queue_service import cancel_queued_rq_job
from PushShoppingList.services.job_queue_service import enqueue_job
from PushShoppingList.services.job_service import cancel_job
from PushShoppingList.services.job_service import create_job
from PushShoppingList.services.job_service import create_retry_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_for_client
from PushShoppingList.services.job_service import recent_jobs
from PushShoppingList.services.job_service import retryable_job_type
from PushShoppingList.services.job_service import update_job
from PushShoppingList.services.job_service import user_can_access_job
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


def create_and_enqueue(job_type, payload, total_items=0):
    actor = actor_context()
    job = create_job(
        job_type,
        input_payload=payload,
        user_id=actor["user_id"],
        guest_session_id=actor["guest_session_id"],
        total_items=total_items,
    )
    queue_result = enqueue_job(job["id"])
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
    return create_and_enqueue("menu-import", payload, total_items=len(urls))


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
    return create_and_enqueue("doc-photo-import", payload, total_items=1)


@job_bp.route("/api/jobs/estimate-per-serving", methods=["POST"])
def start_estimate_per_serving_job_route():
    payload = json_payload()
    if not payload.get("recipe") and not (payload.get("url") or payload.get("recipe_url") or payload.get("source_url")):
        return jsonify({"ok": False, "error": "Recipe payload or URL is required."}), 400
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
    return create_and_enqueue("product-matching", payload, total_items=len(items))


@job_bp.route("/api/jobs/recipe-category-decision", methods=["POST"])
def start_recipe_category_decision_job_route():
    payload = json_payload()
    if not payload:
        return jsonify({"ok": False, "error": "Recipe payload is required."}), 400
    return create_and_enqueue("recipe-category-decision", payload, total_items=1)


@job_bp.route("/api/jobs/<job_id>", methods=["GET"])
def job_status_route(job_id):
    job, error_response = job_access_or_404(job_id)
    if error_response:
        return error_response
    return jsonify({"ok": True, "job": job_for_client(job, include_input=actor_context()["is_admin"])})


@job_bp.route("/api/jobs/recent", methods=["GET"])
def recent_jobs_route():
    actor = actor_context()
    include_all = actor["is_admin"] and request.args.get("scope") == "all"
    try:
        limit = int(request.args.get("limit", "25"))
    except ValueError:
        limit = 25

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
