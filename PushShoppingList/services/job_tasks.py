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

    if job_type == "menu-import":
        return model_metadata(resolve_menu_cleanup_model(), resolve_menu_cleanup_model_source(), "OPENAI_MENU_CLEANUP_MODEL")

    if job_type == "doc-photo-import" and mode in {"menu", "menu_extract", "menu-extract"}:
        return model_metadata(resolve_menu_model(), resolve_menu_model_source(), "OPENAI_MENU_MODEL")

    if job_type == "doc-photo-import" and is_image_upload:
        return model_metadata(resolve_vision_model(), resolve_vision_model_source(), "OPENAI_VISION_MODEL")

    if job_type == "estimate-per-serving":
        return model_metadata(
            str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL)),
            "env:OPENAI_NUTRITION_MODEL" if os.getenv("OPENAI_NUTRITION_MODEL") else "fallback:OPENAI_RECIPE_MODEL",
            "OPENAI_NUTRITION_MODEL",
        )

    if job_type == "product-matching":
        env_var = "OPENAI_PRODUCT_ANALYSIS_MODEL" if os.getenv("OPENAI_PRODUCT_ANALYSIS_MODEL") else "OPENAI_RECIPE_MODEL"
        return model_metadata(
            str(os.getenv("OPENAI_PRODUCT_ANALYSIS_MODEL") or os.getenv("OPENAI_RECIPE_MODEL") or "gpt-4o-mini"),
            f"env:{env_var}",
            env_var,
        )

    if job_type == "recipe-category-decision":
        model = str(os.getenv("OPENAI_RECIPE_CATEGORY_MODEL", MODEL))
        return model_metadata(
            model,
            "env:OPENAI_RECIPE_CATEGORY_MODEL" if os.getenv("OPENAI_RECIPE_CATEGORY_MODEL") else "fallback:OPENAI_RECIPE_MODEL",
            "OPENAI_RECIPE_CATEGORY_MODEL",
        )

    if job_type == "recipe-import" or job_type == "doc-photo-import":
        return model_metadata(MODEL, "recipe", "OPENAI_RECIPE_MODEL")

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


def run_menu_import_job(job_id, payload):
    payload = payload if isinstance(payload, dict) else {}
    payload = {**payload, "extraction_mode": "menu_extract"}
    return run_import_urls_job(job_id, payload, menu_extract=True)


def run_recipe_import_job(job_id, payload):
    return run_import_urls_job(job_id, payload if isinstance(payload, dict) else {}, menu_extract=False)


