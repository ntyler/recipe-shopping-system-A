import os
import re
import time
from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from pathlib import Path

from werkzeug.datastructures import FileStorage

from PushShoppingList.services.job_runtime_context import job_context
from PushShoppingList.services.job_service import append_job_warning
from PushShoppingList.services.job_service import complete_job
from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_cancelled
from PushShoppingList.services.job_service import menu_item_label_from_url
from PushShoppingList.services.job_service import update_job_progress
from PushShoppingList.services.file_lock_service import workspace_write_lock
from PushShoppingList.services.openai_model_service import model_value_for_env as active_model_value_for_env


class JobCancelled(Exception):
    pass


PROGRESS_COUNT_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")


def run_job_task(job_id):
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "Job not found."}

    handlers = {
        "menu-import": run_menu_import_job,
        "menu-generate-recipes": run_menu_generate_recipes_job,
        "menu-deferred-heavy-tasks": run_menu_deferred_enrichment_job,
        "cookbook-infer-missing-details": run_cookbook_infer_missing_details_job,
        "recipe-import": run_recipe_import_job,
        "doc-photo-import": run_doc_photo_import_job,
        "estimate-per-serving": run_estimate_per_serving_job,
        "create-recipe-pdf": run_create_recipe_pdf_job,
        "product-matching": run_product_matching_job,
        "recipe-category-decision": run_recipe_category_decision_job,
        "upload-source-pdf": run_upload_pdf_job,
        "upload-generated-pdf": run_upload_pdf_job,
    }
    handler = handlers.get(job.get("job_type"))
    if not handler:
        return fail_job(job_id, f"Unsupported job type: {job.get('job_type')}")

    try:
        result = handler(job_id, job.get("input_payload") or {})
        if job_cancelled(job_id):
            return get_job(job_id)
        return result
    except JobCancelled:
        from PushShoppingList.services.job_service import cancel_job

        return cancel_job(job_id, "Cancelled")
    except Exception as exc:
        print(f"[job_tasks] job_id={job_id} error={exc}")
        return fail_job(job_id, str(exc) or "Job failed.")


def ensure_not_cancelled(job_id):
    if job_cancelled(job_id):
        raise JobCancelled()


def bounded_percent(index, total, start=0, end=100):
    total = max(1, int(total or 1))
    index = max(0, min(total, int(index or 0)))
    return int(start + ((end - start) * (index / total)))


def menu_item_batch_inference_worker_count(batch_total=None):
    try:
        configured = int(os.getenv("MENU_ITEM_BATCH_INFERENCE_WORKERS") or "8")
    except (TypeError, ValueError):
        configured = 8
    configured = max(1, min(12, configured))
    if batch_total:
        return max(1, min(configured, int(batch_total)))
    return configured


def menu_followup_worker_count(total=None, env_var="", default=4):
    try:
        configured = int(os.getenv(env_var) or str(default))
    except (TypeError, ValueError):
        configured = int(default or 1)
    configured = max(1, min(8, configured))
    if total:
        return max(1, min(configured, int(total)))
    return configured


def menu_nutrition_worker_count(total=None):
    return menu_followup_worker_count(total, "MENU_NUTRITION_WORKERS", default=6)


def menu_category_worker_count(total=None):
    return menu_followup_worker_count(total, "MENU_CATEGORY_WORKERS", default=6)


def menu_save_progress_update_every():
    try:
        configured = int(os.getenv("MENU_SAVE_PROGRESS_EVERY") or "10")
    except (TypeError, ValueError):
        configured = 10
    return max(1, min(50, configured))


def menu_followup_progress_update_every():
    try:
        configured = int(os.getenv("MENU_FOLLOWUP_PROGRESS_EVERY") or os.getenv("MENU_SAVE_PROGRESS_EVERY") or "10")
    except (TypeError, ValueError):
        configured = 10
    return max(1, min(50, configured))


def copy_current_request_context_if_available(callback):
    try:
        from flask import copy_current_request_context
        from flask import has_request_context

        if has_request_context():
            return copy_current_request_context(callback)
    except Exception:
        pass
    return callback


def model_metadata(model_used="", model_source="", model_env_var=""):
    return {
        "model_used": str(model_used or "").strip(),
        "model_source": str(model_source or "").strip(),
        "model_env_var": str(model_env_var or "").strip(),
        "model_env_var_used": str(model_env_var or "").strip(),
    }


def active_model_metadata(env_var, default_model="", default_source=""):
    model, source = active_model_value_for_env(env_var, default_model)
    return model_metadata(model, source or default_source, env_var)


