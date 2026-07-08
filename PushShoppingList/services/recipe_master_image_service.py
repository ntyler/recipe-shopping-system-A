import base64
import os
import threading
import uuid

import requests

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services.image_variant_service import ensure_webp_variants
from PushShoppingList.services.openai_throttle_service import throttled_image_generation
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.recipe_edit_service import STEP_IMAGE_FOLDER
from PushShoppingList.services.recipe_edit_service import STEP_IMAGE_URL_PREFIX
from PushShoppingList.services.recipe_edit_service import build_recipe_equipment_image_prompt
from PushShoppingList.services.recipe_edit_service import build_recipe_ingredient_image_prompt
from PushShoppingList.services.recipe_edit_service import finalize_equipment_image_prompt
from PushShoppingList.services.recipe_edit_service import first_openai_image_record
from PushShoppingList.services.recipe_edit_service import openai_image_field
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import safe_filename


SUPPORTED_MASTER_IMAGE_TYPES = {"ingredients", "equipment"}
MASTER_IMAGE_LABELS = {
    "ingredients": "ingredient",
    "equipment": "equipment",
}
MASTER_IMAGE_PROGRESS_LOCK = threading.RLock()
MASTER_IMAGE_PROGRESS_RUNS = {}
MAX_MASTER_IMAGE_PROGRESS_RUNS = 8
MAX_MASTER_IMAGE_PROGRESS_ITEMS = 500


def master_image_type_label(record_type, plural=False):
    label = MASTER_IMAGE_LABELS.get(str(record_type or "").strip(), "record")
    if plural:
        return "equipment" if label == "equipment" else f"{label}s"
    return label


def _new_image_progress(job_id, record_type="ingredients", user_id="", include_all_users=False, search=""):
    now = master_data.utc_now_iso()
    return {
        "job_id": str(job_id or "").strip(),
        "status": "starting",
        "summary": "Preparing master image generation.",
        "record_type": str(record_type or "ingredients").strip(),
        "user_id": master_data.clean_text(user_id),
        "include_all_users": bool(include_all_users),
        "search": master_data.clean_text(search),
        "started_at": now,
        "updated_at": now,
        "total": 0,
        "completed": 0,
        "generated": 0,
        "failed": 0,
        "skipped": 0,
        "current_record_id": 0,
        "current_record_name": "",
        "items": [],
    }


def _prune_image_progress_runs():
    if len(MASTER_IMAGE_PROGRESS_RUNS) <= MAX_MASTER_IMAGE_PROGRESS_RUNS:
        return

    removable = sorted(
        (
            progress
            for progress in MASTER_IMAGE_PROGRESS_RUNS.values()
            if progress.get("status") not in {"starting", "running"}
        ),
        key=lambda progress: str(progress.get("updated_at") or ""),
    )
    for progress in removable:
        if len(MASTER_IMAGE_PROGRESS_RUNS) <= MAX_MASTER_IMAGE_PROGRESS_RUNS:
            break
        MASTER_IMAGE_PROGRESS_RUNS.pop(progress.get("job_id"), None)


def _progress_items(progress):
    items = progress.setdefault("items", [])
    if len(items) > MAX_MASTER_IMAGE_PROGRESS_ITEMS:
        progress["items"] = items[-MAX_MASTER_IMAGE_PROGRESS_ITEMS:]
    return progress["items"]


def _append_progress_item(progress, row, state, image_url="", error=""):
    item = {
        "id": int(row.get("id") or 0),
        "user_id": master_data.clean_text(row.get("user_id")),
        "name": master_data.clean_text(row.get("name") or row.get("normalized_name")),
        "state": state,
        "image_url": master_data.clean_text(image_url),
        "error": master_data.clean_text(error),
        "updated_at": master_data.utc_now_iso(),
    }
    _progress_items(progress).append(item)
    _progress_items(progress)
    return item


def start_master_image_progress(job_id, record_type="ingredients", user_id="", include_all_users=False, search=""):
    job_id = str(job_id or "").strip()
    if not job_id:
        return None

    with MASTER_IMAGE_PROGRESS_LOCK:
        progress = _new_image_progress(
            job_id,
            record_type=record_type,
            user_id=user_id,
            include_all_users=include_all_users,
            search=search,
        )
        MASTER_IMAGE_PROGRESS_RUNS[job_id] = progress
        _prune_image_progress_runs()
        return dict(progress)


