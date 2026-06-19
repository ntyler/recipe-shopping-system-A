import os
import re
from pathlib import Path

from werkzeug.datastructures import FileStorage

from PushShoppingList.services.job_service import append_job_warning
from PushShoppingList.services.job_service import complete_job
from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_cancelled
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
        "menu-deferred-heavy-tasks": run_menu_deferred_heavy_tasks_job,
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
        return model_metadata(resolve_menu_model(), resolve_menu_model_source(), "OPENAI_MENU_MODEL")

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
    payload = {**payload, "extraction_mode": "menu_extract"}
    return run_import_urls_job(job_id, payload, menu_extract=True)


def run_recipe_import_job(job_id, payload):
    return run_import_urls_job(job_id, payload if isinstance(payload, dict) else {}, menu_extract=False)


def run_menu_generate_recipes_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import add_items
    from PushShoppingList.routes.recipe_routes import apply_imported_recipe_category_routine
    from PushShoppingList.routes.recipe_routes import import_recipe_title
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import record_recipe_import_activity
    from PushShoppingList.routes.recipe_routes import resolve_menu_model
    from PushShoppingList.routes.recipe_routes import resolve_menu_model_source
    from PushShoppingList.routes.recipe_routes import save_ingredients_for_recipe
    from PushShoppingList.routes.recipe_routes import save_recipe_url_name
    from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
    from PushShoppingList.services.recipe_extract_service import apply_menu_batch_inference_to_stub
    from PushShoppingList.services.recipe_extract_service import menu_batch_entry_item_name
    from PushShoppingList.services.recipe_extract_service import infer_menu_item_recipe_batch
    from PushShoppingList.services.recipe_extract_service import menu_batch_item_from_stub
    from PushShoppingList.services.recipe_extract_service import menu_inference_batches
    from PushShoppingList.services.recipe_extract_service import menu_item_name_is_blank_divider
    from PushShoppingList.services.recipe_url_service import add_recipe_urls
    from PushShoppingList.services.storage_service import active_user_id
    from PushShoppingList.services.cookbook_service import cookbook_recipe_assignment_for_url

    payload = payload if isinstance(payload, dict) else {}
    force_reprocess = payload_bool(payload, "force_reprocess", False)
    run_heavy_tasks = payload_bool(payload, "run_deferred_heavy_tasks", True)
    raw_urls = payload.get("recipe_urls") or payload.get("urls")
    if isinstance(raw_urls, str):
        raw_urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    if not isinstance(raw_urls, list):
        raw_urls = [payload.get("recipe_url") or payload.get("url") or payload.get("source_url") or ""]
    recipe_urls = [str(url or "").strip() for url in raw_urls if str(url or "").strip()]
    if not recipe_urls:
        return fail_job(job_id, "At least one menu item stub URL is required.")

    total = len(recipe_urls)
    model_info = stored_job_model_metadata(job_id, model_metadata(
        resolve_menu_model(),
        resolve_menu_model_source(),
        "OPENAI_MENU_MODEL",
    ))
    created_urls = []
    skipped_urls = []
    failed_items = 0
    pending_entries = []
    category_statuses = []
    category_success_count = 0

    update_job_progress(
        job_id,
        current_step="Predicting recipes",
        total_items=total,
        progress_percent=5,
        result_payload={
            **model_info,
            "stage": "Predicting recipes",
            "total_items": total,
            "recipe_shells_created": total,
            "recipe_inference_completed": 0,
            "nutrition_completed": 0,
            "pdfs_completed": 0,
            "failed_items": 0,
        },
    )

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

    batches = menu_inference_batches(pending_entries)
    batch_total = len(batches)
    completed_batches = 0

    for batch_index, batch in enumerate(batches, start=1):
        ensure_not_cancelled(job_id)
        update_job_progress(
            job_id,
            current_step=f"Predicting recipes ({batch_index}/{batch_total})",
            progress_percent=bounded_percent(batch_index - 1, max(1, batch_total), 10, 82),
            completed_items=len(created_urls) + len(skipped_urls),
            failed_items=failed_items,
            result_payload={
                **model_info,
                "stage": "Predicting recipes",
                "total_items": total,
                "recipe_inference_completed": len(created_urls),
                "skipped_count": len(skipped_urls),
                "failed_items": failed_items,
                "batch_count": batch_total,
                "batch_index": batch_index,
            },
        )

        batch_result = {}
        for attempt in range(2):
            ensure_not_cancelled(job_id)
            batch_result = infer_menu_item_recipe_batch(batch, user_id=active_user_id())
            result_items = batch_result.get("items") if isinstance(batch_result.get("items"), dict) else {}
            failure_items = batch_result.get("failures") if isinstance(batch_result.get("failures"), dict) else {}
            missing_ids = [
                str((entry.get("menu_item") or {}).get("menu_item_id") or "").strip()
                for entry in batch
                if str((entry.get("menu_item") or {}).get("menu_item_id") or "").strip() not in result_items
            ]
            if batch_result.get("ok") and not missing_ids:
                break
            if result_items:
                append_job_warning(
                    job_id,
                    (
                        f"Batch {batch_index}/{batch_total} returned partial recipe predictions; "
                        f"{len(missing_ids or failure_items)} item(s) still need attention. "
                        f"{batch_result.get('error_message') or ''}"
                    ).strip(),
                )
                break
            if attempt == 0:
                append_job_warning(
                    job_id,
                    (
                        f"Batch {batch_index}/{batch_total} failed once; retrying. "
                        f"{batch_result.get('error_message') or ('Missing menu_item_id: ' + ', '.join(missing_ids[:3]) if missing_ids else '')}"
                    ).strip(),
                )
                if batch_result.get("ok") and missing_ids:
                    batch_result = {**batch_result, "ok": False}

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
        failed_names_text = ", ".join(name for name in failed_names[:12] if name)
        if failed_names:
            print(
                "[Job Worker] action=menu-item-recipe-batch-final-failed-items "
                f"job_id={job_id} batch_index={batch_index} batch_count={batch_total} "
                f"failed_count={len(failed_names)} failed_item_names={failed_names_text}"
            )
        if not result_items:
            failed_items += len(batch)
            append_job_warning(
                job_id,
                (
                    f"Batch {batch_index}/{batch_total}: "
                    f"{batch_result.get('error_message') or ('Missing menu_item_id: ' + ', '.join(missing_ids[:3]) if missing_ids else 'Unable to predict recipes.')} "
                    f"Failed item names: {failed_names_text}"
                ).strip(),
            )
            continue
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

        for entry in batch:
            ensure_not_cancelled(job_id)
            recipe_url = entry["recipe_url"]
            menu_item = entry.get("menu_item") if isinstance(entry.get("menu_item"), dict) else {}
            recipe_name = cookbook_recipe_display_name(
                recipe_url,
                {"name": menu_item.get("item_name")},
            )
            recipe_position = min(total, len(created_urls) + len(skipped_urls) + failed_items + 1)
            item_id = str(menu_item.get("menu_item_id") or "").strip()
            item_result = result_items.get(item_id)
            if not isinstance(item_result, dict):
                failed_items += 1
                failure = failure_items.get(item_id) if isinstance(failure_items.get(item_id), dict) else {}
                append_job_warning(
                    job_id,
                    (
                        f"{recipe_name} ({recipe_url}): "
                        f"{failure.get('error') or f'Batch response did not include menu_item_id {item_id}.'}"
                    ).strip(),
                )
                continue

            update_job_progress(
                job_id,
                current_step=f"Saving predicted recipe for {recipe_name} ({recipe_position}/{total})",
                progress_percent=bounded_percent(len(created_urls), total, 82, 88),
                completed_items=len(created_urls) + len(skipped_urls),
                failed_items=failed_items,
                result_payload={
                    **model_info,
                    "stage": "Saving predicted recipes",
                    "total_items": total,
                    "recipe_inference_completed": len(created_urls),
                    "skipped_count": len(skipped_urls),
                    "category_success_count": category_success_count,
                    "failed_items": failed_items,
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

            result = apply_menu_batch_inference_to_stub(
                recipe_url,
                entry.get("stub") or {},
                menu_item,
                item_result,
                model=batch_result.get("model") or model_info.get("model_used"),
                model_source=batch_result.get("model_source") or model_info.get("model_source"),
            )
            if not result.get("ok"):
                failed_items += 1
                append_job_warning(job_id, f"{recipe_url}: {result.get('error') or 'Unable to save predicted recipe.'}")
                continue

            ingredients = result.get("ingredients") if isinstance(result.get("ingredients"), list) else []
            with workspace_write_lock("recipe-imports"):
                if ingredients:
                    add_items(ingredients)
                    save_ingredients_for_recipe(recipe_url, ingredients, result)
                if result.get("display_name") or result.get("recipe_title"):
                    save_recipe_url_name(recipe_url, result.get("display_name") or result.get("recipe_title"))
                add_recipe_urls([recipe_url])

            update_job_progress(
                job_id,
                current_step=f"Generating ChatGPT categories for {recipe_name} ({recipe_position}/{total})",
                progress_percent=bounded_percent(len(created_urls), total, 82, 88),
                completed_items=len(created_urls) + len(skipped_urls),
                failed_items=failed_items,
                result_payload={
                    **model_info,
                    "stage": "Generating categories",
                    "total_items": total,
                    "recipe_inference_completed": len(created_urls),
                    "category_success_count": category_success_count,
                    "failed_items": failed_items,
                    **cookbook_recipe_progress_payload(
                        "categories",
                        "Deciding categories for",
                        recipe_url,
                        recipe_name,
                        recipe_position,
                        total,
                        event="started",
                    ),
                },
            )
            assignment = cookbook_recipe_assignment_for_url(recipe_url)
            if not assignment.get("cookbook_id"):
                assignment = {
                    "cookbook_id": result.get("cookbook_id") or (entry.get("stub") or {}).get("cookbook_id", ""),
                    "cookbook_name": result.get("cookbook_name") or (entry.get("stub") or {}).get("cookbook_name", ""),
                }
            category_status = apply_imported_recipe_category_routine(
                recipe_url,
                result,
                assignment,
                trigger_source="menu_generate:all",
            )
            category_statuses.append({
                **category_status,
                "recipe_url": recipe_url,
            })
            if category_status.get("ok"):
                category_success_count += 1
            else:
                append_job_warning(
                    job_id,
                    f"{import_recipe_title(result, recipe_url)}: {category_status.get('error') or 'Category inference skipped.'}",
                )
            result = {
                **result,
                "import_category_status": category_status,
                "category_status": category_status,
            }
            record_recipe_import_activity(recipe_url, result, "menu-batch-generation")
            print(
                "[recipe_import] action=menu_stub_generated_batch "
                f"title={import_recipe_title(result, recipe_url)} url={recipe_url}"
            )
            created_urls.append(recipe_url)

        completed_batches += 1

    ensure_not_cancelled(job_id)
    if created_urls:
        update_job_progress(
            job_id,
            current_step="Finalizing predicted recipes",
            progress_percent=88,
            result_payload={
                **model_info,
                "stage": "Predicting recipes",
                "recipe_inference_completed": len(created_urls),
                "failed_items": failed_items,
            },
        )
        with workspace_write_lock("recipe-imports"):
            sort_ingredients()

    heavy_job = {}
    if run_heavy_tasks and created_urls:
        update_job_progress(
            job_id,
            current_step="Queueing deferred heavy tasks",
            progress_percent=93,
            result_payload={
                **model_info,
                "stage": "Estimating nutrition",
                "recipe_inference_completed": len(created_urls),
                "nutrition_completed": 0,
                "pdfs_completed": 0,
                "failed_items": failed_items,
            },
        )
        heavy_job = enqueue_followup_job(
            "menu-deferred-heavy-tasks",
            {
                "recipe_urls": created_urls,
                "force_reprocess": force_reprocess,
                "source_job_id": job_id,
                "context": "menu-batch-generation",
            },
            total_items=len(created_urls),
        )
        if not heavy_job.get("queued"):
            append_job_warning(job_id, heavy_job.get("error") or "Deferred heavy tasks were not queued.")

    result_payload = {
        "ok": bool(created_urls or skipped_urls),
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
        "pdfs_created": 0,
        "pdfs_completed": 0,
        "category_statuses": category_statuses,
        "category_success_count": category_success_count,
        "categories_generated": category_success_count,
        "batch_count": batch_total,
        "batches_completed": completed_batches,
        "deferred_heavy_tasks_job": heavy_job,
        "deferred_heavy_tasks_job_id": heavy_job.get("job_id", ""),
        "stage": "Complete",
        **model_info,
    }
    update_job_progress(
        job_id,
        current_step="Finalizing results",
        progress_percent=95,
        total_items=total,
        completed_items=len(created_urls) + len(skipped_urls),
        failed_items=failed_items,
        result_payload=result_payload,
    )

    if created_urls or skipped_urls:
        return complete_job(job_id, result_payload=result_payload)
    return fail_job(job_id, "No menu item stubs were generated.", result_payload=result_payload)


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
            } if menu_extract else {}),
        },
    )

    for index, url in enumerate(urls):
        ensure_not_cancelled(job_id)
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
                current_step="Creating recipe shells",
                progress_percent=bounded_percent(index, total, 65, 90),
                result_payload={
                    **job_model,
                    "stage": "Creating recipe shells",
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
            else:
                failed_items += 1
                append_job_warning(job_id, f"{url}: {committed.get('error') or 'No menu item recipes were created.'}")
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

    final_total = max(total, len(created_urls) + failed_items) if menu_extract else total
    result_payload = {
        "ok": bool(created_urls),
        "created_count": len(created_urls),
        "failed_count": failed_items,
        "failed_items": failed_items,
        "recipe_urls": created_urls,
        "links": recipe_links(created_urls),
        **job_model,
    }
    if menu_extract:
        inference_job = {}
        if created_urls and payload_bool(payload, "auto_generate_recipes", True):
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
            if not inference_job.get("queued"):
                append_job_warning(job_id, inference_job.get("error") or "Recipe inference was not queued.")
        result_payload.update(menu_job_stats)
        result_payload.update({
            "stage": "Complete",
            "recipe_shells_created": len(created_urls),
            "recipe_inference_completed": 0,
            "nutrition_completed": 0,
            "pdfs_completed": 0,
            "recipe_inference_job": inference_job,
            "recipe_inference_job_id": inference_job.get("job_id", ""),
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
    return complete_job(job_id, result_payload=result_payload)


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