def job_start_metadata(job):
    from PushShoppingList.services.recipe_extract_service import MODEL
    from PushShoppingList.services.recipe_extract_service import OPENAI_MENU_RECIPE_MODEL_ENV_VAR
    from PushShoppingList.services.recipe_extract_service import menu_item_recipe_model_resolution
    from PushShoppingList.services.recipe_extract_service import resolve_menu_cleanup_model
    from PushShoppingList.services.recipe_extract_service import resolve_menu_cleanup_model_source
    from PushShoppingList.services.recipe_extract_service import resolve_menu_model
    from PushShoppingList.services.recipe_extract_service import resolve_menu_model_source
    from PushShoppingList.services.recipe_extract_service import resolve_vision_model
    from PushShoppingList.services.recipe_extract_service import resolve_vision_model_source

    job = job if isinstance(job, dict) else {}
    payload = job.get("input_payload") if isinstance(job.get("input_payload"), dict) else {}
    job_type = str(job.get("job_type") or "").strip().lower()
    mode = str(payload.get("import_mode") or payload.get("extraction_mode") or payload.get("mode") or "").strip().lower()
    upload_mode = str(payload.get("upload_mode") or "").strip().lower()
    content_type = str(payload.get("content_type") or "").strip().lower()
    filename = str(payload.get("filename") or "").strip().lower()
    is_image_upload = bool(
        upload_mode in {"image", "vision", "manual_description"}
        or content_type.startswith("image/")
        or filename.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"))
    )

    if job_type == "menu-generate-recipes":
        model_resolution = menu_item_recipe_model_resolution()
        return model_metadata(
            model_resolution.model,
            model_resolution.source,
            OPENAI_MENU_RECIPE_MODEL_ENV_VAR,
        )

    if job_type == "menu-deferred-heavy-tasks":
        return active_model_metadata(
            "OPENAI_NUTRITION_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        )

    if job_type == "cookbook-infer-missing-details":
        from PushShoppingList.services.cookbook_item_inference_service import COOKBOOK_ITEM_MODEL_ENV_VAR
        from PushShoppingList.services.cookbook_item_inference_service import resolve_cookbook_item_model

        model, source = resolve_cookbook_item_model()
        return model_metadata(model, source, COOKBOOK_ITEM_MODEL_ENV_VAR)

    if job_type == "menu-import":
        return model_metadata(resolve_menu_cleanup_model(), resolve_menu_cleanup_model_source(), "OPENAI_MENU_CLEANUP_MODEL")

    if job_type == "doc-photo-import" and mode in {"menu", "menu_extract", "menu-extract"}:
        return model_metadata(resolve_menu_model(), resolve_menu_model_source(), "OPENAI_MENU_MODEL")

    if job_type == "doc-photo-import" and is_image_upload:
        return model_metadata(resolve_vision_model(), resolve_vision_model_source(), "OPENAI_VISION_MODEL")

    if job_type == "estimate-per-serving":
        return active_model_metadata(
            "OPENAI_NUTRITION_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        )

    if job_type == "product-matching":
        return active_model_metadata(
            "OPENAI_PRODUCT_ANALYSIS_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        )

    if job_type == "recipe-category-decision":
        return active_model_metadata(
            "OPENAI_RECIPE_CATEGORY_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        )

    if job_type == "recipe-import" or job_type == "doc-photo-import":
        return active_model_metadata("OPENAI_RECIPE_MODEL", MODEL, "recipe")

    return model_metadata("", "", "")


def stored_job_model_metadata(job_id, fallback=None):
    fallback = fallback if isinstance(fallback, dict) else {}
    job = get_job(job_id) or {}
    model_used = str(job.get("model_used") or "").strip()
    model_source = str(job.get("model_source") or "").strip()
    model_env_var = str(job.get("model_env_var_used") or "").strip()
    if model_used or model_env_var:
        return model_metadata(model_used, model_source, model_env_var)
    return {
        **model_metadata(
            fallback.get("model_used") or fallback.get("model") or "",
            fallback.get("model_source") or "",
            fallback.get("model_env_var_used") or fallback.get("model_env_var") or "",
        ),
    }


def progress_counts(*values):
    for value in values:
        match = PROGRESS_COUNT_RE.search(str(value or ""))
        if not match:
            continue
        completed = int(match.group(1))
        total = int(match.group(2))
        if total > 0:
            return completed, total
    return None, None


def recipe_links(urls):
    return [
        {
            "label": str(url),
            "url": f"/recipe/edit?url={url}",
            "recipe_url": str(url),
        }
        for url in urls
        if str(url or "").strip()
    ]


def selected_cookbook_from_payload(payload):
    from PushShoppingList.routes.recipe_routes import selected_import_cookbook

    return selected_import_cookbook(
        payload.get("cookbook_id", ""),
        payload.get("cookbook_name", ""),
    )


def payload_bool(payload, key, default=False):
    value = (payload if isinstance(payload, dict) else {}).get(key, default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def env_bool(name, default=False):
    raw_value = os.getenv(str(name or ""), None)
    if raw_value is None:
        return bool(default)
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default=0, minimum=None, maximum=None):
    try:
        value = int(os.getenv(str(name or "")) or int(default or 0))
    except (TypeError, ValueError):
        value = int(default or 0)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def import_menu_url_auto_enrich_enabled(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    for key in ("auto_generate_recipes", "auto_enrich", "run_background_enrichment"):
        if key in payload:
            return payload_bool(payload, key, False)
    return env_bool("IMPORT_MENU_URL_AUTO_ENRICH", False)


def import_menu_url_create_source_pdf_enabled(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    for key in ("create_source_pdf", "create_menu_source_pdf", "run_source_pdf"):
        if key in payload:
            return payload_bool(payload, key, False)
    return env_bool("IMPORT_MENU_URL_CREATE_SOURCE_PDF", False)


def import_menu_url_target_seconds():
    return env_int("IMPORT_MENU_URL_TARGET_SECONDS", 60, minimum=1, maximum=3600)


def import_menu_url_elapsed_seconds(start_time):
    return max(0.0, time.perf_counter() - float(start_time or time.perf_counter()))


def format_import_menu_url_elapsed(seconds):
    seconds = max(0.0, float(seconds or 0))
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining}s"


def log_import_menu_url_stage(stage, **fields):
    parts = [f"[Import Menu URL] stage={stage}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    print(" ".join(parts))


def menu_enrichment_mode(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    value = str(
        payload.get("menu_enrichment_mode")
        or payload.get("enrichment_mode")
        or os.getenv("MENU_ENRICHMENT_MODE")
        or "fast"
    ).strip().lower()
    return "full" if value == "full" else "fast"


def menu_recipe_batch_size(mode="fast"):
    mode = "full" if str(mode or "").strip().lower() == "full" else "fast"
    env_name = "MENU_RECIPE_FULL_BATCH_SIZE" if mode == "full" else "MENU_RECIPE_FAST_BATCH_SIZE"
    default = 8 if mode == "full" else 32
    return env_int(env_name, default, minimum=1, maximum=50)


def menu_recipe_batch_target_chars(mode="fast"):
    mode = "full" if str(mode or "").strip().lower() == "full" else "fast"
    env_name = "MENU_RECIPE_FULL_BATCH_TARGET_CHARS" if mode == "full" else "MENU_RECIPE_FAST_BATCH_TARGET_CHARS"
    default = 12000 if mode == "full" else 48000
    return env_int(env_name, default, minimum=3000, maximum=100000)


def menu_recipe_fast_target_seconds():
    return env_int("MENU_RECIPE_FAST_TARGET_SECONDS", 120, minimum=1, maximum=7200)


def menu_recipe_failed_item_fallback_enabled(mode="fast"):
    mode = "full" if str(mode or "").strip().lower() == "full" else "fast"
    if mode == "full":
        return env_bool("MENU_RECIPE_FULL_USE_FAILED_ITEM_FALLBACK", True)
    return env_bool("MENU_RECIPE_FAST_USE_FAILED_ITEM_FALLBACK", False)


def log_menu_enrichment_stage(stage, **fields):
    parts = ["[Menu Enrichment]"]
    job_id = fields.pop("job_id", "")
    if job_id:
        parts.append(f"job_id={job_id}")
    parts.append(f"stage={stage}")
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    print(" ".join(parts))


def menu_inline_enrichment_max_items():
    return env_int("MENU_INLINE_ENRICHMENT_MAX_ITEMS", 25, minimum=0, maximum=10000)


def menu_deferred_enrichment_enabled(payload, total):
    payload = payload if isinstance(payload, dict) else {}
    if not payload_bool(payload, "run_deferred_heavy_tasks", True):
        return False
    if payload_bool(payload, "inline_enrichment", False):
        return False
    if "defer_enrichment" in payload:
        return payload_bool(payload, "defer_enrichment", True)
    if os.getenv("MENU_DEFER_ENRICHMENT", "").strip():
        return env_bool("MENU_DEFER_ENRICHMENT", False)
    return int(total or 0) > menu_inline_enrichment_max_items()


def menu_generated_pdfs_enabled(payload, total=None):
    payload = payload if isinstance(payload, dict) else {}
    for key in ("run_generated_pdfs", "generate_recipe_pdfs", "run_recipe_pdfs"):
        if key in payload:
            return payload_bool(payload, key, False)
    return env_bool("MENU_DEFERRED_GENERATED_PDFS", False)


def enqueue_followup_job(job_type, payload, total_items=0):
    from PushShoppingList.services.job_queue_service import enqueue_job
    from PushShoppingList.services.job_queue_service import queue_name_for_job
    from PushShoppingList.services.job_service import active_limit_for_job
    from PushShoppingList.services.job_service import active_limit_wait_message
    from PushShoppingList.services.job_service import create_job
    from PushShoppingList.services.job_service import job_limit_key
    from PushShoppingList.services.job_service import owner_job_count_for_limit_key
    from PushShoppingList.services.job_service import queued_limit_status
    from PushShoppingList.services.job_service import update_job
    from PushShoppingList.services.storage_service import active_guest_session_id
    from PushShoppingList.services.storage_service import active_user_id

    payload = payload if isinstance(payload, dict) else {}
    user_id = active_user_id()
    guest_session_id = active_guest_session_id()
    queue_name = queue_name_for_job(job_type, payload)
    queued_status = queued_limit_status(
        user_id=user_id,
        guest_session_id=guest_session_id,
        job_type=job_type,
        input_payload=payload,
    )
    if not queued_status.get("ok"):
        return {
            "queued": False,
            "error": queued_status.get("message") or "Too many queued jobs.",
            "queue_name": queue_name,
        }

    limit_key = job_limit_key(job_type, payload)
    active_limit = active_limit_for_job(job_type, payload)
    active_count = owner_job_count_for_limit_key(
        user_id=user_id,
        guest_session_id=guest_session_id,
        limit_key=limit_key,
        statuses=["running"],
    ) if active_limit else 0

    job = create_job(
        job_type,
        input_payload=payload,
        user_id=user_id,
        guest_session_id=guest_session_id,
        total_items=total_items,
        queue_name=queue_name,
    )
    if active_limit and active_count >= active_limit:
        job = update_job(job["id"], current_step=active_limit_wait_message(limit_key), queue_name=queue_name) or job

    queue_result = enqueue_job(job["id"], queue_name_override=queue_name)
    return {
        "queued": bool(queue_result.get("ok")),
        "job_id": job.get("id", ""),
        "queue": {key: value for key, value in queue_result.items() if key != "details"},
        "error": "" if queue_result.get("ok") else queue_result.get("error") or "Unable to queue follow-up job.",
    }


def run_menu_import_job(job_id, payload):
    payload = payload if isinstance(payload, dict) else {}
    payload = {
        **payload,
        "extraction_mode": "menu_extract",
        "auto_generate_recipes": import_menu_url_auto_enrich_enabled(payload),
        "create_source_pdf": import_menu_url_create_source_pdf_enabled(payload),
    }
    return run_import_urls_job(job_id, payload, menu_extract=True)


def run_recipe_import_job(job_id, payload):
    return run_import_urls_job(job_id, payload if isinstance(payload, dict) else {}, menu_extract=False)


def run_menu_generate_recipes_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import add_items
    from PushShoppingList.routes.recipe_routes import apply_imported_recipe_category_routine
    from PushShoppingList.routes.recipe_routes import ensure_menu_recipe_serving_basis_estimate
    from PushShoppingList.routes.recipe_routes import import_recipe_title
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import record_recipe_import_activity
    from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
    from PushShoppingList.services.recipe_ingredient_service import save_ingredients_for_recipes
    from PushShoppingList.services.recipe_extract_service import OPENAI_MENU_RECIPE_MODEL_ENV_VAR
    from PushShoppingList.services.recipe_extract_service import build_menu_batch_inference_result
    from PushShoppingList.services.recipe_extract_service import menu_batch_entry_item_name
    from PushShoppingList.services.recipe_extract_service import infer_menu_item_recipe_batch
    from PushShoppingList.services.recipe_extract_service import menu_item_recipe_model_resolution
    from PushShoppingList.services.recipe_extract_service import menu_batch_item_from_stub
    from PushShoppingList.services.recipe_extract_service import menu_inference_batches
    from PushShoppingList.services.recipe_extract_service import menu_item_name_is_blank_divider
    from PushShoppingList.services.recipe_extract_service import mark_menu_recipe_import_failure
    from PushShoppingList.services.recipe_extract_service import save_menu_batch_inference_results
    from PushShoppingList.services.recipe_url_service import add_recipe_urls
    from PushShoppingList.services.recipe_url_service import save_recipe_url_names
    from PushShoppingList.services.storage_service import active_user_id
    from PushShoppingList.services.cookbook_service import cookbook_recipe_assignment_for_url

    payload = payload if isinstance(payload, dict) else {}
    job_started_at = time.perf_counter()
    enrichment_mode = menu_enrichment_mode(payload)
    fast_mode = enrichment_mode == "fast"
    force_reprocess = payload_bool(payload, "force_reprocess", False)
    run_heavy_tasks = (not fast_mode) and payload_bool(payload, "run_deferred_heavy_tasks", True)
    recipe_batch_size = menu_recipe_batch_size(enrichment_mode)
    recipe_batch_target_chars = menu_recipe_batch_target_chars(enrichment_mode)
    allow_failed_item_fallback = menu_recipe_failed_item_fallback_enabled(enrichment_mode)
    raw_urls = payload.get("recipe_urls") or payload.get("urls")
    if isinstance(raw_urls, str):
        raw_urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not isinstance(raw_urls, list):
        raw_urls = [payload.get("recipe_url") or payload.get("url") or payload.get("source_url") or ""]
    recipe_urls = [str(url or "").strip() for url in raw_urls if str(url or "").strip()]
    if not recipe_urls:
        return fail_job(job_id, "At least one menu item stub URL is required.")

    total = len(recipe_urls)
    recipe_model_resolution = menu_item_recipe_model_resolution()
    model_info = stored_job_model_metadata(job_id, model_metadata(
        recipe_model_resolution.model,
        recipe_model_resolution.source,
        OPENAI_MENU_RECIPE_MODEL_ENV_VAR,
    ))
    created_urls = []
    skipped_urls = []
    failed_items = 0
    pending_entries = []
    category_statuses = []
    category_success_count = 0
    nutrition_statuses = []
    nutrition_success_count = 0
    nutrition_failed_count = 0
    generated_recipe_results = {}
    failed_recipe_items = []

    def elapsed_seconds():
        return max(0.0, time.perf_counter() - job_started_at)

    def update_menu_progress(progress_stage, **kwargs):
        progress_started = time.perf_counter()
        result = update_job_progress(job_id, **kwargs)
        log_menu_enrichment_stage(
            "progress_update",
            job_id=job_id,
            mode=enrichment_mode,
            progress_stage=str(progress_stage or "").replace(" ", "_"),
            progress=kwargs.get("progress_percent"),
            elapsed=f"{time.perf_counter() - progress_started:.3f}s",
        )
        return result

    def record_failed_recipe_item(recipe_url, recipe_name="", stage="", error=""):
        recipe_url = str(recipe_url or "").strip()
        if not recipe_url:
            return
        failed_recipe_items.append({
            "recipe_url": recipe_url,
            "recipe_name": str(recipe_name or "").strip(),
            "stage": str(stage or "").strip(),
            "error": str(error or "").strip(),
        })
        try:
            mark_menu_recipe_import_failure(recipe_url, recipe_name, stage, error)
        except Exception as exc:
            print(
                "[MenuRecipeGeneration] action=failed_item_flag_save_failed "
                f"job_id={job_id} recipe_url={recipe_url} error={exc}"
            )

    update_menu_progress(
        "start",
        current_step="Predicting recipes",
        total_items=total,
        progress_percent=5,
        result_payload={
            **model_info,
            "stage": "Predicting recipes",
            "stage_detail": "Loading menu stubs",
            "menu_enrichment_mode": enrichment_mode,
            "recipe_batch_size": recipe_batch_size,
            "total_items": total,
            "recipe_shells_created": total,
            "recipe_inference_completed": 0,
            "nutrition_completed": 0,
            "nutrition_failed": 0,
            "failed_recipe_items": [],
            "pdfs_completed": 0,
            "failed_items": 0,
        },
    )

    load_started = time.perf_counter()
    for index, recipe_url in enumerate(recipe_urls):
        ensure_not_cancelled(job_id)
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        stub = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        stub = stub if isinstance(stub, dict) else {}
        if not stub:
            failed_items += 1
            append_job_warning(job_id, f"{recipe_url}: Menu item stub was not found.")
            continue

        menu_item = menu_batch_item_from_stub(recipe_url, stub, index)
        if menu_item_name_is_blank_divider(menu_item.get("item_name")):
            skipped_urls.append(recipe_url)
            continue

        inference = stub.get("recipe_inference") if isinstance(stub.get("recipe_inference"), dict) else {}
        already_generated = (
            str(stub.get("recipe_status") or "").strip().lower() == "generated"
            and not stub.get("needs_ai_recipe")
        ) or str(inference.get("status") or "").strip().lower() == "generated"
        if already_generated and not force_reprocess:
            skipped_urls.append(recipe_url)
            continue

        pending_entries.append({
            "recipe_url": recipe_url,
            "stub": stub,
            "menu_item": menu_item,
        })

    log_menu_enrichment_stage(
        "load_menu_stubs",
        job_id=job_id,
        mode=enrichment_mode,
        total=total,
        pending=len(pending_entries),
        skipped=len(skipped_urls),
        failed=failed_items,
        elapsed=f"{time.perf_counter() - load_started:.3f}s",
    )
    prepare_started = time.perf_counter()
    try:
        batches = menu_inference_batches(
            pending_entries,
            min_items=recipe_batch_size,
            max_items=recipe_batch_size,
            target_chars=recipe_batch_target_chars,
        )
    except TypeError as exc:
        if "min_items" not in str(exc) and "max_items" not in str(exc) and "target_chars" not in str(exc):
            raise
        batches = menu_inference_batches(pending_entries)
    batch_total = len(batches)
    completed_batches = 0
    predicted_batches_completed = 0
    batch_worker_count = menu_item_batch_inference_worker_count(batch_total)
    save_progress_every = menu_save_progress_update_every()
    followup_progress_every = menu_followup_progress_update_every()
    job_record = get_job(job_id) or {}
    inference_user_id = str(job_record.get("user_id") or active_user_id() or "").strip()
    job_queue_name = str(job_record.get("queue_name") or "ai-pantry-menu").strip() or "ai-pantry-menu"

    log_menu_enrichment_stage(
        "prepare_ai_input_batches",
        job_id=job_id,
        mode=enrichment_mode,
        total=total,
        pending=len(pending_entries),
        batch_count=batch_total,
        batch_size=recipe_batch_size,
        target_chars=recipe_batch_target_chars,
        elapsed=f"{time.perf_counter() - prepare_started:.3f}s",
    )

    print(
        "[MenuRecipeGeneration] action=start "
        f"job_id={job_id} total_items={total} pending_items={len(pending_entries)} "
        f"mode={enrichment_mode} batch_size={recipe_batch_size}"
    )
    if batch_total:
        print(
            "[Job Worker] action=menu-item-recipe-batch-parallel-start "
            f"job_id={job_id} batch_count={batch_total} worker_count={batch_worker_count} "
            f"item_count={len(pending_entries)}"
        )

    def run_prediction_batch(batch_index, batch):
        with job_context(
            job_id=job_id,
            queue_name=job_queue_name,
            model_used=model_info.get("model_used"),
            model_source=model_info.get("model_source"),
            model_env_var_used=model_info.get("model_env_var_used"),
            batch_index=batch_index,
            batch_count=batch_total,
            batch_size=len(batch or []),
        ):
            print(
                "[Job Worker] action=menu-item-recipe-batch-worker-start "
                f"job_id={job_id} batch_index={batch_index} batch_count={batch_total} "
                f"batch_size={len(batch or [])}"
            )
            print(
                "[MenuRecipeGeneration] action=batch_start "
                f"job_id={job_id} batch_index={batch_index} batch_size={len(batch or [])}"
            )
            batch_started = time.perf_counter()
            log_menu_enrichment_stage(
                "openai_batch_start",
                job_id=job_id,
                mode=enrichment_mode,
                batch=f"{batch_index}/{batch_total}",
                size=len(batch or []),
                model=model_info.get("model_used") or "",
                allow_failed_item_fallback=allow_failed_item_fallback,
            )
            try:
                result = infer_menu_item_recipe_batch(
                    batch,
                    user_id=inference_user_id,
                    allow_fallback=allow_failed_item_fallback,
                )
            except TypeError as exc:
                if "allow_fallback" not in str(exc):
                    raise
                result = infer_menu_item_recipe_batch(batch, user_id=inference_user_id)
            log_menu_enrichment_stage(
                "openai_batch",
                job_id=job_id,
                mode=enrichment_mode,
                batch=f"{batch_index}/{batch_total}",
                size=len(batch or []),
                model=(result.get("model") if isinstance(result, dict) else "") or model_info.get("model_used") or "",
                ok=bool(result.get("ok") if isinstance(result, dict) else False),
                result_items=len(result.get("items") or {}) if isinstance(result, dict) else 0,
                failed_items=len(result.get("failures") or {}) if isinstance(result, dict) else len(batch or []),
                elapsed=f"{time.perf_counter() - batch_started:.3f}s",
            )
            print(
                "[Job Worker] action=menu-item-recipe-batch-worker-ready "
                f"job_id={job_id} batch_index={batch_index} batch_count={batch_total} "
                f"ok={bool(result.get('ok') if isinstance(result, dict) else False)}"
            )
            return result

    def failed_batch_result(batch_index, exc):
        print(
            "[Job Worker] action=menu-item-recipe-batch-worker-error "
            f"job_id={job_id} batch_index={batch_index} batch_count={batch_total} "
            f"exception_type={type(exc).__name__} error={exc}"
        )
        return {
            "ok": False,
            "items": {},
            "failures": {},
            "error_message": str(exc) or "Unable to predict recipes.",
            "technical_message": str(exc),
            "exception_type": type(exc).__name__,
            "model": model_info.get("model_used") or "",
            "model_source": model_info.get("model_source") or "",
        }

    def record_prediction_result(batch_index, batch_result):
        nonlocal predicted_batches_completed
        predicted_batches_completed += 1
        update_menu_progress(
            "ai_generation",
            current_step=f"AI generation: batch {predicted_batches_completed} of {batch_total}",
            progress_percent=bounded_percent(predicted_batches_completed, max(1, batch_total), 10, 82),
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items,
            result_payload={
                **model_info,
                "stage": "Predicting recipes",
                "stage_detail": f"AI generation batch {predicted_batches_completed} of {batch_total}",
                "menu_enrichment_mode": enrichment_mode,
                "total_items": total,
                "recipe_inference_completed": len(created_urls),
                "recipe_prediction_batches_completed": predicted_batches_completed,
                "skipped_count": len(skipped_urls),
                "failed_items": failed_items,
                "failed_recipe_items": failed_recipe_items,
                "batch_count": batch_total,
                "batch_index": batch_index,
                "batch_workers": batch_worker_count,
                "recipe_batch_size": recipe_batch_size,
            },
        )
        return batch_result

    def process_predicted_batch(batch_index, batch, batch_result):
        nonlocal completed_batches
        nonlocal failed_items

        batch_ingredient_records = []
        batch_name_records = []
        batch_recipe_urls = []
        batch_shopping_items = []
        batch_result = batch_result if isinstance(batch_result, dict) else {}
        validate_started = time.perf_counter()
        result_items = batch_result.get("items") if isinstance(batch_result.get("items"), dict) else {}
        failure_items = batch_result.get("failures") if isinstance(batch_result.get("failures"), dict) else {}
        missing_ids = [
            str((entry.get("menu_item") or {}).get("menu_item_id") or "").strip()
            for entry in batch
            if str((entry.get("menu_item") or {}).get("menu_item_id") or "").strip() not in result_items
        ]
        failed_names = [
            menu_batch_entry_item_name(entry)
            for entry in batch
            if str((entry.get("menu_item") or {}).get("menu_item_id") or "").strip() in missing_ids
        ]
        log_menu_enrichment_stage(
            "validate_item_id_mapping",
            job_id=job_id,
            mode=enrichment_mode,
            batch=f"{batch_index}/{batch_total}",
            expected=len(batch or []),
            matched=len(result_items),
            missing=len(missing_ids),
            elapsed=f"{time.perf_counter() - validate_started:.3f}s",
        )
        failed_names_text = ", ".join(name for name in failed_names[:12] if name)
        if failed_names:
            print(
                "[Job Worker] action=menu-item-recipe-batch-final-failed-items "
                f"job_id={job_id} batch_index={batch_index} batch_count={batch_total} "
                f"failed_count={len(failed_names)} failed_item_names={failed_names_text}"
            )
        if not result_items:
            failed_items += len(batch)
            batch_error = (
                batch_result.get("error_message")
                or ("Missing menu_item_id: " + ", ".join(missing_ids[:3]) if missing_ids else "Unable to predict recipes.")
            )
            for entry in batch:
                failed_recipe_url = str(entry.get("recipe_url") or "").strip()
                record_failed_recipe_item(
                    failed_recipe_url,
                    menu_batch_entry_item_name(entry),
                    "Recipe generation",
                    batch_error,
                )
            append_job_warning(
                job_id,
                (
                    f"Batch {batch_index}/{batch_total}: "
                    f"{batch_error} "
                    f"Failed item names: {failed_names_text}"
                ).strip(),
            )
            completed_batches += 1
            return
        if not batch_result.get("ok") or missing_ids:
            append_job_warning(
                job_id,
                (
                    f"Batch {batch_index}/{batch_total}: keeping {len(result_items)} predicted recipe(s); "
                    f"{len(missing_ids)} item(s) failed. "
                    f"Failed item names: {failed_names_text}. "
                    f"{batch_result.get('error_message') or ''}"
                ).strip(),
            )

        prepared_save_results = []
        prepared_save_entries = []
        save_prepare_started = time.perf_counter()
        for entry in batch:
            ensure_not_cancelled(job_id)
            recipe_url = entry["recipe_url"]
            menu_item = entry.get("menu_item") if isinstance(entry.get("menu_item"), dict) else {}
            recipe_name = cookbook_recipe_display_name(
                recipe_url,
                {"name": menu_item.get("item_name")},
            )
            recipe_position = min(
                total,
                len(created_urls) + len(skipped_urls) + failed_items + len(prepared_save_results) + 1,
            )
            item_id = str(menu_item.get("menu_item_id") or "").strip()
            item_result = result_items.get(item_id)
            if not isinstance(item_result, dict):
                failed_items += 1
                failure = failure_items.get(item_id) if isinstance(failure_items.get(item_id), dict) else {}
                failure_error = failure.get("error") or f"Batch response did not include menu_item_id {item_id}."
                record_failed_recipe_item(recipe_url, recipe_name, "Recipe generation", failure_error)
                append_job_warning(
                    job_id,
                    (
                        f"{recipe_name} ({recipe_url}): "
                        f"{failure_error}"
                    ).strip(),
                )
                continue

            if (
                recipe_position <= 1
                or recipe_position >= total
                or recipe_position % save_progress_every == 0
            ):
                update_menu_progress(
                    "save_prepare",
                    current_step=f"Saving recipes: preparing item {recipe_position} of {total}",
                    progress_percent=bounded_percent(len(created_urls), total, 82, 88),
                    completed_items=len(created_urls) + len(skipped_urls),
                    failed_items=failed_items,
                    result_payload={
                        **model_info,
                        "stage": "Saving predicted recipes",
                        "stage_detail": f"Preparing recipe save item {recipe_position} of {total}",
                        "menu_enrichment_mode": enrichment_mode,
                        "total_items": total,
                        "recipe_inference_completed": len(created_urls),
                        "recipe_prediction_batches_completed": predicted_batches_completed,
                        "batch_workers": batch_worker_count,
                        "save_progress_every": save_progress_every,
                        "skipped_count": len(skipped_urls),
                        "nutrition_completed": nutrition_success_count,
                        "nutrition_failed": nutrition_failed_count,
                        "category_success_count": category_success_count,
                        "failed_items": failed_items,
                        "failed_recipe_items": failed_recipe_items,
                        **cookbook_recipe_progress_payload(
                            "recipe_generation",
                            "Saving predicted recipe for",
                            recipe_url,
                            recipe_name,
                            recipe_position,
                            total,
                            event="started",
                        ),
                    },
                )

            try:
                result = build_menu_batch_inference_result(
                    recipe_url,
                    entry.get("stub") or {},
                    menu_item,
                    item_result,
                    model=batch_result.get("model") or model_info.get("model_used"),
                    model_source=batch_result.get("model_source") or model_info.get("model_source"),
                )
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": str(exc) or "Unable to prepare predicted recipe.",
                    "exception_type": type(exc).__name__,
                }
            if not result.get("ok"):
                failed_items += 1
                save_error = result.get("error") or "Unable to prepare predicted recipe."
                record_failed_recipe_item(recipe_url, recipe_name, "Recipe generation", save_error)
                append_job_warning(job_id, f"{recipe_url}: {save_error}")
                continue

            prepared_save_results.append(result)
            prepared_save_entries.append({
                "recipe_url": recipe_url,
                "recipe_name": recipe_name,
                "recipe_position": recipe_position,
            })

        log_menu_enrichment_stage(
            "save_predicted_recipes",
            job_id=job_id,
            mode=enrichment_mode,
            batch=f"{batch_index}/{batch_total}",
            prepared=len(prepared_save_results),
            failed=failed_items,
            elapsed=f"{time.perf_counter() - save_prepare_started:.3f}s",
        )

        if prepared_save_results:
            print(
                "[MenuRecipeGeneration] action=bulk_save_start "
                f"job_id={job_id} batch_index={batch_index} batch_size={len(prepared_save_results)} "
                f"progress_update_every={save_progress_every}"
            )
            write_started = time.perf_counter()
            save_statuses = save_menu_batch_inference_results(prepared_save_results)
            log_menu_enrichment_stage(
                "write_recipe_json",
                job_id=job_id,
                mode=enrichment_mode,
                batch=f"{batch_index}/{batch_total}",
                requested=len(prepared_save_results),
                elapsed=f"{time.perf_counter() - write_started:.3f}s",
            )
            saved_count = 0
            save_failed_count = 0
            for index, prepared in enumerate(prepared_save_entries):
                ensure_not_cancelled(job_id)
                save_status = save_statuses[index] if index < len(save_statuses) else {}
                recipe_url = prepared["recipe_url"]
                recipe_name = prepared["recipe_name"]
                recipe_position = prepared["recipe_position"]
                result = prepared_save_results[index]
                if not save_status.get("ok"):
                    failed_items += 1
                    save_failed_count += 1
                    save_error = save_status.get("error") or "Unable to save predicted recipe."
                    record_failed_recipe_item(recipe_url, recipe_name, "Recipe generation", save_error)
                    append_job_warning(job_id, f"{recipe_url}: {save_error}")
                    continue

                saved_count += 1
                ingredients = result.get("ingredients") if isinstance(result.get("ingredients"), list) else []
                if ingredients:
                    batch_shopping_items.extend(ingredients)
                    batch_ingredient_records.append({
                        "url": recipe_url,
                        "ingredients": ingredients,
                        "recipe_metadata": result,
                    })
                if result.get("display_name") or result.get("recipe_title"):
                    batch_name_records.append({
                        "url": recipe_url,
                        "name": result.get("display_name") or result.get("recipe_title"),
                    })
                batch_recipe_urls.append(recipe_url)

                generated_recipe_results[recipe_url] = result
                print(
                    "[recipe_import] action=menu_stub_generated_batch "
                    f"title={import_recipe_title(result, recipe_url)} url={recipe_url}"
                )
                created_urls.append(recipe_url)

                if (
                    recipe_position >= total
                    or recipe_position % save_progress_every == 0
                    or index == len(prepared_save_entries) - 1
                ):
                    update_menu_progress(
                        "save_batch",
                        current_step=f"Saving recipes: item {len(created_urls)} of {total}",
                        progress_percent=bounded_percent(len(created_urls), total, 82, 88),
                        completed_items=len(created_urls) + len(skipped_urls),
                        failed_items=failed_items,
                        result_payload={
                            **model_info,
                            "stage": "Saving predicted recipes",
                            "stage_detail": f"Saving recipes item {len(created_urls)} of {total}",
                            "menu_enrichment_mode": enrichment_mode,
                            "total_items": total,
                            "recipe_inference_completed": len(created_urls),
                            "recipe_prediction_batches_completed": predicted_batches_completed,
                            "batch_workers": batch_worker_count,
                            "save_progress_every": save_progress_every,
                            "skipped_count": len(skipped_urls),
                            "nutrition_completed": nutrition_success_count,
                            "nutrition_failed": nutrition_failed_count,
                            "category_success_count": category_success_count,
                            "failed_items": failed_items,
                            "failed_recipe_items": failed_recipe_items,
                            **cookbook_recipe_progress_payload(
                                "recipe_generation",
                                "Saving predicted recipes",
                                recipe_url,
                                recipe_name,
                                recipe_position,
                                total,
                                event="completed",
                            ),
                        },
                    )
            print(
                "[MenuRecipeGeneration] action=bulk_save_ready "
                f"job_id={job_id} batch_index={batch_index} saved_count={saved_count} "
                f"failed_count={save_failed_count}"
            )

        if batch_recipe_urls:
            index_started = time.perf_counter()
            with workspace_write_lock("recipe-imports"):
                if batch_shopping_items:
                    add_items(batch_shopping_items)
                if batch_ingredient_records:
                    save_ingredients_for_recipes(batch_ingredient_records)
                if batch_name_records:
                    save_recipe_url_names(batch_name_records)
                add_recipe_urls(batch_recipe_urls)
            log_menu_enrichment_stage(
                "update_indexes",
                job_id=job_id,
                mode=enrichment_mode,
                batch=f"{batch_index}/{batch_total}",
                recipes=len(batch_recipe_urls),
                ingredients=len(batch_ingredient_records),
                names=len(batch_name_records),
                elapsed=f"{time.perf_counter() - index_started:.3f}s",
            )

        completed_batches += 1

    batch_results = {}
    futures = {}
    next_batch_to_submit = 0
    next_batch_to_process = 1

    def submit_available_batches(executor):
        nonlocal next_batch_to_submit
        while next_batch_to_submit < batch_total:
            batch_index = next_batch_to_submit + 1
            future = executor.submit(run_prediction_batch, batch_index, batches[next_batch_to_submit])
            futures[future] = batch_index
            next_batch_to_submit += 1

    if batch_total:
        update_menu_progress(
            "ai_generation_start",
            current_step=f"AI generation: batch 0 of {batch_total}",
            progress_percent=10,
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items,
            result_payload={
                **model_info,
                "stage": "Predicting recipes",
                "stage_detail": f"AI generation batch 0 of {batch_total}",
                "menu_enrichment_mode": enrichment_mode,
                "total_items": total,
                "recipe_inference_completed": len(created_urls),
                "recipe_prediction_batches_completed": 0,
                "skipped_count": len(skipped_urls),
                "failed_items": failed_items,
                "batch_count": batch_total,
                "batch_index": 0,
                "batch_workers": batch_worker_count,
                "recipe_batch_size": recipe_batch_size,
            },
        )

    with ThreadPoolExecutor(
        max_workers=batch_worker_count,
        thread_name_prefix="menu-recipe-batch",
    ) as executor:
        submit_available_batches(executor)
        try:
            while next_batch_to_process <= batch_total:
                ensure_not_cancelled(job_id)
                while next_batch_to_process not in batch_results:
                    ensure_not_cancelled(job_id)
                    if not futures:
                        break
                    done, _pending = wait(
                        list(futures.keys()),
                        timeout=0.5,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        batch_index = futures.pop(future)
                        try:
                            batch_result = future.result()
                        except Exception as exc:
                            batch_result = failed_batch_result(batch_index, exc)
                        batch_results[batch_index] = record_prediction_result(batch_index, batch_result)
                    submit_available_batches(executor)

                while next_batch_to_process in batch_results:
                    batch_result = batch_results.pop(next_batch_to_process)
                    process_predicted_batch(
                        next_batch_to_process,
                        batches[next_batch_to_process - 1],
                        batch_result,
                    )
                    next_batch_to_process += 1
                    ensure_not_cancelled(job_id)
        except JobCancelled:
            for future in list(futures.keys()):
                future.cancel()
            raise

    ensure_not_cancelled(job_id)
    if created_urls:
        update_menu_progress(
            "finalize_recipe_generation",
            current_step="Finalizing predicted recipes",
            progress_percent=88,
            result_payload={
                **model_info,
                "stage": "Predicting recipes",
                "stage_detail": "Finalizing predicted recipes",
                "menu_enrichment_mode": enrichment_mode,
                "recipe_inference_completed": len(created_urls),
                "nutrition_completed": nutrition_success_count,
                "nutrition_failed": nutrition_failed_count,
                "failed_items": failed_items + nutrition_failed_count,
                "failed_recipe_items": failed_recipe_items,
            },
        )
        sort_started = time.perf_counter()
        with workspace_write_lock("recipe-imports"):
            sort_ingredients()
        log_menu_enrichment_stage(
            "update_indexes",
            job_id=job_id,
            mode=enrichment_mode,
            operation="sort_ingredients",
            elapsed=f"{time.perf_counter() - sort_started:.3f}s",
        )

    if fast_mode and (created_urls or skipped_urls):
        total_failed_items = failed_items
        retry_failed_recipe_urls = [
            item.get("recipe_url", "")
            for item in failed_recipe_items
            if item.get("recipe_url")
        ]
        result_payload = {
            "ok": True,
            "created_count": len(created_urls),
            "generated_count": len(created_urls),
            "full_recipes_generated": len(created_urls),
            "recipe_inference_completed": len(created_urls),
            "skipped_count": len(skipped_urls),
            "failed_count": total_failed_items,
            "failed_items": total_failed_items,
            "recipe_urls": created_urls + skipped_urls,
            "generated_recipe_urls": created_urls,
            "skipped_recipe_urls": skipped_urls,
            "retry_failed_recipe_urls": retry_failed_recipe_urls,
            "links": recipe_links(created_urls + skipped_urls),
            "nutrition_estimates_completed": 0,
            "nutrition_completed": 0,
            "nutrition_failed": 0,
            "nutrition_statuses": [],
            "failed_recipe_items": failed_recipe_items,
            "pdfs_created": 0,
            "pdfs_completed": 0,
            "category_statuses": [],
            "category_success_count": 0,
            "categories_generated": 0,
            "batch_count": batch_total,
            "batches_completed": completed_batches,
            "recipe_prediction_batches_completed": predicted_batches_completed,
            "batch_workers": batch_worker_count,
            "recipe_batch_size": recipe_batch_size,
            "menu_enrichment_mode": enrichment_mode,
            "enrichment_deferred": False,
            "run_generated_pdfs": False,
            "stage": "Complete",
            "stage_detail": "Fast recipe generation complete",
            **model_info,
            **clear_cookbook_recipe_progress_payload(),
        }
        update_menu_progress(
            "complete",
            current_step="Fast recipe generation complete",
            progress_percent=99,
            total_items=total,
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=total_failed_items,
            result_payload=result_payload,
        )
        total_elapsed = elapsed_seconds()
        target_seconds = menu_recipe_fast_target_seconds()
        warning = "target_exceeded" if total_elapsed > target_seconds else None
        log_menu_enrichment_stage(
            "complete",
            job_id=job_id,
            mode=enrichment_mode,
            total_elapsed=f"{total_elapsed:.3f}s",
            target=target_seconds,
            warning=warning,
            created=len(created_urls),
            skipped=len(skipped_urls),
            failed=total_failed_items,
        )
        return complete_job(job_id, result_payload=result_payload)

    if created_urls and menu_deferred_enrichment_enabled(payload, len(created_urls)):
        run_generated_pdfs = menu_generated_pdfs_enabled(payload, len(created_urls))
        print(
            "[MenuRecipeGeneration] action=defer_enrichment_start "
            f"job_id={job_id} total_items={len(created_urls)} "
            f"inline_enrichment_max_items={menu_inline_enrichment_max_items()} "
            f"run_generated_pdfs={bool(run_generated_pdfs)}"
        )
        update_menu_progress(
            "enqueue_next_jobs_start",
            current_step="Queueing menu nutrition and categories",
            progress_percent=96,
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items,
            result_payload={
                **model_info,
                "stage": "Queueing menu nutrition and categories",
                "stage_detail": "Queueing nutrition/categories follow-up",
                "menu_enrichment_mode": enrichment_mode,
                "total_items": total,
                "recipe_inference_completed": len(created_urls),
                "recipe_prediction_batches_completed": predicted_batches_completed,
                "batch_workers": batch_worker_count,
                "skipped_count": len(skipped_urls),
                "failed_items": failed_items,
                "failed_recipe_items": failed_recipe_items,
                "enrichment_deferred": True,
                "run_generated_pdfs": bool(run_generated_pdfs),
            },
        )
        enqueue_started = time.perf_counter()
        heavy_job = enqueue_followup_job(
            "menu-deferred-heavy-tasks",
            {
                "recipe_urls": created_urls,
                "force_reprocess": force_reprocess,
                "source_job_id": job_id,
                "context": "menu-batch-generation",
                "run_categories": True,
                "run_generated_pdfs": bool(run_generated_pdfs),
            },
            total_items=len(created_urls),
        )
        log_menu_enrichment_stage(
            "enqueue_next_jobs",
            job_id=job_id,
            mode=enrichment_mode,
            job_type="menu-deferred-heavy-tasks",
            queued=bool(heavy_job.get("queued")),
            followup_job_id=heavy_job.get("job_id", ""),
            elapsed=f"{time.perf_counter() - enqueue_started:.3f}s",
        )
        if not heavy_job.get("queued"):
            append_job_warning(job_id, heavy_job.get("error") or "Menu nutrition/category enrichment was not queued.")
        print(
            "[MenuRecipeGeneration] action=defer_enrichment_ready "
            f"job_id={job_id} followup_job_id={heavy_job.get('job_id', '')} "
            f"queued={bool(heavy_job.get('queued'))} total_items={len(created_urls)} "
            f"run_generated_pdfs={bool(run_generated_pdfs)}"
        )
        result_payload = {
            "ok": True,
            "created_count": len(created_urls),
            "generated_count": len(created_urls),
            "full_recipes_generated": len(created_urls),
            "recipe_inference_completed": len(created_urls),
            "skipped_count": len(skipped_urls),
            "failed_count": failed_items,
            "failed_items": failed_items,
            "recipe_urls": created_urls + skipped_urls,
            "generated_recipe_urls": created_urls,
            "skipped_recipe_urls": skipped_urls,
            "links": recipe_links(created_urls + skipped_urls),
            "nutrition_estimates_completed": 0,
            "nutrition_completed": 0,
            "nutrition_failed": 0,
            "nutrition_statuses": [],
            "failed_recipe_items": failed_recipe_items,
            "pdfs_created": 0,
            "pdfs_completed": 0,
            "category_statuses": [],
            "category_success_count": 0,
            "categories_generated": 0,
            "batch_count": batch_total,
            "batches_completed": completed_batches,
            "recipe_prediction_batches_completed": predicted_batches_completed,
            "batch_workers": batch_worker_count,
            "recipe_batch_size": recipe_batch_size,
            "menu_enrichment_mode": enrichment_mode,
            "deferred_heavy_tasks_job": heavy_job,
            "deferred_heavy_tasks_job_id": heavy_job.get("job_id", ""),
            "enrichment_deferred": True,
            "run_generated_pdfs": bool(run_generated_pdfs),
            "stage": "Complete",
            "stage_detail": "Recipe generation complete; nutrition/categories queued",
            **model_info,
            **clear_cookbook_recipe_progress_payload(),
        }
        update_menu_progress(
            "complete",
            current_step="Recipe generation complete; menu nutrition and categories queued",
            progress_percent=99,
            total_items=total,
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items,
            result_payload=result_payload,
        )
        log_menu_enrichment_stage(
            "complete",
            job_id=job_id,
            mode=enrichment_mode,
            total_elapsed=f"{elapsed_seconds():.3f}s",
            created=len(created_urls),
            skipped=len(skipped_urls),
            failed=failed_items,
            followup_job_id=heavy_job.get("job_id", ""),
        )
        return complete_job(job_id, result_payload=result_payload)

    nutrition_ok_by_url = {}
    nutrition_worker_count = menu_nutrition_worker_count(len(created_urls)) if created_urls else 1

    def run_nutrition_for_recipe(index, recipe_url):
        result = dict(generated_recipe_results.get(recipe_url) if isinstance(generated_recipe_results.get(recipe_url), dict) else {})
        recipe_name = cookbook_recipe_display_name(recipe_url, result)
        with job_context(
            job_id=job_id,
            queue_name=job_queue_name,
            worker_id=(get_job(job_id) or {}).get("worker_id") or "",
        ):
            print(
                "[MenuRecipeGeneration] action=nutrition_start "
                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name}"
            )
            try:
                nutrition_status = ensure_menu_recipe_serving_basis_estimate(recipe_url, result)
            except Exception as exc:
                nutrition_status = {
                    "ok": False,
                    "recipe_url": recipe_url,
                    "error": str(exc) or "Unable to estimate serving basis.",
                }
        nutrition_status = nutrition_status if isinstance(nutrition_status, dict) else {
            "ok": False,
            "recipe_url": recipe_url,
            "error": "Invalid serving basis result.",
        }
        return {
            "index": index,
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
            "result": result,
            "status": nutrition_status,
        }

    if created_urls:
        update_job_progress(
            job_id,
            current_step=f"Estimating per serving basis (0/{len(created_urls)})",
            progress_percent=89,
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items + nutrition_failed_count,
            result_payload={
                **model_info,
                "stage": "Estimating per serving basis",
                "total_items": total,
                "recipe_inference_completed": len(created_urls),
                "recipe_prediction_batches_completed": predicted_batches_completed,
                "batch_workers": batch_worker_count,
                "nutrition_workers": nutrition_worker_count,
                "nutrition_completed": nutrition_success_count,
                "nutrition_failed": nutrition_failed_count,
                "category_success_count": category_success_count,
                "failed_items": failed_items + nutrition_failed_count,
                "failed_recipe_items": failed_recipe_items,
            },
        )
        print(
            "[MenuRecipeGeneration] action=nutrition_parallel_start "
            f"job_id={job_id} total_items={len(created_urls)} worker_count={nutrition_worker_count}"
        )
        nutrition_completed_count = 0
        nutrition_futures = {}
        with ThreadPoolExecutor(
            max_workers=nutrition_worker_count,
            thread_name_prefix="menu-nutrition",
        ) as executor:
            try:
                for index, recipe_url in enumerate(created_urls):
                    nutrition_task = copy_current_request_context_if_available(
                        lambda index=index, recipe_url=recipe_url: run_nutrition_for_recipe(index, recipe_url)
                    )
                    nutrition_futures[executor.submit(nutrition_task)] = (index, recipe_url)
                while nutrition_futures:
                    ensure_not_cancelled(job_id)
                    done, _pending = wait(
                        list(nutrition_futures.keys()),
                        timeout=0.5,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        index, recipe_url = nutrition_futures.pop(future)
                        result = generated_recipe_results.get(recipe_url) if isinstance(generated_recipe_results.get(recipe_url), dict) else {}
                        recipe_name = cookbook_recipe_display_name(recipe_url, result)
                        try:
                            worker_result = future.result()
                        except Exception as exc:
                            worker_result = {
                                "index": index,
                                "recipe_url": recipe_url,
                                "recipe_name": recipe_name,
                                "result": result,
                                "status": {
                                    "ok": False,
                                    "recipe_url": recipe_url,
                                    "error": str(exc) or "Unable to estimate serving basis.",
                                },
                            }
                        nutrition_status = worker_result.get("status") if isinstance(worker_result.get("status"), dict) else {
                            "ok": False,
                            "recipe_url": recipe_url,
                            "error": "Invalid serving basis result.",
                        }
                        result = worker_result.get("result") if isinstance(worker_result.get("result"), dict) else result
                        recipe_name = worker_result.get("recipe_name") or recipe_name
                        nutrition_completed_count += 1
                        nutrition_statuses.append({
                            "ok": bool(nutrition_status.get("ok")),
                            "recipe_url": recipe_url,
                            "recipe_name": recipe_name,
                            "already_complete": bool(nutrition_status.get("already_complete")),
                            "estimated": bool(nutrition_status.get("estimated")),
                            "error": str(nutrition_status.get("error") or ""),
                            "model_used": str(nutrition_status.get("model_used") or ""),
                        })
                        result = {
                            **result,
                            "serving_basis_status": nutrition_status,
                            "nutrition_status": nutrition_status,
                        }
                        if nutrition_status.get("ok"):
                            nutrition_success_count += 1
                            nutrition_ok_by_url[recipe_url] = True
                            updated_recipe = nutrition_status.get("recipe_json") if isinstance(nutrition_status.get("recipe_json"), dict) else {}
                            if updated_recipe:
                                result = {
                                    **result,
                                    "raw": updated_recipe,
                                    "recipe_json": updated_recipe,
                                    "nutrition": updated_recipe.get("nutrition", result.get("nutrition", [])),
                                    "nutrition_inference": updated_recipe.get("nutrition_inference", result.get("nutrition_inference")),
                                }
                            print(
                                "[MenuRecipeGeneration] action=nutrition_ready "
                                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name} "
                                f"already_complete={bool(nutrition_status.get('already_complete'))}"
                            )
                        else:
                            nutrition_failed_count += 1
                            nutrition_ok_by_url[recipe_url] = False
                            error = nutrition_status.get("error") or "Unable to estimate serving basis."
                            record_failed_recipe_item(recipe_url, recipe_name, "Nutrition", error)
                            append_job_warning(job_id, f"{recipe_name} ({recipe_url}): {error}")
                            print(
                                "[MenuRecipeGeneration] action=nutrition_failed "
                                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name} error={error}"
                            )
                        generated_recipe_results[recipe_url] = result
                        if (
                            nutrition_completed_count <= 1
                            or nutrition_completed_count >= len(created_urls)
                            or nutrition_completed_count % followup_progress_every == 0
                        ):
                            update_job_progress(
                                job_id,
                                current_step=f"Estimating per serving basis ({nutrition_completed_count}/{len(created_urls)})",
                                progress_percent=bounded_percent(nutrition_completed_count, len(created_urls), 89, 93),
                                completed_items=len(created_urls) + len(skipped_urls),
                                failed_items=failed_items + nutrition_failed_count,
                                result_payload={
                                    **model_info,
                                    "stage": "Estimating per serving basis",
                                    "total_items": total,
                                    "recipe_inference_completed": len(created_urls),
                                    "recipe_prediction_batches_completed": predicted_batches_completed,
                                    "batch_workers": batch_worker_count,
                                    "nutrition_workers": nutrition_worker_count,
                                    "followup_progress_every": followup_progress_every,
                                    "nutrition_completed": nutrition_success_count,
                                    "nutrition_failed": nutrition_failed_count,
                                    "category_success_count": category_success_count,
                                    "failed_items": failed_items + nutrition_failed_count,
                                    "failed_recipe_items": failed_recipe_items,
                                    **cookbook_recipe_progress_payload(
                                        "nutrition",
                                        "Finished nutrition for",
                                        recipe_url,
                                        recipe_name,
                                        nutrition_completed_count,
                                        len(created_urls),
                                        event="completed" if nutrition_status.get("ok") else "failed",
                                    ),
                                },
                            )
            except JobCancelled:
                for future in list(nutrition_futures.keys()):
                    future.cancel()
                raise

    category_worker_count = menu_category_worker_count(len(created_urls)) if created_urls else 1

    def run_category_for_recipe(index, recipe_url):
        result = dict(generated_recipe_results.get(recipe_url) if isinstance(generated_recipe_results.get(recipe_url), dict) else {})
        recipe_name = cookbook_recipe_display_name(recipe_url, result)
        with job_context(
            job_id=job_id,
            queue_name=job_queue_name,
            worker_id=(get_job(job_id) or {}).get("worker_id") or "",
        ):
            print(
                "[MenuRecipeGeneration] action=category_start "
                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name}"
            )
            assignment = cookbook_recipe_assignment_for_url(recipe_url)
            if not assignment.get("cookbook_id"):
                assignment = {
                    "cookbook_id": result.get("cookbook_id") or "",
                    "cookbook_name": result.get("cookbook_name") or "",
                }
            try:
                category_status = apply_imported_recipe_category_routine(
                    recipe_url,
                    result,
                    assignment,
                    trigger_source="menu_generate:all",
                )
            except Exception as exc:
                category_status = {
                    "ok": False,
                    "recipe_url": recipe_url,
                    "error": str(exc) or "Category inference skipped.",
                }
        return {
            "index": index,
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
            "result": result,
            "status": category_status if isinstance(category_status, dict) else {
                "ok": False,
                "recipe_url": recipe_url,
                "error": "Invalid category result.",
            },
        }

    if created_urls:
        update_job_progress(
            job_id,
            current_step="Nutrition complete; generating categories",
            progress_percent=94,
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items + nutrition_failed_count,
            result_payload={
                **model_info,
                "stage": "Generating categories",
                "total_items": total,
                "recipe_inference_completed": len(created_urls),
                "recipe_prediction_batches_completed": predicted_batches_completed,
                "batch_workers": batch_worker_count,
                "nutrition_workers": nutrition_worker_count,
                "category_workers": category_worker_count,
                "nutrition_completed": nutrition_success_count,
                "nutrition_failed": nutrition_failed_count,
                "category_success_count": category_success_count,
                "failed_items": failed_items + nutrition_failed_count,
                "failed_recipe_items": failed_recipe_items,
            },
        )
        category_targets = []
        category_completed_count = 0
        for index, recipe_url in enumerate(created_urls):
            result = generated_recipe_results.get(recipe_url) if isinstance(generated_recipe_results.get(recipe_url), dict) else {}
            recipe_name = cookbook_recipe_display_name(recipe_url, result)
            if nutrition_ok_by_url.get(recipe_url):
                category_targets.append((index, recipe_url))
                continue
            error = next(
                (
                    status.get("error") or "Serving basis estimation failed."
                    for status in nutrition_statuses
                    if status.get("recipe_url") == recipe_url
                ),
                "Serving basis estimation failed.",
            )
            category_status = {
                "ok": False,
                "recipe_url": recipe_url,
                "status": "skipped",
                "error": f"Category generation skipped because serving basis estimation failed: {error}",
            }
            category_statuses.append(category_status)
            result = {
                **result,
                "import_category_status": category_status,
                "category_status": category_status,
            }
            generated_recipe_results[recipe_url] = result
            record_recipe_import_activity(recipe_url, result, "menu-batch-generation")
            category_completed_count += 1

        if category_targets:
            category_worker_count = menu_category_worker_count(len(category_targets))
            print(
                "[MenuRecipeGeneration] action=category_parallel_start "
                f"job_id={job_id} total_items={len(category_targets)} worker_count={category_worker_count}"
            )
            category_futures = {}
            with ThreadPoolExecutor(
                max_workers=category_worker_count,
                thread_name_prefix="menu-category",
            ) as executor:
                try:
                    for index, recipe_url in category_targets:
                        category_task = copy_current_request_context_if_available(
                            lambda index=index, recipe_url=recipe_url: run_category_for_recipe(index, recipe_url)
                        )
                        category_futures[executor.submit(category_task)] = (index, recipe_url)
                    while category_futures:
                        ensure_not_cancelled(job_id)
                        done, _pending = wait(
                            list(category_futures.keys()),
                            timeout=0.5,
                            return_when=FIRST_COMPLETED,
                        )
                        if not done:
                            continue
                        for future in done:
                            index, recipe_url = category_futures.pop(future)
                            result = generated_recipe_results.get(recipe_url) if isinstance(generated_recipe_results.get(recipe_url), dict) else {}
                            recipe_name = cookbook_recipe_display_name(recipe_url, result)
                            try:
                                worker_result = future.result()
                            except Exception as exc:
                                worker_result = {
                                    "index": index,
                                    "recipe_url": recipe_url,
                                    "recipe_name": recipe_name,
                                    "result": result,
                                    "status": {
                                        "ok": False,
                                        "recipe_url": recipe_url,
                                        "error": str(exc) or "Category inference skipped.",
                                    },
                                }
                            category_completed_count += 1
                            category_status = worker_result.get("status") if isinstance(worker_result.get("status"), dict) else {
                                "ok": False,
                                "recipe_url": recipe_url,
                                "error": "Invalid category result.",
                            }
                            category_statuses.append({
                                **category_status,
                                "recipe_url": recipe_url,
                                "recipe_name": recipe_name,
                            })
                            recipe_name = worker_result.get("recipe_name") or recipe_name
                            result = worker_result.get("result") if isinstance(worker_result.get("result"), dict) else result
                            if category_status.get("ok"):
                                category_success_count += 1
                            else:
                                category_error = category_status.get("error") or "Category inference skipped."
                                record_failed_recipe_item(recipe_url, recipe_name, "Categories", category_error)
                                append_job_warning(
                                    job_id,
                                    f"{import_recipe_title(result, recipe_url)}: {category_error}",
                                )
                            result = {
                                **result,
                                "import_category_status": category_status,
                                "category_status": category_status,
                            }
                            generated_recipe_results[recipe_url] = result
                            record_recipe_import_activity(recipe_url, result, "menu-batch-generation")
                            if (
                                category_completed_count <= 1
                                or category_completed_count >= len(created_urls)
                                or category_completed_count % followup_progress_every == 0
                            ):
                                update_job_progress(
                                    job_id,
                                    current_step=f"Generating ChatGPT categories ({category_completed_count}/{len(created_urls)})",
                                    progress_percent=bounded_percent(category_completed_count, len(created_urls), 94, 97),
                                    completed_items=len(created_urls) + len(skipped_urls),
                                    failed_items=failed_items + nutrition_failed_count,
                                    result_payload={
                                        **model_info,
                                        "stage": "Generating categories",
                                        "total_items": total,
                                        "recipe_inference_completed": len(created_urls),
                                        "recipe_prediction_batches_completed": predicted_batches_completed,
                                        "batch_workers": batch_worker_count,
                                        "nutrition_workers": nutrition_worker_count,
                                        "category_workers": category_worker_count,
                                        "followup_progress_every": followup_progress_every,
                                        "nutrition_completed": nutrition_success_count,
                                        "nutrition_failed": nutrition_failed_count,
                                        "category_success_count": category_success_count,
                                        "failed_items": failed_items + nutrition_failed_count,
                                        "failed_recipe_items": failed_recipe_items,
                                        **cookbook_recipe_progress_payload(
                                            "categories",
                                            "Finished category decision for",
                                            recipe_url,
                                            recipe_name,
                                            category_completed_count,
                                            len(created_urls),
                                            event="completed" if category_status.get("ok") else "failed",
                                        ),
                                    },
                                )
                except JobCancelled:
                    for future in list(category_futures.keys()):
                        future.cancel()
                    raise

    heavy_job = {}
    if run_heavy_tasks and created_urls and menu_generated_pdfs_enabled(payload, len(created_urls)):
        update_job_progress(
            job_id,
            current_step="Queueing generated recipe PDFs",
            progress_percent=98,
            result_payload={
                **model_info,
                "stage": "Queueing generated recipe PDFs",
                "recipe_inference_completed": len(created_urls),
                "nutrition_completed": nutrition_success_count,
                "nutrition_failed": nutrition_failed_count,
                "pdfs_completed": 0,
                "failed_items": failed_items + nutrition_failed_count,
                "failed_recipe_items": failed_recipe_items,
            },
        )
        heavy_job = enqueue_followup_job(
            "menu-deferred-heavy-tasks",
            {
                "recipe_urls": created_urls,
                "force_reprocess": force_reprocess,
                "source_job_id": job_id,
                "context": "menu-batch-generation",
                "run_nutrition": False,
                "run_categories": False,
                "run_generated_pdfs": True,
            },
            total_items=len(created_urls),
        )
        if not heavy_job.get("queued"):
            append_job_warning(job_id, heavy_job.get("error") or "Generated recipe PDF tasks were not queued.")

    total_failed_items = failed_items + nutrition_failed_count
    result_payload = {
        "ok": bool(created_urls or skipped_urls),
        "created_count": len(created_urls),
        "generated_count": len(created_urls),
        "full_recipes_generated": len(created_urls),
        "recipe_inference_completed": len(created_urls),
        "skipped_count": len(skipped_urls),
        "failed_count": total_failed_items,
        "failed_items": total_failed_items,
        "recipe_urls": created_urls + skipped_urls,
        "generated_recipe_urls": created_urls,
        "skipped_recipe_urls": skipped_urls,
        "links": recipe_links(created_urls + skipped_urls),
        "nutrition_estimates_completed": nutrition_success_count,
        "nutrition_completed": nutrition_success_count,
        "nutrition_failed": nutrition_failed_count,
        "nutrition_statuses": nutrition_statuses,
        "failed_recipe_items": failed_recipe_items,
        "pdfs_created": 0,
        "pdfs_completed": 0,
        "category_statuses": category_statuses,
        "category_success_count": category_success_count,
        "categories_generated": category_success_count,
        "batch_count": batch_total,
        "batches_completed": completed_batches,
        "recipe_prediction_batches_completed": predicted_batches_completed,
        "batch_workers": batch_worker_count,
        "recipe_batch_size": recipe_batch_size,
        "menu_enrichment_mode": enrichment_mode,
        "deferred_heavy_tasks_job": heavy_job,
        "deferred_heavy_tasks_job_id": heavy_job.get("job_id", ""),
        "stage": "Complete",
        "stage_detail": "Full recipe generation complete",
        **model_info,
    }
    update_menu_progress(
        "complete",
        current_step="Finalizing results",
        progress_percent=99,
        total_items=total,
        completed_items=len(created_urls) + len(skipped_urls),
        failed_items=total_failed_items,
        result_payload=result_payload,
    )
    log_menu_enrichment_stage(
        "complete",
        job_id=job_id,
        mode=enrichment_mode,
        total_elapsed=f"{elapsed_seconds():.3f}s",
        created=len(created_urls),
        skipped=len(skipped_urls),
        failed=total_failed_items,
    )

    if created_urls or skipped_urls:
        return complete_job(job_id, result_payload=result_payload)
    return fail_job(job_id, "No menu item stubs were generated.", result_payload=result_payload)


def run_menu_deferred_enrichment_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import MODEL
    from PushShoppingList.routes.recipe_routes import apply_imported_recipe_category_routine
    from PushShoppingList.routes.recipe_routes import ensure_menu_recipe_serving_basis_estimate
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import record_recipe_import_activity
    from PushShoppingList.services.cookbook_service import cookbook_recipe_assignment_for_url
    from PushShoppingList.services.recipe_edit_service import generate_editable_recipe_pdf_file
    from PushShoppingList.services.recipe_edit_service import upload_recipe_pdf_to_cloudflare
    from PushShoppingList.services.recipe_extract_service import mark_menu_recipe_import_failure

    payload = payload if isinstance(payload, dict) else {}
    raw_urls = payload.get("recipe_urls") or payload.get("urls")
    if isinstance(raw_urls, str):
        raw_urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not isinstance(raw_urls, list):
        raw_urls = [payload.get("recipe_url") or payload.get("url") or payload.get("source_url") or ""]
    recipe_urls = [str(url or "").strip() for url in raw_urls if str(url or "").strip()]
    recipe_urls = list(dict.fromkeys(recipe_urls))
    if not recipe_urls:
        return fail_job(job_id, "At least one recipe URL is required.")

    total = len(recipe_urls)
    force_reprocess = payload_bool(payload, "force_reprocess", False)
    run_nutrition = payload_bool(payload, "run_nutrition", True)
    run_categories = payload_bool(payload, "run_categories", True)
    run_generated_pdfs = menu_generated_pdfs_enabled(payload, total)
    job_record = get_job(job_id) or {}
    job_queue_name = str(job_record.get("queue_name") or "ai-pantry-light").strip() or "ai-pantry-light"
    nutrition_model_info = stored_job_model_metadata(
        job_id,
        active_model_metadata(
            "OPENAI_NUTRITION_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        ),
    )
    category_model_info = active_model_metadata(
        "OPENAI_RECIPE_CATEGORY_MODEL",
        MODEL,
        "fallback:OPENAI_RECIPE_MODEL",
    )
    category_payload = {
        "category_model_used": category_model_info.get("model_used", ""),
        "category_model_source": category_model_info.get("model_source", ""),
        "category_model_env_var": category_model_info.get("model_env_var_used", ""),
    }
    followup_progress_every = menu_followup_progress_update_every()
    nutrition_worker_count = menu_nutrition_worker_count(total)
    category_worker_count = menu_category_worker_count(total)
    nutrition_completed = 0
    nutrition_failed = 0
    categories_completed = 0
    categories_failed = 0
    pdfs_completed = 0
    uploads_completed = 0
    failed_items = 0
    nutrition_statuses = []
    category_statuses = []
    failed_recipe_items = []
    nutrition_ready_urls = []
    category_ready_urls = []
    pdf_ready_urls = []

    def record_failed_recipe_item(recipe_url, recipe_name="", stage="", error=""):
        recipe_url = str(recipe_url or "").strip()
        if not recipe_url:
            return
        item = {
            "recipe_url": recipe_url,
            "recipe_name": str(recipe_name or "").strip(),
            "stage": str(stage or "").strip(),
            "error": str(error or "").strip(),
        }
        failed_recipe_items.append(item)
        try:
            mark_menu_recipe_import_failure(recipe_url, item["recipe_name"], item["stage"], item["error"])
        except Exception as exc:
            print(
                "[MenuDeferredEnrichment] action=failed_item_flag_save_failed "
                f"job_id={job_id} recipe_url={recipe_url} error={exc}"
            )

    base_payload = {
        **nutrition_model_info,
        **category_payload,
        "total_items": total,
        "nutrition_completed": 0,
        "nutrition_failed": 0,
        "categories_completed": 0,
        "categories_failed": 0,
        "pdfs_completed": 0,
        "pdf_uploads_completed": 0,
        "failed_items": 0,
        "failed_recipe_items": failed_recipe_items,
        "run_nutrition": bool(run_nutrition),
        "run_categories": bool(run_categories),
        "run_generated_pdfs": bool(run_generated_pdfs),
    }
    update_job_progress(
        job_id,
        current_step="Estimating nutrition" if run_nutrition else "Preparing menu enrichment",
        total_items=total,
        progress_percent=5,
        result_payload={
            **base_payload,
            "stage": "Estimating nutrition" if run_nutrition else "Preparing menu enrichment",
        },
    )
    print(
        "[MenuDeferredEnrichment] action=start "
        f"job_id={job_id} total_items={total} run_nutrition={bool(run_nutrition)} "
        f"run_categories={bool(run_categories)} run_generated_pdfs={bool(run_generated_pdfs)}"
    )

    def run_nutrition_for_recipe(index, recipe_url):
        recipe_name = cookbook_recipe_display_name(recipe_url)
        with job_context(
            job_id=job_id,
            queue_name=job_queue_name,
            worker_id=(get_job(job_id) or {}).get("worker_id") or "",
        ):
            print(
                "[MenuDeferredEnrichment] action=nutrition_start "
                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name}"
            )
            try:
                status = ensure_menu_recipe_serving_basis_estimate(recipe_url, {})
            except Exception as exc:
                status = {
                    "ok": False,
                    "recipe_url": recipe_url,
                    "error": str(exc) or "Unable to estimate serving basis.",
                }
        status = status if isinstance(status, dict) else {
            "ok": False,
            "recipe_url": recipe_url,
            "error": "Invalid serving basis result.",
        }
        return {
            "index": index,
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
            "status": status,
        }

    if run_nutrition:
        print(
            "[MenuDeferredEnrichment] action=nutrition_parallel_start "
            f"job_id={job_id} total_items={total} worker_count={nutrition_worker_count}"
        )
        nutrition_seen = 0
        nutrition_futures = {}
        with ThreadPoolExecutor(
            max_workers=nutrition_worker_count,
            thread_name_prefix="menu-deferred-nutrition",
        ) as executor:
            try:
                for index, recipe_url in enumerate(recipe_urls):
                    nutrition_task = copy_current_request_context_if_available(
                        lambda index=index, recipe_url=recipe_url: run_nutrition_for_recipe(index, recipe_url)
                    )
                    nutrition_futures[executor.submit(nutrition_task)] = (index, recipe_url)
                while nutrition_futures:
                    ensure_not_cancelled(job_id)
                    done, _pending = wait(
                        list(nutrition_futures.keys()),
                        timeout=0.5,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        index, recipe_url = nutrition_futures.pop(future)
                        recipe_name = cookbook_recipe_display_name(recipe_url)
                        try:
                            worker_result = future.result()
                        except Exception as exc:
                            worker_result = {
                                "index": index,
                                "recipe_url": recipe_url,
                                "recipe_name": recipe_name,
                                "status": {
                                    "ok": False,
                                    "recipe_url": recipe_url,
                                    "error": str(exc) or "Unable to estimate serving basis.",
                                },
                            }
                        nutrition_seen += 1
                        recipe_name = worker_result.get("recipe_name") or recipe_name
                        status = worker_result.get("status") if isinstance(worker_result.get("status"), dict) else {
                            "ok": False,
                            "recipe_url": recipe_url,
                            "error": "Invalid serving basis result.",
                        }
                        nutrition_statuses.append({
                            "ok": bool(status.get("ok")),
                            "recipe_url": recipe_url,
                            "recipe_name": recipe_name,
                            "already_complete": bool(status.get("already_complete")),
                            "estimated": bool(status.get("estimated")),
                            "error": str(status.get("error") or ""),
                            "model_used": str(status.get("model_used") or nutrition_model_info.get("model_used") or ""),
                        })
                        if status.get("ok"):
                            nutrition_completed += 1
                            nutrition_ready_urls.append(recipe_url)
                            print(
                                "[MenuDeferredEnrichment] action=nutrition_ready "
                                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name} "
                                f"already_complete={bool(status.get('already_complete'))}"
                            )
                        else:
                            nutrition_failed += 1
                            failed_items += 1
                            error = status.get("error") or "Unable to estimate serving basis."
                            record_failed_recipe_item(recipe_url, recipe_name, "Nutrition", error)
                            append_job_warning(job_id, f"{recipe_name} ({recipe_url}): {error}")
                            print(
                                "[MenuDeferredEnrichment] action=nutrition_failed "
                                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name} error={error}"
                            )
                        if (
                            nutrition_seen <= 1
                            or nutrition_seen >= total
                            or nutrition_seen % followup_progress_every == 0
                        ):
                            update_job_progress(
                                job_id,
                                current_step=f"Estimating nutrition ({nutrition_seen}/{total})",
                                progress_percent=bounded_percent(nutrition_seen, total, 5, 45),
                                completed_items=nutrition_completed,
                                failed_items=failed_items,
                                result_payload={
                                    **base_payload,
                                    "stage": "Estimating nutrition",
                                    "nutrition_completed": nutrition_completed,
                                    "nutrition_failed": nutrition_failed,
                                    "failed_items": failed_items,
                                    "failed_recipe_items": failed_recipe_items,
                                    "nutrition_statuses": nutrition_statuses,
                                    "nutrition_workers": nutrition_worker_count,
                                    **cookbook_recipe_progress_payload(
                                        "nutrition",
                                        "Finished nutrition for",
                                        recipe_url,
                                        recipe_name,
                                        nutrition_seen,
                                        total,
                                        event="completed" if status.get("ok") else "failed",
                                    ),
                                },
                            )
            except JobCancelled:
                for future in list(nutrition_futures.keys()):
                    future.cancel()
                raise
    else:
        nutrition_ready_urls = list(recipe_urls)

    def run_category_for_recipe(index, recipe_url):
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        recipe = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        recipe = recipe if isinstance(recipe, dict) else {}
        recipe_name = cookbook_recipe_display_name(recipe_url, recipe)
        with job_context(
            job_id=job_id,
            queue_name=job_queue_name,
            worker_id=(get_job(job_id) or {}).get("worker_id") or "",
        ):
            print(
                "[MenuDeferredEnrichment] action=category_start "
                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name}"
            )
            if not recipe:
                status = {
                    "ok": False,
                    "recipe_url": recipe_url,
                    "error": "Recipe was not found for category decision.",
                }
            else:
                assignment = cookbook_recipe_assignment_for_url(recipe_url) or {}
                assignment = {
                    **assignment,
                    "cookbook_id": assignment.get("cookbook_id") or payload.get("cookbook_id") or "",
                    "cookbook_name": assignment.get("cookbook_name") or payload.get("cookbook_name") or "",
                }
                try:
                    status = apply_imported_recipe_category_routine(
                        recipe_url,
                        recipe,
                        assignment,
                        trigger_source="menu_deferred_enrichment:all",
                    )
                except Exception as exc:
                    status = {
                        "ok": False,
                        "recipe_url": recipe_url,
                        "error": str(exc) or "Unable to decide categories.",
                    }
        status = status if isinstance(status, dict) else {
            "ok": False,
            "recipe_url": recipe_url,
            "error": "Invalid category result.",
        }
        return {
            "index": index,
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
            "recipe": recipe,
            "status": status,
        }

    if run_categories and nutrition_ready_urls:
        update_job_progress(
            job_id,
            current_step="Nutrition complete; generating categories",
            progress_percent=47,
            completed_items=nutrition_completed,
            failed_items=failed_items,
            result_payload={
                **base_payload,
                "stage": "Generating categories",
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "failed_items": failed_items,
                "failed_recipe_items": failed_recipe_items,
            },
        )
        category_total = len(nutrition_ready_urls)
        category_worker_count = menu_category_worker_count(category_total)
        print(
            "[MenuDeferredEnrichment] action=category_parallel_start "
            f"job_id={job_id} total_items={category_total} worker_count={category_worker_count}"
        )
        category_seen = 0
        category_futures = {}
        with ThreadPoolExecutor(
            max_workers=category_worker_count,
            thread_name_prefix="menu-deferred-category",
        ) as executor:
            try:
                for index, recipe_url in enumerate(nutrition_ready_urls):
                    category_task = copy_current_request_context_if_available(
                        lambda index=index, recipe_url=recipe_url: run_category_for_recipe(index, recipe_url)
                    )
                    category_futures[executor.submit(category_task)] = (index, recipe_url)
                while category_futures:
                    ensure_not_cancelled(job_id)
                    done, _pending = wait(
                        list(category_futures.keys()),
                        timeout=0.5,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        index, recipe_url = category_futures.pop(future)
                        recipe_name = cookbook_recipe_display_name(recipe_url)
                        try:
                            worker_result = future.result()
                        except Exception as exc:
                            worker_result = {
                                "index": index,
                                "recipe_url": recipe_url,
                                "recipe_name": recipe_name,
                                "recipe": {},
                                "status": {
                                    "ok": False,
                                    "recipe_url": recipe_url,
                                    "error": str(exc) or "Unable to decide categories.",
                                },
                            }
                        category_seen += 1
                        recipe_name = worker_result.get("recipe_name") or recipe_name
                        recipe = worker_result.get("recipe") if isinstance(worker_result.get("recipe"), dict) else {}
                        status = worker_result.get("status") if isinstance(worker_result.get("status"), dict) else {
                            "ok": False,
                            "recipe_url": recipe_url,
                            "error": "Invalid category result.",
                        }
                        category_statuses.append({
                            **status,
                            "recipe_url": recipe_url,
                            "recipe_name": recipe_name,
                        })
                        if status.get("ok"):
                            categories_completed += 1
                            category_ready_urls.append(recipe_url)
                        else:
                            categories_failed += 1
                            failed_items += 1
                            error = status.get("error") or "Unable to decide categories."
                            record_failed_recipe_item(recipe_url, recipe_name, "Categories", error)
                            append_job_warning(job_id, f"{recipe_name} ({recipe_url}): {error}")
                            print(
                                "[MenuDeferredEnrichment] action=category_failed "
                                f"job_id={job_id} recipe_url={recipe_url} recipe_name={recipe_name} error={error}"
                            )
                        record_recipe_import_activity(
                            recipe_url,
                            {
                                **recipe,
                                "import_category_status": status,
                                "category_status": status,
                            },
                            "menu-deferred-enrichment",
                        )
                        if (
                            category_seen <= 1
                            or category_seen >= category_total
                            or category_seen % followup_progress_every == 0
                        ):
                            update_job_progress(
                                job_id,
                                current_step=f"Generating categories ({category_seen}/{category_total})",
                                progress_percent=bounded_percent(category_seen, category_total, 47, 72),
                                completed_items=max(nutrition_completed, categories_completed),
                                failed_items=failed_items,
                                result_payload={
                                    **base_payload,
                                    "stage": "Generating categories",
                                    "nutrition_completed": nutrition_completed,
                                    "nutrition_failed": nutrition_failed,
                                    "categories_completed": categories_completed,
                                    "categories_failed": categories_failed,
                                    "category_statuses": category_statuses,
                                    "failed_items": failed_items,
                                    "failed_recipe_items": failed_recipe_items,
                                    "category_workers": category_worker_count,
                                    **cookbook_recipe_progress_payload(
                                        "categories",
                                        "Finished category decision for",
                                        recipe_url,
                                        recipe_name,
                                        category_seen,
                                        category_total,
                                        event="completed" if status.get("ok") else "failed",
                                    ),
                                },
                            )
            except JobCancelled:
                for future in list(category_futures.keys()):
                    future.cancel()
                raise
    elif run_categories:
        update_job_progress(
            job_id,
            current_step="Categories skipped because no recipes finished nutrition",
            progress_percent=72,
            failed_items=failed_items,
            result_payload={
                **base_payload,
                "stage": "Categories skipped",
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "failed_items": failed_items,
                "failed_recipe_items": failed_recipe_items,
            },
        )
    else:
        category_ready_urls = list(nutrition_ready_urls)

    if run_generated_pdfs:
        pdf_candidate_urls = category_ready_urls if run_categories else nutrition_ready_urls
        update_job_progress(
            job_id,
            current_step="Generating PDFs",
            progress_percent=74,
            completed_items=max(nutrition_completed, categories_completed),
            failed_items=failed_items,
            result_payload={
                **base_payload,
                "stage": "Generating PDFs",
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "categories_completed": categories_completed,
                "categories_failed": categories_failed,
                "failed_items": failed_items,
                "failed_recipe_items": failed_recipe_items,
            },
        )
        pdf_total = max(1, len(pdf_candidate_urls))
        for index, recipe_url in enumerate(pdf_candidate_urls):
            ensure_not_cancelled(job_id)
            recipe_name = cookbook_recipe_display_name(recipe_url)
            try:
                with workspace_write_lock("recipe-pdfs"):
                    pdf_result = generate_editable_recipe_pdf_file(recipe_url)
            except Exception as exc:
                pdf_result = {"ok": False, "error": str(exc)}
            if pdf_result.get("ok"):
                pdfs_completed += 1
                pdf_ready_urls.append(recipe_url)
            else:
                failed_items += 1
                error = pdf_result.get("error") or "Unable to create recipe PDF."
                record_failed_recipe_item(recipe_url, recipe_name, "Generated PDF", error)
                append_job_warning(job_id, f"{recipe_url}: {error}")
            if index == 0 or index + 1 >= len(pdf_candidate_urls) or (index + 1) % followup_progress_every == 0:
                update_job_progress(
                    job_id,
                    current_step=f"Generating PDFs ({index + 1}/{len(pdf_candidate_urls)})",
                    progress_percent=bounded_percent(index + 1, pdf_total, 74, 88),
                    completed_items=pdfs_completed,
                    failed_items=failed_items,
                    result_payload={
                        **base_payload,
                        "stage": "Generating PDFs",
                        "nutrition_completed": nutrition_completed,
                        "categories_completed": categories_completed,
                        "pdfs_completed": pdfs_completed,
                        "failed_items": failed_items,
                        "failed_recipe_items": failed_recipe_items,
                    },
                )

        upload_total = max(1, len(pdf_ready_urls))
        for index, recipe_url in enumerate(pdf_ready_urls):
            ensure_not_cancelled(job_id)
            try:
                with workspace_write_lock("recipe-pdfs"):
                    upload_result = upload_recipe_pdf_to_cloudflare(recipe_url, pdf_kind="generated_recipe")
            except Exception as exc:
                upload_result = {"ok": False, "error": str(exc)}
            if upload_result.get("ok"):
                uploads_completed += 1
            else:
                failed_items += 1
                recipe_name = cookbook_recipe_display_name(recipe_url)
                error = upload_result.get("error") or "Unable to upload generated PDF."
                record_failed_recipe_item(recipe_url, recipe_name, "Generated PDF Upload", error)
                append_job_warning(job_id, f"{recipe_url}: {error}")
            if index == 0 or index + 1 >= len(pdf_ready_urls) or (index + 1) % followup_progress_every == 0:
                update_job_progress(
                    job_id,
                    current_step=f"Uploading PDFs ({index + 1}/{len(pdf_ready_urls)})",
                    progress_percent=bounded_percent(index + 1, upload_total, 89, 96),
                    completed_items=uploads_completed,
                    failed_items=failed_items,
                    result_payload={
                        **base_payload,
                        "stage": "Uploading PDFs",
                        "nutrition_completed": nutrition_completed,
                        "categories_completed": categories_completed,
                        "pdfs_completed": pdfs_completed,
                        "pdf_uploads_completed": uploads_completed,
                        "failed_items": failed_items,
                        "failed_recipe_items": failed_recipe_items,
                    },
                )

    result_payload = {
        **nutrition_model_info,
        **category_payload,
        "ok": bool(nutrition_completed or categories_completed or pdfs_completed or uploads_completed or not (run_nutrition or run_categories or run_generated_pdfs)),
        "created_count": total,
        "recipe_urls": recipe_urls,
        "links": recipe_links(recipe_urls),
        "nutrition_estimates_completed": nutrition_completed,
        "nutrition_completed": nutrition_completed,
        "nutrition_failed": nutrition_failed,
        "nutrition_statuses": nutrition_statuses,
        "categories_generated": categories_completed,
        "categories_completed": categories_completed,
        "categories_failed": categories_failed,
        "category_statuses": category_statuses,
        "pdfs_created": pdfs_completed,
        "pdfs_completed": pdfs_completed,
        "pdf_uploads_completed": uploads_completed,
        "failed_count": failed_items,
        "failed_items": failed_items,
        "failed_recipe_items": failed_recipe_items,
        "run_nutrition": bool(run_nutrition),
        "run_categories": bool(run_categories),
        "run_generated_pdfs": bool(run_generated_pdfs),
        "stage": "Complete",
        **clear_cookbook_recipe_progress_payload(),
    }
    update_job_progress(
        job_id,
        current_step="Complete",
        progress_percent=98,
        total_items=total,
        completed_items=max(nutrition_completed, categories_completed, pdfs_completed, uploads_completed),
        failed_items=failed_items,
        result_payload=result_payload,
    )
    print(
        "[MenuDeferredEnrichment] action=complete "
        f"job_id={job_id} total_items={total} nutrition_completed={nutrition_completed} "
        f"categories_completed={categories_completed} pdfs_completed={pdfs_completed} failed_items={failed_items}"
    )
    if result_payload["ok"]:
        return complete_job(job_id, result_payload=result_payload)
    return fail_job(job_id, "No deferred menu enrichment completed.", result_payload=result_payload)


def run_menu_deferred_heavy_tasks_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import MODEL
    from PushShoppingList.routes.recipe_routes import _has_per_serving_estimate
    from PushShoppingList.routes.recipe_routes import _menu_nutrition_inference_from_rows
    from PushShoppingList.routes.recipe_routes import estimate_recipe_nutrition
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import save_editable_recipe
    from PushShoppingList.services.recipe_edit_service import generate_editable_recipe_pdf_file
    from PushShoppingList.services.recipe_edit_service import upload_recipe_pdf_to_cloudflare
    import os

    payload = payload if isinstance(payload, dict) else {}
    raw_urls = payload.get("recipe_urls") or payload.get("urls")
    if isinstance(raw_urls, str):
        raw_urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not isinstance(raw_urls, list):
        raw_urls = [payload.get("recipe_url") or payload.get("url") or payload.get("source_url") or ""]
    recipe_urls = [str(url or "").strip() for url in raw_urls if str(url or "").strip()]
    recipe_urls = list(dict.fromkeys(recipe_urls))
    if not recipe_urls:
        return fail_job(job_id, "At least one recipe URL is required.")

    total = len(recipe_urls)
    force_reprocess = payload_bool(payload, "force_reprocess", False)
    nutrition_model_info = stored_job_model_metadata(
        job_id,
        active_model_metadata(
            "OPENAI_NUTRITION_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        ),
    )
    nutrition_model = nutrition_model_info.get("model_used") or MODEL
    nutrition_completed = 0
    pdfs_completed = 0
    uploads_completed = 0
    failed_items = 0
    nutrition_ready_urls = []
    pdf_ready_urls = []

    update_job_progress(
        job_id,
        current_step="Estimating nutrition",
        total_items=total,
        progress_percent=5,
        result_payload={
            **nutrition_model_info,
            "stage": "Estimating nutrition",
            "total_items": total,
            "nutrition_completed": 0,
            "pdfs_completed": 0,
            "pdf_uploads_completed": 0,
            "failed_items": 0,
        },
    )

    for index, recipe_url in enumerate(recipe_urls):
        ensure_not_cancelled(job_id)
        recipe_name = cookbook_recipe_display_name(recipe_url)
        update_job_progress(
            job_id,
            current_step=f"Loading recipe for nutrition ({index + 1}/{total})",
            progress_percent=bounded_percent(index, total, 5, 38),
            completed_items=nutrition_completed,
            failed_items=failed_items,
            result_payload={
                **nutrition_model_info,
                "stage": "Estimating nutrition",
                "total_items": total,
                "nutrition_completed": nutrition_completed,
                "failed_items": failed_items,
                **cookbook_recipe_progress_payload(
                    "nutrition",
                    "Loading recipe for nutrition",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    total,
                    event="started",
                ),
            },
        )
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        recipe = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        recipe = recipe if isinstance(recipe, dict) else {}
        recipe_name = cookbook_recipe_display_name(recipe_url, recipe)
        if not recipe:
            failed_items += 1
            append_job_warning(job_id, f"{recipe_url}: Recipe was not found for nutrition estimation.")
            continue

        if not force_reprocess and _has_per_serving_estimate(recipe.get("nutrition")):
            nutrition_completed += 1
            nutrition_ready_urls.append(recipe_url)
        else:
            estimate_result = estimate_recipe_nutrition(recipe)
            if not estimate_result.get("ok"):
                failed_items += 1
                append_job_warning(job_id, f"{recipe_url}: {estimate_result.get('error') or 'Unable to estimate nutrition.'}")
                continue

            updated_recipe = {
                **recipe,
                "nutrition": estimate_result.get("nutrition", []),
                "nutrition_inference": _menu_nutrition_inference_from_rows(
                    estimate_result.get("nutrition", []),
                    model=nutrition_model,
                ),
            }
            with workspace_write_lock("recipe-imports"):
                save_result = save_editable_recipe(recipe_url, updated_recipe)
            if not save_result.get("ok"):
                failed_items += 1
                append_job_warning(job_id, f"{recipe_url}: {save_result.get('error') or 'Unable to save nutrition estimate.'}")
                continue
            nutrition_completed += 1
            nutrition_ready_urls.append(recipe_url)

        update_job_progress(
            job_id,
            current_step=f"Estimating nutrition ({index + 1}/{total})",
            progress_percent=bounded_percent(index + 1, total, 5, 38),
            completed_items=nutrition_completed,
            failed_items=failed_items,
            result_payload={
                **nutrition_model_info,
                "stage": "Estimating nutrition",
                "total_items": total,
                "nutrition_completed": nutrition_completed,
                "failed_items": failed_items,
                **cookbook_recipe_progress_payload(
                    "nutrition",
                    "Finished nutrition for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    total,
                    event="completed",
                ),
            },
        )

    update_job_progress(
        job_id,
        current_step="Generating PDFs",
        progress_percent=40,
        completed_items=nutrition_completed,
        failed_items=failed_items,
        result_payload={
            **nutrition_model_info,
            "stage": "Generating PDFs",
            "nutrition_completed": nutrition_completed,
            "pdfs_completed": 0,
            "failed_items": failed_items,
        },
    )

    pdf_total = max(1, len(nutrition_ready_urls))
    for index, recipe_url in enumerate(nutrition_ready_urls):
        ensure_not_cancelled(job_id)
        recipe_name = cookbook_recipe_display_name(recipe_url)
        update_job_progress(
            job_id,
            current_step=f"Loading recipe fields for PDF ({index + 1}/{len(nutrition_ready_urls)})",
            progress_percent=bounded_percent(index, pdf_total, 40, 70),
            completed_items=pdfs_completed,
            failed_items=failed_items,
            result_payload={
                **nutrition_model_info,
                "stage": "Generating PDFs",
                "total_items": total,
                "nutrition_completed": nutrition_completed,
                "pdfs_completed": pdfs_completed,
                "failed_items": failed_items,
                **cookbook_recipe_progress_payload(
                    "pdf",
                    "Loading recipe fields for PDF",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    len(nutrition_ready_urls),
                    event="started",
                ),
            },
        )
        try:
            with workspace_write_lock("recipe-pdfs"):
                pdf_result = generate_editable_recipe_pdf_file(recipe_url)
        except Exception as exc:
            pdf_result = {"ok": False, "error": str(exc)}
        if pdf_result.get("ok"):
            pdfs_completed += 1
            pdf_ready_urls.append(recipe_url)
        else:
            failed_items += 1
            append_job_warning(job_id, f"{recipe_url}: {pdf_result.get('error') or 'Unable to create recipe PDF.'}")

        update_job_progress(
            job_id,
            current_step=f"Generating PDFs ({index + 1}/{len(nutrition_ready_urls)})",
            progress_percent=bounded_percent(index + 1, pdf_total, 40, 70),
            completed_items=pdfs_completed,
            failed_items=failed_items,
            result_payload={
                **nutrition_model_info,
                "stage": "Generating PDFs",
                "total_items": total,
                "nutrition_completed": nutrition_completed,
                "pdfs_completed": pdfs_completed,
                "failed_items": failed_items,
                **cookbook_recipe_progress_payload(
                    "pdf",
                    "Finished PDF for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    len(nutrition_ready_urls),
                    event="completed",
                ),
            },
        )

    update_job_progress(
        job_id,
        current_step="Uploading PDFs",
        progress_percent=72,
        completed_items=pdfs_completed,
        failed_items=failed_items,
        result_payload={
            **nutrition_model_info,
            "stage": "Uploading PDFs",
            "nutrition_completed": nutrition_completed,
            "pdfs_completed": pdfs_completed,
            "pdf_uploads_completed": 0,
            "failed_items": failed_items,
        },
    )

    upload_total = max(1, len(pdf_ready_urls))
    for index, recipe_url in enumerate(pdf_ready_urls):
        ensure_not_cancelled(job_id)
        recipe_name = cookbook_recipe_display_name(recipe_url)
        update_job_progress(
            job_id,
            current_step=f"Uploading PDF for {recipe_name} ({index + 1}/{len(pdf_ready_urls)})",
            progress_percent=bounded_percent(index, upload_total, 72, 96),
            completed_items=uploads_completed,
            failed_items=failed_items,
            result_payload={
                **nutrition_model_info,
                "stage": "Uploading PDFs",
                "total_items": total,
                "nutrition_completed": nutrition_completed,
                "pdfs_completed": pdfs_completed,
                "pdf_uploads_completed": uploads_completed,
                "failed_items": failed_items,
                **cookbook_recipe_progress_payload(
                    "upload",
                    "Uploading PDF for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    len(pdf_ready_urls),
                    event="started",
                ),
            },
        )
        try:
            with workspace_write_lock("recipe-pdfs"):
                upload_result = upload_recipe_pdf_to_cloudflare(recipe_url, pdf_kind="generated_recipe")
        except Exception as exc:
            upload_result = {"ok": False, "error": str(exc)}
        if upload_result.get("ok"):
            uploads_completed += 1
        else:
            failed_items += 1
            append_job_warning(job_id, f"{recipe_url}: {upload_result.get('error') or 'Unable to upload generated PDF.'}")

        update_job_progress(
            job_id,
            current_step=f"Uploading PDFs ({index + 1}/{len(pdf_ready_urls)})",
            progress_percent=bounded_percent(index + 1, upload_total, 72, 96),
            completed_items=uploads_completed,
            failed_items=failed_items,
            result_payload={
                **nutrition_model_info,
                "stage": "Uploading PDFs",
                "total_items": total,
                "nutrition_completed": nutrition_completed,
                "pdfs_completed": pdfs_completed,
                "pdf_uploads_completed": uploads_completed,
                "failed_items": failed_items,
                **cookbook_recipe_progress_payload(
                    "upload",
                    "Finished PDF upload for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    len(pdf_ready_urls),
                    event="completed",
                ),
            },
        )

    result_payload = {
        "ok": uploads_completed > 0 or pdfs_completed > 0 or nutrition_completed > 0,
        "created_count": total,
        "recipe_urls": recipe_urls,
        "links": recipe_links(recipe_urls),
        "nutrition_estimates_completed": nutrition_completed,
        "nutrition_completed": nutrition_completed,
        "pdfs_created": pdfs_completed,
        "pdfs_completed": pdfs_completed,
        "pdf_uploads_completed": uploads_completed,
        "failed_count": failed_items,
        "failed_items": failed_items,
        "stage": "Complete",
        **nutrition_model_info,
    }
    update_job_progress(
        job_id,
        current_step="Complete",
        progress_percent=98,
        total_items=total,
        completed_items=max(nutrition_completed, pdfs_completed, uploads_completed),
        failed_items=failed_items,
        result_payload=result_payload,
    )
    if result_payload["ok"]:
        return complete_job(job_id, result_payload=result_payload)
    return fail_job(job_id, "No deferred menu tasks completed.", result_payload=result_payload)


def cookbook_infer_urls_from_payload(payload, cookbook):
    raw_urls = (payload if isinstance(payload, dict) else {}).get("recipe_urls")
    if isinstance(raw_urls, str):
        raw_urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not isinstance(raw_urls, list):
        raw_urls = []

    urls = [str(url or "").strip() for url in raw_urls if str(url or "").strip()]
    if not urls:
        urls = [
            str(recipe.get("url") or "").strip()
            for recipe in (cookbook.get("recipes", []) if isinstance(cookbook, dict) else [])
            if isinstance(recipe, dict) and str(recipe.get("url") or "").strip()
        ]
    return list(dict.fromkeys(urls))


def cookbook_recipe_names_by_url(cookbook):
    recipes = cookbook.get("recipes", []) if isinstance(cookbook, dict) else []
    names = {}
    for recipe in recipes:
        if not isinstance(recipe, dict):
            continue
        url = str(recipe.get("url") or "").strip()
        if not url:
            continue
        name = str(
            recipe.get("name")
            or recipe.get("display_name")
            or recipe.get("recipe_title")
            or recipe.get("menu_item_name")
            or ""
        ).strip()
        if name:
            names[url] = name
    return names


def cookbook_recipe_display_name(recipe_url, recipe=None, recipe_names=None):
    recipe = recipe if isinstance(recipe, dict) else {}
    recipe_names = recipe_names if isinstance(recipe_names, dict) else {}
    for value in (
        recipe.get("display_name"),
        recipe.get("recipe_title"),
        recipe.get("menu_item_name"),
        recipe.get("name"),
        recipe_names.get(recipe_url),
        menu_item_label_from_url(recipe_url),
        recipe_url,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "this recipe"


def cookbook_recipe_progress_payload(stage, action, recipe_url, recipe_name, index, total, event="running"):
    index = max(0, int(index or 0))
    total = max(0, int(total or 0))
    label = str(recipe_name or recipe_url or "this recipe").strip()
    if index and total:
        detail = f"{action} recipe {index} of {total}: {label}"
    else:
        detail = f"{action}: {label}"
    return {
        "current_recipe_stage": str(stage or "").strip(),
        "current_recipe_event": str(event or "").strip(),
        "current_recipe_index": index,
        "current_recipe_total": total,
        "current_recipe_name": label,
        "current_recipe_url": str(recipe_url or "").strip(),
        "current_recipe_action": str(action or "").strip(),
        "current_recipe_detail": detail,
    }


def clear_cookbook_recipe_progress_payload():
    return {
        "current_recipe_stage": "",
        "current_recipe_event": "",
        "current_recipe_index": 0,
        "current_recipe_total": 0,
        "current_recipe_name": "",
        "current_recipe_url": "",
        "current_recipe_action": "",
        "current_recipe_detail": "",
    }


def run_cookbook_infer_missing_details_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import MODEL
    from PushShoppingList.routes.recipe_routes import _has_per_serving_estimate
    from PushShoppingList.routes.recipe_routes import _menu_nutrition_inference_from_rows
    from PushShoppingList.routes.recipe_routes import apply_imported_recipe_category_routine
    from PushShoppingList.routes.recipe_routes import estimate_recipe_nutrition
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import save_editable_recipe
    from PushShoppingList.services import cookbook_service
    from PushShoppingList.services.cookbook_item_inference_service import COOKBOOK_ITEM_MODEL_ENV_VAR
    from PushShoppingList.services.cookbook_item_inference_service import infer_missing_details_for_cookbook
    from PushShoppingList.services.cookbook_item_inference_service import recipe_context_from_cookbook
    from PushShoppingList.services.cookbook_item_inference_service import resolve_cookbook_item_model

    payload = payload if isinstance(payload, dict) else {}
    cookbook_id = str(payload.get("cookbook_id") or "").strip()
    if not cookbook_id:
        return fail_job(job_id, "Cookbook is required.")

    overwrite_ai_fields = payload_bool(payload, "overwrite_ai_fields", False)
    preview_only = payload_bool(payload, "preview_only", False)
    try:
        cookbook = recipe_context_from_cookbook(cookbook_id)
    except ValueError as exc:
        return fail_job(job_id, str(exc) or "Cookbook was not found.")

    cookbook_name = str(payload.get("cookbook_name") or cookbook.get("name") or cookbook_id).strip()
    recipe_urls = cookbook_infer_urls_from_payload(payload, cookbook)
    payload_recipe_names = payload.get("recipe_names") if isinstance(payload.get("recipe_names"), dict) else {}
    recipe_names = {
        **cookbook_recipe_names_by_url(cookbook),
        **{str(key or "").strip(): str(value or "").strip() for key, value in payload_recipe_names.items() if str(key or "").strip() and str(value or "").strip()},
    }
    total = len(recipe_urls)
    if not recipe_urls:
        result_payload = {
            "ok": True,
            "cookbook_id": cookbook_id,
            "cookbook_name": cookbook_name,
            "total_items": 0,
            "total_found": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "stage": "Complete",
            "summary_message": f"{cookbook_name}: no recipes found.",
        }
        return complete_job(job_id, result_payload=result_payload)

    cookbook_model, cookbook_model_source = resolve_cookbook_item_model()
    cookbook_model_info = stored_job_model_metadata(
        job_id,
        model_metadata(cookbook_model, cookbook_model_source, COOKBOOK_ITEM_MODEL_ENV_VAR),
    )
    nutrition_model_info = active_model_metadata(
        "OPENAI_NUTRITION_MODEL",
        MODEL,
        "fallback:OPENAI_RECIPE_MODEL",
    )
    nutrition_model = nutrition_model_info.get("model_used") or MODEL

    base_payload = {
        **cookbook_model_info,
        "cookbook_id": cookbook_id,
        "cookbook_name": cookbook_name,
        "total_items": total,
        "stage": "Inferring missing details",
        "details_completed": 0,
        "nutrition_completed": 0,
        "categories_completed": 0,
        "failed_items": 0,
        **clear_cookbook_recipe_progress_payload(),
    }
    update_job_progress(
        job_id,
        current_step=f"Inferring missing details for {cookbook_name}",
        total_items=total,
        progress_percent=5,
        result_payload=base_payload,
    )

    def update_inference_recipe_progress(event):
        event = event if isinstance(event, dict) else {}
        recipe_url = str(event.get("recipe_url") or "").strip()
        recipe_name = cookbook_recipe_display_name(
            recipe_url,
            {"name": event.get("recipe_name")},
            recipe_names,
        )
        item_index = int(event.get("index") or 0)
        completed = int(event.get("completed") or 0)
        item_total = int(event.get("total") or total or 0)
        event_name = str(event.get("event") or "").strip().lower()
        is_completed = event_name == "completed"
        action = "Finished inferring details for" if is_completed else "Inferring details for"
        current_step = f"{action} {recipe_name}"
        if item_index and item_total:
            current_step = f"{current_step} ({item_index}/{item_total})"
        progress_index = completed if is_completed else max(0, item_index - 1)
        update_job_progress(
            job_id,
            current_step=current_step,
            progress_percent=bounded_percent(progress_index, item_total or total, 6, 34),
            completed_items=completed if completed else None,
            failed_items=None,
            result_payload={
                "stage": "Inferring missing details",
                "cookbook_id": cookbook_id,
                "cookbook_name": cookbook_name,
                "total_items": total,
                "details_completed": completed,
                **cookbook_recipe_progress_payload(
                    "details",
                    action,
                    recipe_url,
                    recipe_name,
                    item_index,
                    item_total,
                    event=event_name or "running",
                ),
            },
        )

    inference_result = infer_missing_details_for_cookbook(
        cookbook_id,
        overwrite_ai_fields=overwrite_ai_fields,
        preview_only=preview_only,
        progress_callback=update_inference_recipe_progress,
    )
    inference_failed = int(inference_result.get("failed") or 0)
    details_completed = int(inference_result.get("updated") or 0) + int(inference_result.get("skipped") or 0)

    if not inference_result.get("ok"):
        result_payload = {
            **base_payload,
            **inference_result,
            "ok": False,
            "stage": "Failed",
            "failed_items": inference_failed or total,
            "summary_message": inference_result.get("error") or "Unable to infer cookbook details.",
        }
        return fail_job(job_id, result_payload["summary_message"], result_payload=result_payload)

    update_job_progress(
        job_id,
        current_step="Missing details complete" if preview_only else "Estimating per serving basis",
        progress_percent=35 if not preview_only else 95,
        completed_items=details_completed,
        failed_items=inference_failed,
        result_payload={
            **base_payload,
            **inference_result,
            "stage": "Preview complete" if preview_only else "Estimating per serving basis",
            "details_completed": details_completed,
            "failed_items": inference_failed,
            "inference_result": inference_result,
        },
    )

    if preview_only:
        result_payload = {
            **base_payload,
            **inference_result,
            "ok": True,
            "stage": "Complete",
            "details_completed": details_completed,
            "failed_items": inference_failed,
            "summary_message": (
                f"Preview complete for {cookbook_name}: "
                f"{inference_result.get('updated', 0)} would update, "
                f"{inference_result.get('skipped', 0)} skipped, "
                f"{inference_result.get('failed', 0)} failed."
            ),
            "links": recipe_links(recipe_urls),
        }
        return complete_job(job_id, result_payload=result_payload)

    failed_items = inference_failed
    nutrition_completed = 0
    nutrition_failed = 0
    category_completed = 0
    category_failed = 0
    category_statuses = []

    for index, recipe_url in enumerate(recipe_urls):
        ensure_not_cancelled(job_id)
        recipe_name = cookbook_recipe_display_name(recipe_url, recipe_names=recipe_names)
        update_job_progress(
            job_id,
            current_step=f"Estimating per serving basis for {recipe_name} ({index + 1}/{total})",
            progress_percent=bounded_percent(index, total, 36, 62),
            completed_items=max(details_completed, nutrition_completed),
            failed_items=failed_items,
            result_payload={
                **cookbook_model_info,
                "stage": "Estimating per serving basis",
                "cookbook_id": cookbook_id,
                "cookbook_name": cookbook_name,
                "total_items": total,
                "details_completed": details_completed,
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "categories_completed": 0,
                "failed_items": failed_items,
                "inference_result": inference_result,
                "nutrition_model_used": nutrition_model_info.get("model_used", ""),
                "nutrition_model_source": nutrition_model_info.get("model_source", ""),
                "nutrition_model_env_var": nutrition_model_info.get("model_env_var", ""),
                **cookbook_recipe_progress_payload(
                    "nutrition",
                    "Estimating nutrition for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    total,
                    event="started",
                ),
            },
        )
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        recipe = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        recipe = recipe if isinstance(recipe, dict) else {}
        recipe_name = cookbook_recipe_display_name(recipe_url, recipe, recipe_names)
        if not recipe:
            failed_items += 1
            nutrition_failed += 1
            append_job_warning(job_id, f"{recipe_url}: Recipe was not found for serving basis estimation.")
        elif _has_per_serving_estimate(recipe.get("nutrition")):
            nutrition_completed += 1
        else:
            estimate_result = estimate_recipe_nutrition(recipe)
            if not estimate_result.get("ok"):
                failed_items += 1
                nutrition_failed += 1
                append_job_warning(job_id, f"{recipe_url}: {estimate_result.get('error') or 'Unable to estimate serving basis.'}")
            else:
                updated_recipe = {
                    **recipe,
                    "nutrition": estimate_result.get("nutrition", []),
                    "nutrition_inference": _menu_nutrition_inference_from_rows(
                        estimate_result.get("nutrition", []),
                        model=nutrition_model,
                    ),
                }
                with workspace_write_lock("recipe-imports"):
                    save_result = save_editable_recipe(recipe_url, updated_recipe)
                if not save_result.get("ok"):
                    failed_items += 1
                    nutrition_failed += 1
                    append_job_warning(job_id, f"{recipe_url}: {save_result.get('error') or 'Unable to save serving basis estimate.'}")
                else:
                    nutrition_completed += 1

        update_job_progress(
            job_id,
            current_step=f"Estimating per serving basis ({index + 1}/{total})",
            progress_percent=bounded_percent(index + 1, total, 36, 62),
            completed_items=max(details_completed, nutrition_completed),
            failed_items=failed_items,
            result_payload={
                **cookbook_model_info,
                "stage": "Estimating per serving basis",
                "cookbook_id": cookbook_id,
                "cookbook_name": cookbook_name,
                "total_items": total,
                "details_completed": details_completed,
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "categories_completed": 0,
                "failed_items": failed_items,
                "inference_result": inference_result,
                "nutrition_model_used": nutrition_model_info.get("model_used", ""),
                "nutrition_model_source": nutrition_model_info.get("model_source", ""),
                "nutrition_model_env_var": nutrition_model_info.get("model_env_var", ""),
                **cookbook_recipe_progress_payload(
                    "nutrition",
                    "Finished nutrition for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    total,
                    event="completed",
                ),
            },
        )

    update_job_progress(
        job_id,
        current_step="Having ChatGPT decide all categories",
        progress_percent=64,
        completed_items=max(details_completed, nutrition_completed),
        failed_items=failed_items,
        result_payload={
            **cookbook_model_info,
            "stage": "Having ChatGPT decide all categories",
            "cookbook_id": cookbook_id,
            "cookbook_name": cookbook_name,
            "total_items": total,
            "details_completed": details_completed,
            "nutrition_completed": nutrition_completed,
            "nutrition_failed": nutrition_failed,
            "categories_completed": 0,
            "failed_items": failed_items,
            "inference_result": inference_result,
        },
    )

    for index, recipe_url in enumerate(recipe_urls):
        ensure_not_cancelled(job_id)
        recipe_name = cookbook_recipe_display_name(recipe_url, recipe_names=recipe_names)
        update_job_progress(
            job_id,
            current_step=f"Having ChatGPT decide all categories for {recipe_name} ({index + 1}/{total})",
            progress_percent=bounded_percent(index, total, 65, 94),
            completed_items=max(details_completed, nutrition_completed, category_completed),
            failed_items=failed_items,
            result_payload={
                **cookbook_model_info,
                "stage": "Having ChatGPT decide all categories",
                "cookbook_id": cookbook_id,
                "cookbook_name": cookbook_name,
                "total_items": total,
                "details_completed": details_completed,
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "categories_completed": category_completed,
                "categories_failed": category_failed,
                "failed_items": failed_items,
                "inference_result": inference_result,
                **cookbook_recipe_progress_payload(
                    "categories",
                    "Deciding categories for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    total,
                    event="started",
                ),
            },
        )
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        recipe = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        recipe = recipe if isinstance(recipe, dict) else {}
        recipe_name = cookbook_recipe_display_name(recipe_url, recipe, recipe_names)
        if not recipe:
            failed_items += 1
            category_failed += 1
            status = {"ok": False, "recipe_url": recipe_url, "error": "Recipe was not found for category decision."}
            append_job_warning(job_id, f"{recipe_url}: Recipe was not found for category decision.")
        else:
            assignment = cookbook_service.cookbook_recipe_assignment_for_url(recipe_url) or {}
            assignment = {
                **assignment,
                "cookbook_id": assignment.get("cookbook_id") or cookbook_id,
                "cookbook_name": assignment.get("cookbook_name") or cookbook_name,
            }
            status = apply_imported_recipe_category_routine(
                recipe_url,
                recipe,
                assignment,
                trigger_source="cookbook_infer:all",
            )
            status = status if isinstance(status, dict) else {"ok": False, "error": "Invalid category result."}
            status["recipe_url"] = recipe_url
            if status.get("ok"):
                category_completed += 1
            else:
                failed_items += 1
                category_failed += 1
                append_job_warning(job_id, f"{recipe_url}: {status.get('error') or 'Unable to decide categories.'}")
        category_statuses.append(status)

        update_job_progress(
            job_id,
            current_step=f"Having ChatGPT decide all categories ({index + 1}/{total})",
            progress_percent=bounded_percent(index + 1, total, 65, 94),
            completed_items=max(details_completed, nutrition_completed, category_completed),
            failed_items=failed_items,
            result_payload={
                **cookbook_model_info,
                "stage": "Having ChatGPT decide all categories",
                "cookbook_id": cookbook_id,
                "cookbook_name": cookbook_name,
                "total_items": total,
                "details_completed": details_completed,
                "nutrition_completed": nutrition_completed,
                "nutrition_failed": nutrition_failed,
                "categories_completed": category_completed,
                "categories_failed": category_failed,
                "failed_items": failed_items,
                "inference_result": inference_result,
                **cookbook_recipe_progress_payload(
                    "categories",
                    "Finished category decision for",
                    recipe_url,
                    recipe_name,
                    index + 1,
                    total,
                    event="completed",
                ),
            },
        )

    result_payload = {
        **cookbook_model_info,
        **inference_result,
        "ok": bool(inference_result.get("ok")),
        "cookbook_id": cookbook_id,
        "cookbook_name": cookbook_name,
        "recipe_urls": recipe_urls,
        "links": recipe_links(recipe_urls),
        "stage": "Complete",
        "total_items": total,
        "details_completed": details_completed,
        "nutrition_completed": nutrition_completed,
        "nutrition_failed": nutrition_failed,
        "categories_completed": category_completed,
        "categories_failed": category_failed,
        "failed_items": failed_items,
        "inference_result": inference_result,
        "category_statuses": category_statuses,
        **clear_cookbook_recipe_progress_payload(),
        "summary_message": (
            f"{cookbook_name}: inferred {inference_result.get('updated', 0)}, "
            f"estimated serving basis for {nutrition_completed}, "
            f"ran ChatGPT category decisions for {category_completed}, "
            f"{failed_items} failed."
        ),
    }
    update_job_progress(
        job_id,
        current_step="Complete",
        progress_percent=98,
        total_items=total,
        completed_items=max(details_completed, nutrition_completed, category_completed),
        failed_items=failed_items,
        result_payload=result_payload,
    )
    return complete_job(job_id, result_payload=result_payload)


def run_import_urls_job(job_id, payload, menu_extract=False):
    from PushShoppingList.routes.recipe_routes import IMPORT_CATEGORY_STATUS_MESSAGE
    from PushShoppingList.routes.recipe_routes import NO_INGREDIENTS_ERROR
    from PushShoppingList.routes.recipe_routes import add_items
    from PushShoppingList.routes.recipe_routes import apply_imported_recipe_category_routine
    from PushShoppingList.routes.recipe_routes import commit_menu_import_result
    from PushShoppingList.routes.recipe_routes import create_source_url_pdf
    from PushShoppingList.routes.recipe_routes import extract_menu_recipes_from_url
    from PushShoppingList.routes.recipe_routes import extract_menu_stubs_from_url
    from PushShoppingList.routes.recipe_routes import extract_recipe_from_url
    from PushShoppingList.routes.recipe_routes import import_recipe_title
    from PushShoppingList.routes.recipe_routes import MODEL
    from PushShoppingList.routes.recipe_routes import record_recipe_import_activity
    from PushShoppingList.routes.recipe_routes import resolve_menu_cleanup_model
    from PushShoppingList.routes.recipe_routes import resolve_menu_cleanup_model_source
    from PushShoppingList.routes.recipe_routes import resolve_menu_model
    from PushShoppingList.routes.recipe_routes import resolve_menu_model_source
    from PushShoppingList.routes.recipe_routes import save_import_cookbook_assignment
    from PushShoppingList.routes.recipe_routes import save_ingredients_for_recipe
    from PushShoppingList.routes.recipe_routes import save_recipe_url_name
    from PushShoppingList.routes.recipe_routes import schedule_generated_recipe_pdf_creation
    from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
    from PushShoppingList.services.recipe_url_service import add_recipe_urls

    raw_urls = payload.get("urls")
    if not isinstance(raw_urls, list):
        raw_urls = [payload.get("url") or payload.get("recipe_url") or payload.get("menu_url") or ""]
    urls = [str(url or "").strip() for url in raw_urls if str(url or "").strip()]
    if not urls:
        return fail_job(job_id, "At least one URL is required.")

    total = len(urls)
    menu_import_started_at = time.perf_counter() if menu_extract else None
    menu_auto_enrich = import_menu_url_auto_enrich_enabled(payload) if menu_extract else False
    menu_create_source_pdf = import_menu_url_create_source_pdf_enabled(payload) if menu_extract else False
    menu_target_seconds = import_menu_url_target_seconds() if menu_extract else 0
    cookbook = selected_cookbook_from_payload(payload)
    created_urls = []
    failed_items = 0
    context = "job-menu-url" if menu_extract else "job-recipe-url"
    menu_job_stats = {
        "menu_mega_json_saved": False,
        "menu_mega_json_snapshots_created": 0,
        "menu_mega_snapshot_ids": [],
        "item_records_unpacked": 0,
        "stubs_created": 0,
        "duplicates_skipped": 0,
        "full_recipes_generated": 0,
        "nutrition_estimates_completed": 0,
        "pdfs_created": 0,
        "openai_calls_used": 0,
        "estimated_token_usage": {},
        "menu_sections_found": 0,
        "menu_items_found": 0,
        "menu_source_pdf_statuses": [],
        "menu_source_url": "",
        "menu_source_pdf_status": "",
        "menu_source_pdf_path": "",
        "menu_source_cloudflare_pdf_url": "",
    }
    job_model = stored_job_model_metadata(job_id, model_metadata(
        resolve_menu_cleanup_model() if menu_extract else MODEL,
        resolve_menu_cleanup_model_source() if menu_extract else "recipe",
        "OPENAI_MENU_CLEANUP_MODEL" if menu_extract else "OPENAI_RECIPE_MODEL",
    ))

    update_job_progress(
        job_id,
        current_step="Fetching menu" if menu_extract else ("Reading source URL" if total == 1 else "Reading source URLs"),
        total_items=total,
        progress_percent=5,
        result_payload={
            **job_model,
            **({
                "stage": "Fetching menu",
                "recipe_shells_created": 0,
                "recipe_inference_completed": 0,
                "nutrition_completed": 0,
                "pdfs_completed": 0,
                "failed_items": 0,
                "auto_enrich": bool(menu_auto_enrich),
                "background_enrichment_enabled": bool(menu_auto_enrich),
                "target_seconds": menu_target_seconds,
            } if menu_extract else {}),
        },
    )

    for index, url in enumerate(urls):
        ensure_not_cancelled(job_id)
        if menu_extract:
            log_import_menu_url_stage(
                "start",
                url=url,
                auto_enrich=str(bool(menu_auto_enrich)).lower(),
                target_seconds=menu_target_seconds,
                source_pdf=str(bool(menu_create_source_pdf)).lower(),
            )
        step = "Fetching menu" if menu_extract else "Reading source URL"
        update_job_progress(
            job_id,
            current_step=step,
            progress_percent=bounded_percent(index, total, 5, 35),
            completed_items=len(created_urls),
            failed_items=failed_items,
        )

        def progress_callback(message, summary=None):
            ensure_not_cancelled(job_id)
            item_completed, item_total = progress_counts(message, summary)
            progress_kwargs = {}
            if menu_extract and item_total:
                progress_kwargs = {
                    "completed_items": item_completed,
                    "total_items": item_total,
                }
            update_job_progress(
                job_id,
                current_step=str(message or summary or "Running"),
                progress_percent=bounded_percent(index, total, 15, 65),
                result_payload=job_model,
                **progress_kwargs,
            )

        try:
            if menu_extract:
                result = extract_menu_stubs_from_url(
                    url,
                    progress_callback=progress_callback,
                    cancellation_check=lambda: ensure_not_cancelled(job_id),
                    import_job_id=job_id,
                    cookbook_id=cookbook.get("id", "") if isinstance(cookbook, dict) else "",
                    cookbook_name=cookbook.get("name", "") if isinstance(cookbook, dict) else "",
                    create_source_pdf=menu_create_source_pdf,
                )
            else:
                result = extract_recipe_from_url(url, progress_callback=progress_callback)
        except JobCancelled:
            raise
        except Exception as exc:
            failed_items += 1
            append_job_warning(job_id, f"{url}: {exc}")
            continue

        ensure_not_cancelled(job_id)

        if menu_extract:
            if not result.get("ok"):
                failed_items += 1
                append_job_warning(job_id, f"{url}: {result.get('error') or 'Menu extraction failed.'}")
                continue

            update_job_progress(
                job_id,
                current_step="Saving menu items",
                progress_percent=bounded_percent(index, total, 65, 90),
                result_payload={
                    **job_model,
                    "stage": "Saving menu items",
                    "recipe_shells_created": len(created_urls),
                    "recipe_inference_completed": 0,
                    "nutrition_completed": 0,
                    "pdfs_completed": 0,
                    "failed_items": failed_items,
                },
            )
            with workspace_write_lock("recipe-imports"):
                committed = commit_menu_import_result(
                    result,
                    cookbook,
                    context=context,
                    progress_callback=progress_callback,
                )
            if committed.get("ok"):
                snapshot_id = str(
                    committed.get("menu_mega_snapshot_id")
                    or committed.get("parent_menu_snapshot_id")
                    or ""
                ).strip()
                if committed.get("menu_mega_json_saved"):
                    menu_job_stats["menu_mega_json_saved"] = True
                    menu_job_stats["menu_mega_json_snapshots_created"] += 1
                if committed.get("menu_source_pdf_status"):
                    menu_job_stats["menu_source_pdf_statuses"].append({
                        "menu_source_url": committed.get("menu_source_url", ""),
                        "status": committed.get("menu_source_pdf_status", ""),
                        "source_pdf_path": committed.get("menu_source_pdf_path", ""),
                        "source_cloudflare_pdf_url": committed.get("menu_source_cloudflare_pdf_url", ""),
                    })
                    for key in (
                        "menu_source_url",
                        "menu_source_pdf_status",
                        "menu_source_pdf_path",
                        "menu_source_cloudflare_pdf_url",
                    ):
                        if not menu_job_stats.get(key):
                            menu_job_stats[key] = committed.get(key, "")
                if snapshot_id and snapshot_id not in menu_job_stats["menu_mega_snapshot_ids"]:
                    menu_job_stats["menu_mega_snapshot_ids"].append(snapshot_id)
                for key in (
                    "item_records_unpacked",
                    "stubs_created",
                    "duplicates_skipped",
                    "full_recipes_generated",
                    "nutrition_estimates_completed",
                    "pdfs_created",
                    "openai_calls_used",
                    "menu_sections_found",
                    "menu_items_found",
                ):
                    menu_job_stats[key] += int(committed.get(key) or 0)
                usage = committed.get("estimated_token_usage") if isinstance(committed.get("estimated_token_usage"), dict) else {}
                for usage_key, usage_value in usage.items():
                    try:
                        menu_job_stats["estimated_token_usage"][usage_key] = (
                            int(menu_job_stats["estimated_token_usage"].get(usage_key) or 0)
                            + int(usage_value or 0)
                        )
                    except (TypeError, ValueError):
                        menu_job_stats["estimated_token_usage"][usage_key] = usage_value

                committed_urls = committed.get("created_urls") or committed.get("recipe_urls") or []
                if not committed_urls and isinstance(committed.get("recipes"), list):
                    committed_urls = [
                        recipe.get("source_url")
                        for recipe in committed.get("recipes")
                        if isinstance(recipe, dict)
                    ]
                if not committed_urls:
                    committed_urls = [url]
                created_urls.extend([item for item in committed_urls if item])
                if committed.get("partial_failure"):
                    failed_items += 1
                    append_job_warning(job_id, committed.get("error") or "Some menu items failed.")
                committed_count = int(committed.get("committed_count") or len(committed_urls) or 0)
                created_count = int(committed.get("created_count") or 0)
                skipped_count = int(committed.get("duplicates_skipped") or 0)
                updated_count = max(0, committed_count - created_count)
                log_import_menu_url_stage(
                    "save_basic_items",
                    created=created_count,
                    skipped=skipped_count,
                    updated=updated_count,
                    elapsed=f"{import_menu_url_elapsed_seconds(menu_import_started_at):.2f}s",
                )
            else:
                failed_items += 1
                append_job_warning(job_id, f"{url}: {committed.get('error') or 'No menu item recipes were created.'}")
                log_import_menu_url_stage(
                    "save_basic_items",
                    created=0,
                    skipped=0,
                    updated=0,
                    elapsed=f"{import_menu_url_elapsed_seconds(menu_import_started_at):.2f}s",
                )
            continue

        ingredients = result.get("ingredients", [])
        if not result.get("ok") or not ingredients:
            failed_items += 1
            append_job_warning(job_id, f"{url}: {result.get('error') or NO_INGREDIENTS_ERROR}")
            continue

        update_job_progress(
            job_id,
            current_step="Inferring ingredients",
            progress_percent=bounded_percent(index, total, 50, 70),
        )
        with workspace_write_lock("recipe-imports"):
            add_items(ingredients)
            save_ingredients_for_recipe(url, ingredients, result)
            if result.get("display_name") or result.get("recipe_title"):
                save_recipe_url_name(url, result.get("display_name") or result.get("recipe_title"))
            add_recipe_urls([url])
            assignment = save_import_cookbook_assignment(url, result, cookbook)

            update_job_progress(
                job_id,
                current_step=IMPORT_CATEGORY_STATUS_MESSAGE,
                progress_percent=bounded_percent(index, total, 70, 82),
            )
            category_status = apply_imported_recipe_category_routine(url, result, assignment)
            if not category_status.get("ok"):
                append_job_warning(job_id, f"{import_recipe_title(result, url)}: {category_status.get('error') or 'Category inference skipped.'}")

            update_job_progress(job_id, current_step="Generating recipe PDF", progress_percent=bounded_percent(index, total, 82, 92))
            create_source_url_pdf(url)
            pdf_job = schedule_generated_recipe_pdf_creation(url, context=context)
        result = {
            **result,
            "generated_recipe_pdf_job": pdf_job,
            "import_category_status": category_status,
        }
        record_recipe_import_activity(url, result, context)
        created_urls.append(url)

    ensure_not_cancelled(job_id)
    if created_urls:
        update_job_progress(job_id, current_step="Finalizing results", progress_percent=95)
        with workspace_write_lock("recipe-imports"):
            sort_ingredients()

    visible_elapsed = import_menu_url_elapsed_seconds(menu_import_started_at) if menu_extract else 0
    final_total = max(total, len(created_urls) + failed_items) if menu_extract else total
    menu_imported_count = len(created_urls)
    menu_elapsed_text = format_import_menu_url_elapsed(visible_elapsed)
    menu_enrichment_message = (
        "Recipe details are queued for background enrichment."
        if menu_auto_enrich
        else "Recipe details are ready for manual enrichment later."
    )
    result_payload = {
        "ok": bool(created_urls),
        "created_count": len(created_urls),
        "failed_count": failed_items,
        "failed_items": failed_items,
        "recipe_urls": created_urls,
        "links": recipe_links(created_urls),
        **job_model,
    }
    should_enqueue_recipe_inference = False
    if menu_extract:
        should_enqueue_recipe_inference = bool(created_urls and menu_auto_enrich)
        result_payload.update(menu_job_stats)
        result_payload.update({
            "stage": "Import complete",
            "basic_import_complete": True,
            "basic_import_status": "imported_basic",
            "auto_enrich": bool(menu_auto_enrich),
            "background_enrichment_enabled": bool(menu_auto_enrich),
            "background_enrichment_status": "queue_pending" if should_enqueue_recipe_inference else "not_started",
            "target_seconds": menu_target_seconds,
            "import_duration_seconds": round(visible_elapsed, 2),
            "target_seconds_exceeded": bool(visible_elapsed > menu_target_seconds),
            "recipe_shells_created": len(created_urls),
            "recipe_inference_completed": 0,
            "nutrition_completed": 0,
            "pdfs_completed": 0,
            "recipe_inference_job": {},
            "recipe_inference_job_id": "",
            "summary_message": (
                f"Imported {menu_imported_count} menu item"
                f"{'' if menu_imported_count == 1 else 's'} in {menu_elapsed_text}. "
                f"{menu_enrichment_message}"
            ),
        })
    update_job_progress(
        job_id,
        total_items=final_total,
        completed_items=len(created_urls),
        failed_items=failed_items,
        result_payload=result_payload,
    )

    if not created_urls:
        return fail_job(job_id, "No recipes were imported.", result_payload=result_payload)

    if menu_extract and visible_elapsed > menu_target_seconds:
        warning = (
            f"Import Menu URL exceeded target: {visible_elapsed:.2f}s "
            f"> {menu_target_seconds}s."
        )
        append_job_warning(job_id, warning)
        log_import_menu_url_stage(
            "warning",
            total_elapsed=f"{visible_elapsed:.2f}s",
            target_seconds=menu_target_seconds,
        )

    completed_job = complete_job(
        job_id,
        result_payload=result_payload,
        current_step="Import complete" if menu_extract else "Completed",
    )
    if menu_extract:
        log_import_menu_url_stage(
            "complete",
            total_elapsed=f"{visible_elapsed:.2f}s",
            auto_enrich=str(bool(menu_auto_enrich)).lower(),
        )
    if should_enqueue_recipe_inference:
        try:
            inference_job = enqueue_followup_job(
                "menu-generate-recipes",
                {
                    "recipe_urls": created_urls,
                    "source_job_id": job_id,
                    "run_deferred_heavy_tasks": True,
                    "force_reprocess": False,
                },
                total_items=len(created_urls),
            )
        except Exception as exc:
            inference_job = {
                "queued": False,
                "job_id": "",
                "error": str(exc) or "Recipe inference was not queued.",
            }
        if not inference_job.get("queued"):
            append_job_warning(job_id, inference_job.get("error") or "Recipe inference was not queued.")
        print(
            f"[MenuRecipeGeneration] action=enqueue_after_menu_import_complete "
            f"source_job_id={job_id} followup_job_id={inference_job.get('job_id', '')} "
            f"queued={bool(inference_job.get('queued'))} total_items={len(created_urls)}"
        )
        enrichment_status = "queued" if inference_job.get("queued") else "queue_failed"
        enrichment_message = (
            "Recipe details are queued for background enrichment."
            if inference_job.get("queued")
            else "Background enrichment was requested but could not be queued."
        )
        result_payload.update({
            "recipe_inference_job": inference_job,
            "recipe_inference_job_id": inference_job.get("job_id", ""),
            "background_enrichment_status": enrichment_status,
            "enrichment_auto_started": bool(inference_job.get("queued")),
            "summary_message": (
                f"Imported {menu_imported_count} menu item"
                f"{'' if menu_imported_count == 1 else 's'} in {menu_elapsed_text}. "
                f"{enrichment_message}"
            ),
        })
        update_job_progress(job_id, result_payload=result_payload)
        log_import_menu_url_stage(
            "enrichment_queued",
            followup_job_id=inference_job.get("job_id", ""),
            queued=str(bool(inference_job.get("queued"))).lower(),
        )
        return get_job(job_id) or completed_job
    return completed_job


def run_doc_photo_import_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import commit_media_import_result
    from PushShoppingList.routes.recipe_routes import commit_menu_import_result
    from PushShoppingList.routes.recipe_routes import extract_menu_recipes_from_upload
    from PushShoppingList.routes.recipe_routes import extract_recipe_from_upload
    from PushShoppingList.routes.recipe_routes import resolve_menu_model
    from PushShoppingList.routes.recipe_routes import resolve_menu_model_source
    from PushShoppingList.routes.recipe_routes import resolve_vision_model
    from PushShoppingList.routes.recipe_routes import resolve_vision_model_source
    from PushShoppingList.services.recipe_extract_service import MODEL

    payload = payload if isinstance(payload, dict) else {}
    source_path = Path(str(payload.get("source_path") or ""))
    if not source_path.is_file():
        return fail_job(job_id, "Uploaded file is no longer available.")

    import_mode = str(payload.get("import_mode") or payload.get("extraction_mode") or "recipe").strip().lower()
    menu_extract = import_mode in {"menu", "menu_extract", "menu-extract"}
    upload_mode = str(payload.get("upload_mode") or "auto").strip().lower()
    manual_description = str(payload.get("manual_description") or "").strip()
    cookbook = selected_cookbook_from_payload(payload)
    initial_model = stored_job_model_metadata(job_id, model_metadata(
        resolve_menu_model() if menu_extract else (resolve_vision_model() if upload_mode in {"vision", "manual_description"} else MODEL),
        resolve_menu_model_source() if menu_extract else (resolve_vision_model_source() if upload_mode in {"vision", "manual_description"} else "recipe"),
        "OPENAI_MENU_MODEL" if menu_extract else ("OPENAI_VISION_MODEL" if upload_mode in {"vision", "manual_description"} else "OPENAI_RECIPE_MODEL"),
    ))

    update_job_progress(
        job_id,
        current_step="Reading uploaded file",
        total_items=1,
        progress_percent=10,
        result_payload=initial_model,
    )
    with source_path.open("rb") as stream:
        uploaded = FileStorage(
            stream=stream,
            filename=payload.get("filename") or source_path.name,
            content_type=payload.get("content_type") or "",
        )
        ensure_not_cancelled(job_id)
        if menu_extract:
            update_job_progress(job_id, current_step="Extracting menu sections", progress_percent=25)
            result = extract_menu_recipes_from_upload(uploaded)
        else:
            update_job_progress(job_id, current_step="Inferring ingredients", progress_percent=25)
            result = extract_recipe_from_upload(
                uploaded,
                manual_description=manual_description,
                upload_mode=upload_mode,
            )

    ensure_not_cancelled(job_id)
    update_job_progress(job_id, current_step="Creating recipe records", progress_percent=70)
    with workspace_write_lock("recipe-imports"):
        if menu_extract:
            if result.get("ok"):
                result = commit_menu_import_result(result, cookbook, context="job-menu-media")
            result.setdefault("success", bool(result.get("ok")))
            result.setdefault("menu_extract", True)
            result.setdefault("extraction_method", "menu_extract")
            result.setdefault("extraction_mode", "menu_extract")
            result.setdefault("model_used", result.get("model") or resolve_menu_model())
            result.setdefault("model_source", result.get("model_source") or resolve_menu_model_source())
            result.setdefault("model_env_var", "OPENAI_MENU_MODEL")
            result.setdefault("model_env_var_used", "OPENAI_MENU_MODEL")
        else:
            if not result.get("read_text_only"):
                result = commit_media_import_result(
                    result,
                    cookbook,
                    recipe_url=str(result.get("source_url") or ""),
                    context="job-media-upload",
                )
            result.setdefault("success", bool(result.get("ok")))
            result.setdefault(
                "model_used",
                resolve_vision_model() if str(result.get("source_type") or "").lower() == "image" else MODEL,
            )
            result.setdefault(
                "model_source",
                resolve_vision_model_source() if str(result.get("source_type") or "").lower() == "image" else "recipe",
            )
            result.setdefault(
                "model_env_var",
                "OPENAI_VISION_MODEL" if str(result.get("source_type") or "").lower() == "image" else "OPENAI_RECIPE_MODEL",
            )
            result.setdefault(
                "model_env_var_used",
                "OPENAI_VISION_MODEL" if str(result.get("source_type") or "").lower() == "image" else "OPENAI_RECIPE_MODEL",
            )

    recipe_urls = []
    if result.get("source_url"):
        recipe_urls.append(result.get("source_url"))
    if isinstance(result.get("created_urls"), list):
        recipe_urls.extend(result.get("created_urls"))
    if isinstance(result.get("recipe_urls"), list):
        recipe_urls.extend(result.get("recipe_urls"))
    recipe_urls = list(dict.fromkeys([url for url in recipe_urls if str(url or "").strip()]))

    result_payload = {
        **result,
        "links": recipe_links(recipe_urls),
    }
    update_job_progress(
        job_id,
        current_step="Finalizing results",
        progress_percent=95,
        completed_items=1 if result.get("ok") or result.get("read_text_only") else 0,
        failed_items=0 if result.get("ok") or result.get("read_text_only") else 1,
        result_payload=result_payload,
    )

    if result.get("ok") or result.get("read_text_only"):
        return complete_job(job_id, result_payload=result_payload)
    return fail_job(job_id, result.get("error") or "Import failed.", result_payload=result_payload)


def run_estimate_per_serving_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import MODEL
    from PushShoppingList.routes.recipe_routes import _existing_nutrition_success
    from PushShoppingList.routes.recipe_routes import _extract_recipe_payload_for_nutrition
    from PushShoppingList.routes.recipe_routes import _has_per_serving_estimate
    from PushShoppingList.routes.recipe_routes import _mark_uploaded_recipe_nutrition_estimated
    from PushShoppingList.routes.recipe_routes import _menu_nutrition_inference_from_rows
    from PushShoppingList.routes.recipe_routes import _recipe_with_default_serving_basis
    from PushShoppingList.routes.recipe_routes import estimate_recipe_nutrition
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import save_editable_recipe
    import os

    payload = payload if isinstance(payload, dict) else {}
    recipe_url = str(payload.get("recipe_url") or payload.get("url") or payload.get("source_url") or "").strip()
    recipe = _extract_recipe_payload_for_nutrition(payload)
    saved_recipe = {}
    nutrition_model_info = stored_job_model_metadata(
        job_id,
        active_model_metadata(
            "OPENAI_NUTRITION_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        ),
    )
    nutrition_model = nutrition_model_info.get("model_used") or MODEL

    update_job_progress(
        job_id,
        current_step="Estimating per serving",
        total_items=1,
        progress_percent=10,
        result_payload=nutrition_model_info,
    )
    if recipe_url:
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        saved_recipe = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        saved_recipe = saved_recipe if isinstance(saved_recipe, dict) else {}

    if saved_recipe and _has_per_serving_estimate(saved_recipe.get("nutrition")):
        saved_recipe = _recipe_with_default_serving_basis(saved_recipe)
        with workspace_write_lock("recipe-imports"):
            _mark_uploaded_recipe_nutrition_estimated(recipe_url, True)
        result = _existing_nutrition_success(saved_recipe, recipe_url)
        result.update(nutrition_model_info)
        return complete_job(job_id, result_payload=result)

    if not recipe and saved_recipe:
        recipe = saved_recipe

    if not recipe:
        return fail_job(job_id, "Recipe payload is required.")

    if _has_per_serving_estimate(recipe.get("nutrition") if isinstance(recipe, dict) else None):
        recipe = _recipe_with_default_serving_basis(recipe)
        if recipe_url:
            with workspace_write_lock("recipe-imports"):
                save_result = save_editable_recipe(recipe_url, recipe)
                if not save_result.get("ok"):
                    return fail_job(job_id, save_result.get("error") or "Unable to save existing nutrition.")
                _mark_uploaded_recipe_nutrition_estimated(recipe_url, True)
        result = _existing_nutrition_success(recipe, recipe_url)
        result.update(nutrition_model_info)
        return complete_job(job_id, result_payload=result)

    update_job_progress(job_id, current_step="Estimating per serving", progress_percent=45)
    result = estimate_recipe_nutrition(recipe)
    if result.get("ok") and recipe_url:
        updated_recipe = {
            **recipe,
            "nutrition": result.get("nutrition", []),
            "nutrition_inference": _menu_nutrition_inference_from_rows(
                result.get("nutrition", []),
                model=nutrition_model,
            ),
        }
        with workspace_write_lock("recipe-imports"):
            save_result = save_editable_recipe(recipe_url, updated_recipe)
            if not save_result.get("ok"):
                _mark_uploaded_recipe_nutrition_estimated(recipe_url, False)
                return fail_job(job_id, save_result.get("error") or "Unable to save estimated nutrition.", result_payload=result)
            result["recipe_json"] = updated_recipe
            result["recipe_url"] = recipe_url
            _mark_uploaded_recipe_nutrition_estimated(recipe_url, True)

    result["success"] = bool(result.get("ok"))
    result.update(nutrition_model_info)
    if result.get("ok"):
        return complete_job(job_id, result_payload=result)
    return fail_job(job_id, result.get("error") or "Unable to estimate nutrition.", result_payload=result)


def run_create_recipe_pdf_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import create_recipe_pdf_from_url
    from PushShoppingList.routes.recipe_routes import upload_recipe_pdf_to_cloudflare

    payload = payload if isinstance(payload, dict) else {}
    recipe_url = str(payload.get("url") or payload.get("recipe_url") or payload.get("source_url") or "").strip()
    if not recipe_url:
        return fail_job(job_id, "Recipe URL is required.")

    update_job_progress(job_id, current_step="Generating recipe PDF", total_items=1, progress_percent=20)
    with workspace_write_lock("recipe-pdfs"):
        result = create_recipe_pdf_from_url(recipe_url)
    if not result.get("ok"):
        return fail_job(job_id, result.get("error") or "Unable to create recipe PDF.", result_payload=result)

    if payload.get("upload_to_cloudflare"):
        update_job_progress(job_id, current_step="Uploading PDF to Cloudflare", progress_percent=75)
        with workspace_write_lock("recipe-pdfs"):
            upload_result = upload_recipe_pdf_to_cloudflare(recipe_url, pdf_kind="generated_recipe")
        result["cloudflare_upload"] = upload_result
        if upload_result.get("ok"):
            result.update(upload_result)
        else:
            append_job_warning(job_id, upload_result.get("error") or "Cloudflare upload failed.")

    links = []
    public_url = result.get("pdf_public_url") or result.get("generated_cloudflare_pdf_url")
    if public_url:
        links.append({"label": "Open PDF", "url": public_url})
    result["links"] = links
    return complete_job(job_id, result_payload=result)


def run_upload_pdf_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import normalize_pdf_kind
    from PushShoppingList.routes.recipe_routes import upload_recipe_pdf_to_cloudflare

    payload = payload if isinstance(payload, dict) else {}
    recipe_url = str(payload.get("url") or payload.get("recipe_url") or payload.get("source_url") or "").strip()
    kind = normalize_pdf_kind(payload.get("kind") or payload.get("pdf_kind") or "")
    if payload.get("job_type") == "upload-source-pdf" and not kind:
        kind = "source"

    if not recipe_url:
        return fail_job(job_id, "Recipe URL is required.")

    update_job_progress(job_id, current_step="Uploading PDF to Cloudflare", total_items=1, progress_percent=25)
    with workspace_write_lock("recipe-pdfs"):
        result = upload_recipe_pdf_to_cloudflare(recipe_url, pdf_kind=kind)
    if result.get("ok"):
        links = []
        public_url = result.get("pdf_public_url") or result.get("generated_cloudflare_pdf_url") or result.get("source_cloudflare_pdf_url")
        if public_url:
            links.append({"label": "Open Cloudflare PDF", "url": public_url})
        result["links"] = links
        return complete_job(job_id, result_payload=result)
    return fail_job(job_id, result.get("error") or "Unable to upload PDF to Cloudflare.", result_payload=result)


def run_product_matching_job(job_id, payload):
    from PushShoppingList.services.product_selection_service import grab_best_products
    from PushShoppingList.services.product_selection_service import PRODUCT_ANALYSIS_MODEL

    payload = payload if isinstance(payload, dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else None
    total = len(items) if items else 0
    product_model_info = stored_job_model_metadata(
        job_id,
        active_model_metadata(
            "OPENAI_PRODUCT_ANALYSIS_MODEL",
            PRODUCT_ANALYSIS_MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        ),
    )
    update_job_progress(
        job_id,
        current_step="Matching products",
        total_items=total,
        progress_percent=10,
        result_payload=product_model_info,
    )
    result = grab_best_products(items=items, job_id=job_id)
    if isinstance(result, dict):
        result.update({key: value for key, value in product_model_info.items() if value and not result.get(key)})
    selected = int(result.get("selected_count") or 0) if isinstance(result, dict) else 0
    count = int(result.get("count") or total or selected) if isinstance(result, dict) else total
    update_job_progress(
        job_id,
        current_step="Finalizing results",
        progress_percent=95,
        total_items=count,
        completed_items=selected,
        failed_items=max(0, count - selected),
    )
    if isinstance(result, dict) and result.get("ok", True):
        return complete_job(job_id, result_payload=result)
    return fail_job(job_id, (result or {}).get("error") or "Product matching failed.", result_payload=result or {})


def run_recipe_category_decision_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import decide_recipe_categories_with_chatgpt
    from PushShoppingList.routes.recipe_routes import MODEL

    payload = payload if isinstance(payload, dict) else {}
    recipe = payload.get("recipe", payload)
    mode = payload.get("mode", "missing")
    category_model_info = stored_job_model_metadata(
        job_id,
        active_model_metadata(
            "OPENAI_RECIPE_CATEGORY_MODEL",
            MODEL,
            "fallback:OPENAI_RECIPE_MODEL",
        ),
    )
    update_job_progress(
        job_id,
        current_step="Having ChatGPT decide categories",
        total_items=1,
        progress_percent=20,
        result_payload=category_model_info,
    )
    with workspace_write_lock("recipe-imports"):
        result = decide_recipe_categories_with_chatgpt(
            recipe,
            mode=mode,
            current_categories=payload.get("current_categories", {}),
            trigger_source=payload.get("trigger_source") or f"recipe_editor:{mode}",
        )
    if isinstance(result, dict):
        result.update({key: value for key, value in category_model_info.items() if value and not result.get(key)})
    if result.get("ok"):
        return complete_job(job_id, result_payload=result)
    return fail_job(job_id, result.get("error") or "Unable to decide categories.", result_payload=result)