def master_image_progress(job_id=None):
    with MASTER_IMAGE_PROGRESS_LOCK:
        if job_id:
            progress = MASTER_IMAGE_PROGRESS_RUNS.get(str(job_id or "").strip())
        else:
            progress = None
            for candidate in MASTER_IMAGE_PROGRESS_RUNS.values():
                if progress is None or str(candidate.get("updated_at") or "") > str(progress.get("updated_at") or ""):
                    progress = candidate
        if not progress:
            return None
        return {
            **progress,
            "items": [dict(item) for item in progress.get("items", [])],
        }


def update_master_image_progress(job_id, event, payload=None):
    job_id = str(job_id or "").strip()
    if not job_id:
        return None
    payload = payload if isinstance(payload, dict) else {}

    with MASTER_IMAGE_PROGRESS_LOCK:
        progress = MASTER_IMAGE_PROGRESS_RUNS.get(job_id)
        if progress is None:
            progress = _new_image_progress(
                job_id,
                record_type=payload.get("record_type", "ingredients"),
                user_id=payload.get("user_id", ""),
                include_all_users=payload.get("include_all_users", False),
                search=payload.get("search", ""),
            )
            MASTER_IMAGE_PROGRESS_RUNS[job_id] = progress

        progress["updated_at"] = master_data.utc_now_iso()
        if event == "started":
            total = int(payload.get("total") or 0)
            if payload.get("record_type"):
                progress["record_type"] = master_data.clean_text(payload.get("record_type"))
            item_label = master_image_type_label(progress.get("record_type"), plural=True)
            progress.update({
                "status": "running" if total else "complete",
                "summary": (
                    f"Generating {total} missing {item_label} images."
                    if total
                    else f"No missing {item_label} images were found for this scope."
                ),
                "total": total,
            })
        elif event == "record_start":
            row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
            item_label = master_image_type_label(progress.get("record_type"))
            progress.update({
                "status": "running",
                "current_record_id": int(row.get("id") or 0),
                "current_record_name": master_data.clean_text(row.get("name") or row.get("normalized_name")),
                "summary": f"Generating image for {master_data.clean_text(row.get('name') or row.get('normalized_name')) or item_label}.",
            })
        elif event == "record_done":
            row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
            _append_progress_item(progress, row, "done", image_url=payload.get("image_url", ""))
            progress["completed"] = int(progress.get("completed") or 0) + 1
            progress["generated"] = int(progress.get("generated") or 0) + 1
            progress["summary"] = f"Generated {progress['generated']} of {progress.get('total') or 0} missing images."
        elif event == "record_skipped":
            row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
            _append_progress_item(progress, row, "skipped", error=payload.get("error", "Skipped."))
            progress["completed"] = int(progress.get("completed") or 0) + 1
            progress["skipped"] = int(progress.get("skipped") or 0) + 1
        elif event == "record_failed":
            row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
            item_label = master_image_type_label(progress.get("record_type"))
            _append_progress_item(progress, row, "failed", error=payload.get("error", "Image generation failed."))
            progress["completed"] = int(progress.get("completed") or 0) + 1
            progress["failed"] = int(progress.get("failed") or 0) + 1
            progress["summary"] = f"Failed image for {master_data.clean_text(row.get('name') or row.get('normalized_name')) or item_label}."
        elif event == "complete":
            progress.update({
                "status": "complete",
                "summary": (
                    f"Image generation finished: {int(progress.get('generated') or 0)} generated, "
                    f"{int(progress.get('failed') or 0)} failed, {int(progress.get('skipped') or 0)} skipped."
                ),
                "current_record_id": 0,
                "current_record_name": "",
            })
        elif event == "failed":
            progress.update({
                "status": "failed",
                "summary": master_data.clean_text(payload.get("error")) or "Image generation failed.",
                "current_record_id": 0,
                "current_record_name": "",
            })

        return master_image_progress(job_id)