def run_menu_generate_recipes_job(job_id, payload):
    from PushShoppingList.routes.recipe_routes import add_items
    from PushShoppingList.routes.recipe_routes import generate_menu_recipe_from_stub
    from PushShoppingList.routes.recipe_routes import import_recipe_title
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import record_recipe_import_activity
    from PushShoppingList.routes.recipe_routes import resolve_menu_model
    from PushShoppingList.routes.recipe_routes import resolve_menu_model_source
    from PushShoppingList.routes.recipe_routes import save_ingredients_for_recipe
    from PushShoppingList.routes.recipe_routes import save_recipe_url_name
    from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
    from PushShoppingList.services.recipe_url_service import add_recipe_urls
    from PushShoppingList.services.storage_service import active_user_id

    payload = payload if isinstance(payload, dict) else {}
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

    update_job_progress(
        job_id,
        current_step="Generating full recipes",
        total_items=total,
        progress_percent=5,
        result_payload=model_info,
    )

    for index, recipe_url in enumerate(recipe_urls):
        ensure_not_cancelled(job_id)
        update_job_progress(
            job_id,
            current_step=f"Generating full recipe {index + 1}/{total}",
            progress_percent=bounded_percent(index, total, 5, 80),
            completed_items=len(created_urls),
            failed_items=failed_items,
            result_payload=model_info,
        )

        loaded_recipe = load_editable_recipe(recipe_url) or {}
        stub = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        stub = stub if isinstance(stub, dict) else {}
        if not stub:
            failed_items += 1
            append_job_warning(job_id, f"{recipe_url}: Menu item stub was not found.")
            continue

        if str(stub.get("recipe_status") or "").strip().lower() == "generated" and not stub.get("needs_ai_recipe"):
            skipped_urls.append(recipe_url)
            continue

        result = generate_menu_recipe_from_stub(recipe_url, stub, user_id=active_user_id())
        if not result.get("ok"):
            failed_items += 1
            append_job_warning(job_id, f"{recipe_url}: {result.get('error') or 'Unable to generate full recipe.'}")
            continue

        ingredients = result.get("ingredients") if isinstance(result.get("ingredients"), list) else []
        with workspace_write_lock("recipe-imports"):
            if ingredients:
                add_items(ingredients)
                save_ingredients_for_recipe(recipe_url, ingredients, result)
            if result.get("display_name") or result.get("recipe_title"):
                save_recipe_url_name(recipe_url, result.get("display_name") or result.get("recipe_title"))
            add_recipe_urls([recipe_url])

        record_recipe_import_activity(recipe_url, result, "menu-stub-generation")
        print(
            "[recipe_import] action=menu_stub_generated "
            f"title={import_recipe_title(result, recipe_url)} url={recipe_url}"
        )
        created_urls.append(recipe_url)

    ensure_not_cancelled(job_id)
    if created_urls:
        update_job_progress(job_id, current_step="Finalizing generated recipes", progress_percent=92)
        with workspace_write_lock("recipe-imports"):
            sort_ingredients()

    result_payload = {
        "ok": bool(created_urls or skipped_urls),
        "created_count": len(created_urls),
        "generated_count": len(created_urls),
        "full_recipes_generated": len(created_urls),
        "skipped_count": len(skipped_urls),
        "failed_count": failed_items,
        "recipe_urls": created_urls + skipped_urls,
        "generated_recipe_urls": created_urls,
        "skipped_recipe_urls": skipped_urls,
        "links": recipe_links(created_urls + skipped_urls),
        "nutrition_estimates_completed": 0,
        "pdfs_created": 0,
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
    }
    job_model = stored_job_model_metadata(job_id, model_metadata(
        resolve_menu_cleanup_model() if menu_extract else MODEL,
        resolve_menu_cleanup_model_source() if menu_extract else "recipe",
        "OPENAI_MENU_CLEANUP_MODEL" if menu_extract else "OPENAI_RECIPE_MODEL",
    ))

    update_job_progress(
        job_id,
        current_step="Reading source URL" if total == 1 else "Reading source URLs",
        total_items=total,
        progress_percent=5,
        result_payload=job_model,
    )

    for index, url in enumerate(urls):
        ensure_not_cancelled(job_id)
        step = "Fetching menu page" if menu_extract else "Reading source URL"
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
                current_step="Creating menu stubs",
                progress_percent=bounded_percent(index, total, 65, 90),
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
        "recipe_urls": created_urls,
        "links": recipe_links(created_urls),
        **job_model,
    }
    if menu_extract:
        result_payload.update(menu_job_stats)
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
    from PushShoppingList.routes.recipe_routes import _recipe_with_default_serving_basis
    from PushShoppingList.routes.recipe_routes import estimate_recipe_nutrition
    from PushShoppingList.routes.recipe_routes import load_editable_recipe
    from PushShoppingList.routes.recipe_routes import save_editable_recipe
    import os

    payload = payload if isinstance(payload, dict) else {}
    recipe_url = str(payload.get("recipe_url") or payload.get("url") or payload.get("source_url") or "").strip()
    recipe = _extract_recipe_payload_for_nutrition(payload)
    saved_recipe = {}
    nutrition_model = str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL))
    nutrition_model_info = stored_job_model_metadata(job_id, model_metadata(
        nutrition_model,
        "env:OPENAI_NUTRITION_MODEL" if os.getenv("OPENAI_NUTRITION_MODEL") else "fallback:OPENAI_RECIPE_MODEL",
        "OPENAI_NUTRITION_MODEL",
    ))

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
    import os

    from PushShoppingList.services.product_selection_service import grab_best_products
    from PushShoppingList.services.product_selection_service import PRODUCT_ANALYSIS_MODEL

    payload = payload if isinstance(payload, dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else None
    total = len(items) if items else 0
    product_model_env = "OPENAI_PRODUCT_ANALYSIS_MODEL" if os.getenv("OPENAI_PRODUCT_ANALYSIS_MODEL") else "OPENAI_RECIPE_MODEL"
    product_model_info = stored_job_model_metadata(job_id, model_metadata(
        PRODUCT_ANALYSIS_MODEL,
        f"env:{product_model_env}",
        product_model_env,
    ))
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
    category_model_info = stored_job_model_metadata(job_id, model_metadata(MODEL, "recipe", "OPENAI_RECIPE_MODEL"))
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