def missing_master_image_rows(record_type="ingredients", user_id=None, search=None, include_all_users=False, limit=None):
    if record_type not in SUPPORTED_MASTER_IMAGE_TYPES:
        raise ValueError("Unsupported master image record type.")
    config = master_data.master_record_table_config(record_type)
    usage_table = config["usage_table"]
    usage_fk = config["usage_fk"]

    where, params = master_data.master_record_filters(
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
    )
    where.append("TRIM(COALESCE(m.image_url, '')) = ''")
    where_clause = f"WHERE {' AND '.join(where)}"
    limit_clause = ""
    if limit:
        limit_clause = "LIMIT ?"
        params.append(int(limit))

    with master_data.existing_recipe_master_connection() as connection:
        if connection is None:
            return []

        rows = connection.execute(
            f"""
            SELECT
                m.id,
                m.user_id,
                m.name,
                m.normalized_name,
                m.image_url,
                m.image_path,
                m.created_at,
                m.updated_at,
                COUNT(u.id) AS usage_count
              FROM {record_type} m
              LEFT JOIN {usage_table} u
                ON u.{usage_fk} = m.id
               AND u.user_id = m.user_id
              {where_clause}
             GROUP BY m.id
             ORDER BY m.updated_at DESC, m.id DESC
             {limit_clause}
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def build_master_equipment_image_prompt(row, index):
    base_prompt = build_recipe_equipment_image_prompt(
        recipe_title="Equipment master data",
        servings="Not specified",
        ingredients="Not specified",
        equipment_item_number=index,
        equipment_item=row.get("name") or row.get("normalized_name") or "",
    )
    return finalize_equipment_image_prompt(base_prompt)


def build_master_ingredient_image_prompt(row, index):
    ingredient = {
        "ingredient": row.get("name") or row.get("normalized_name") or "",
        "purchasable_item": row.get("name") or row.get("normalized_name") or "",
    }
    return build_recipe_ingredient_image_prompt(
        recipe_title="Ingredient master data",
        servings="Not specified",
        ingredient_number=index,
        ingredient=ingredient,
    )


def build_master_image_prompt(record_type, row, index):
    if record_type == "equipment":
        return build_master_equipment_image_prompt(row, index)
    return build_master_ingredient_image_prompt(row, index)


def request_master_image_bytes(prompt, row, record_type="ingredients"):
    timeout_seconds = int(os.getenv("OPENAI_STEP_IMAGE_TIMEOUT_SECONDS", "90"))
    model = os.getenv("OPENAI_STEP_IMAGE_MODEL", "gpt-image-1")
    size = os.getenv("OPENAI_STEP_IMAGE_SIZE", "1024x1024")
    quality = os.getenv("OPENAI_STEP_IMAGE_QUALITY", "medium")

    client = get_openai_client()
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_seconds)

    response = throttled_image_generation(
        client,
        {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": 1,
        },
        action_name="recipe-step-image",
        model=model,
    )
    record_openai_usage(
        response,
        "recipe-step-image",
        model=model,
        metadata={
            "size": size,
            "quality": quality,
            "source": "recipe-master-data",
            "record_type": record_type,
            "record_id": int(row.get("id") or 0),
            "record_name": master_data.clean_text(row.get("name") or row.get("normalized_name")),
        },
        user_id=master_data.clean_text(row.get("user_id")),
    )

    image_record = first_openai_image_record(response)
    if not image_record:
        return b""

    b64_json = openai_image_field(image_record, "b64_json")
    if b64_json:
        encoded = str(b64_json).split(",", 1)[-1]
        return base64.b64decode(encoded)

    image_url = openai_image_field(image_record, "url")
    if image_url:
        result = requests.get(image_url, timeout=timeout_seconds)
        result.raise_for_status()
        return result.content

    return b""


def request_master_ingredient_image_bytes(prompt, row):
    return request_master_image_bytes(prompt, row, record_type="ingredients")


def save_master_record_image(row, image_bytes, record_type="ingredients"):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    record_id = int(row.get("id") or 0)
    label = master_image_type_label(record_type)
    name_key = safe_filename(row.get("normalized_name") or row.get("name") or label)[:60]
    filename = f"master_{label}_{record_id}_{name_key}_{uuid.uuid4().hex[:12]}.png"
    image_path = STEP_IMAGE_FOLDER / filename
    image_path.write_bytes(image_bytes)
    ensure_webp_variants(image_path)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}", str(image_path)


def save_master_ingredient_image(row, image_bytes):
    return save_master_record_image(row, image_bytes, record_type="ingredients")


def attach_master_record_image(row, image_url, image_path, record_type="ingredients"):
    if record_type not in SUPPORTED_MASTER_IMAGE_TYPES:
        raise ValueError("Unsupported master image record type.")

    now = master_data.utc_now_iso()
    with master_data.recipe_master_connection() as connection:
        existing = connection.execute(
            f"""
            SELECT image_url
              FROM {record_type}
             WHERE id = ?
               AND user_id = ?
            """,
            (int(row.get("id") or 0), row.get("user_id")),
        ).fetchone()
        if not existing:
            return False
        if master_data.clean_text(existing["image_url"]):
            return False
        connection.execute(
            f"""
            UPDATE {record_type}
               SET image_url = ?,
                   image_path = ?,
                   updated_at = ?
             WHERE id = ?
               AND user_id = ?
            """,
            (
                master_data.clean_text(image_url),
                master_data.clean_text(image_path),
                now,
                int(row.get("id") or 0),
                row.get("user_id"),
            ),
        )
    return True


def attach_master_ingredient_image(row, image_url, image_path):
    return attach_master_record_image(row, image_url, image_path, record_type="ingredients")


def generate_missing_master_images(
    job_id,
    record_type="ingredients",
    user_id=None,
    include_all_users=False,
    search=None,
    max_errors=10,
):
    try:
        rows = missing_master_image_rows(
            record_type=record_type,
            user_id=user_id,
            search=search,
            include_all_users=include_all_users,
        )
        update_master_image_progress(job_id, "started", {
            "total": len(rows),
            "record_type": record_type,
            "user_id": user_id,
            "include_all_users": include_all_users,
            "search": search,
        })
        if not rows:
            return master_image_progress(job_id)
        if not os.getenv("OPENAI_API_KEY"):
            update_master_image_progress(job_id, "failed", {"error": "OPENAI_API_KEY is not set."})
            return master_image_progress(job_id)

        for index, row in enumerate(rows, start=1):
            update_master_image_progress(job_id, "record_start", {"row": row})
            try:
                prompt = build_master_image_prompt(record_type, row, index)
                image_bytes = request_master_image_bytes(prompt, row, record_type=record_type)
                if not image_bytes:
                    raise RuntimeError("OpenAI returned no image bytes.")
                image_url, image_path = save_master_record_image(row, image_bytes, record_type=record_type)
                if attach_master_record_image(row, image_url, image_path, record_type=record_type):
                    update_master_image_progress(job_id, "record_done", {
                        "row": row,
                        "image_url": image_url,
                    })
                else:
                    update_master_image_progress(job_id, "record_skipped", {
                        "row": row,
                        "error": "The row already has an image or no longer exists.",
                    })
            except Exception as exc:
                update_master_image_progress(job_id, "record_failed", {
                    "row": row,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                progress = master_image_progress(job_id)
                if max_errors and int(progress.get("failed") or 0) >= int(max_errors):
                    update_master_image_progress(job_id, "failed", {
                        "error": f"Stopped after {int(progress.get('failed') or 0)} image failures.",
                    })
                    return master_image_progress(job_id)

        update_master_image_progress(job_id, "complete")
        return master_image_progress(job_id)
    except Exception as exc:
        update_master_image_progress(job_id, "failed", {"error": f"{type(exc).__name__}: {exc}"})
        return master_image_progress(job_id)


def start_master_image_generation_job(
    job_id,
    record_type="ingredients",
    user_id=None,
    include_all_users=False,
    search=None,
):
    start_master_image_progress(
        job_id,
        record_type=record_type,
        user_id=user_id,
        include_all_users=include_all_users,
        search=search,
    )
    worker = threading.Thread(
        target=generate_missing_master_images,
        kwargs={
            "job_id": job_id,
            "record_type": record_type,
            "user_id": user_id,
            "include_all_users": include_all_users,
            "search": search,
        },
        daemon=True,
    )
    worker.start()
    return master_image_progress(job_id)
