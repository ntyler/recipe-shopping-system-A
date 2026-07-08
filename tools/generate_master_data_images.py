#!/usr/bin/env python
"""Generate missing images for recipe master data records."""

import argparse
import base64
import os
import sys
import time
import uuid
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services.image_variant_service import ensure_webp_variants
from PushShoppingList.services.openai_throttle_service import throttled_image_generation
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.recipe_edit_service import STEP_IMAGE_FOLDER
from PushShoppingList.services.recipe_edit_service import STEP_IMAGE_URL_PREFIX
from PushShoppingList.services.recipe_edit_service import build_recipe_ingredient_image_prompt
from PushShoppingList.services.recipe_edit_service import first_openai_image_record
from PushShoppingList.services.recipe_edit_service import openai_image_field
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import safe_filename


SUPPORTED_RECORD_TYPES = {"ingredients"}


def load_env_file(env_file):
    env_path = Path(env_file)
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def missing_master_image_rows(user_id, record_type, limit=None, order_by="updated_at_desc"):
    if record_type not in SUPPORTED_RECORD_TYPES:
        raise ValueError("Only ingredient master image generation is supported.")

    order_clause = {
        "updated_at_desc": "m.updated_at DESC, m.id DESC",
        "usage_count_desc": "usage_count DESC, m.updated_at DESC, m.id DESC",
        "name_asc": "m.normalized_name ASC, m.name ASC, m.id ASC",
    }.get(order_by, "m.updated_at DESC, m.id DESC")
    limit_clause = ""
    params = [user_id]
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
              FROM ingredients m
              LEFT JOIN recipe_ingredients u
                ON u.ingredient_id = m.id
               AND u.user_id = m.user_id
             WHERE m.user_id = ?
               AND TRIM(COALESCE(m.image_url, '')) = ''
             GROUP BY m.id
             ORDER BY {order_clause}
             {limit_clause}
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


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


def request_master_image_bytes(prompt, user_id, record_id, record_name):
    timeout_seconds = int(os.getenv("OPENAI_STEP_IMAGE_TIMEOUT_SECONDS", "90"))
    model = os.getenv("OPENAI_STEP_IMAGE_MODEL", "gpt-image-1")
    size = os.getenv("OPENAI_STEP_IMAGE_SIZE", "1024x1024")
    quality = os.getenv("OPENAI_STEP_IMAGE_QUALITY", "medium")

    client = get_openai_client()
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_seconds)

    print(
        f"[OpenAI] action=recipe-master-ingredient-image model={model} "
        f"record_id={record_id} name={record_name}",
        flush=True,
    )
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
            "record_type": "ingredients",
            "record_id": record_id,
            "record_name": record_name,
        },
        user_id=user_id,
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


def save_master_ingredient_image(row, image_bytes):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    record_id = int(row.get("id") or 0)
    name_key = safe_filename(row.get("normalized_name") or row.get("name") or "ingredient")[:60]
    filename = f"master_ingredient_{record_id}_{name_key}_{uuid.uuid4().hex[:12]}.png"
    image_path = STEP_IMAGE_FOLDER / filename
    image_path.write_bytes(image_bytes)
    ensure_webp_variants(image_path)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}", str(image_path)


def attach_master_image(row, image_url, image_path):
    now = master_data.utc_now_iso()
    with master_data.recipe_master_connection() as connection:
        existing = connection.execute(
            """
            SELECT image_url
              FROM ingredients
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
            """
            UPDATE ingredients
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


def generate_missing_images(args):
    load_env_file(args.env_file)
    user_id = master_data.clean_text(args.user_id)
    if not user_id:
        raise SystemExit("--user-id is required.")

    rows = missing_master_image_rows(
        user_id,
        args.record_type,
        limit=args.limit,
        order_by=args.order_by,
    )
    print(
        f"Found {len(rows)} missing {args.record_type} images for user_id={user_id}.",
        flush=True,
    )

    if args.dry_run:
        for row in rows:
            print(
                f"DRY-RUN id={row['id']} usage={int(row['usage_count'] or 0)} name={row['name']}",
                flush=True,
            )
        return {"generated": 0, "failed": 0, "skipped": len(rows)}

    if rows and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set.")

    generated = 0
    failed = 0
    skipped = 0
    for index, row in enumerate(rows, start=1):
        record_id = int(row.get("id") or 0)
        record_name = master_data.clean_text(row.get("name") or row.get("normalized_name"))
        try:
            prompt = build_master_ingredient_image_prompt(row, index)
            image_bytes = request_master_image_bytes(prompt, user_id, record_id, record_name)
            if not image_bytes:
                raise RuntimeError("OpenAI returned no image bytes.")
            image_url, image_path = save_master_ingredient_image(row, image_bytes)
            if attach_master_image(row, image_url, image_path):
                generated += 1
                print(
                    f"OK {generated}/{len(rows)} id={record_id} name={record_name} url={image_url}",
                    flush=True,
                )
            else:
                skipped += 1
                print(
                    f"SKIP id={record_id} name={record_name} reason=row already has image or is missing",
                    flush=True,
                )
        except Exception as exc:
            failed += 1
            print(
                f"FAIL id={record_id} name={record_name} error={type(exc).__name__}: {exc}",
                flush=True,
            )
            if args.max_errors and failed >= args.max_errors:
                print(f"Stopping after {failed} failures.", flush=True)
                break
        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    print(
        f"Done. generated={generated} failed={failed} skipped={skipped} remaining={len(missing_master_image_rows(user_id, args.record_type))}",
        flush=True,
    )
    return {"generated": generated, "failed": failed, "skipped": skipped}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="Recipe master user id to update.")
    parser.add_argument("--record-type", default="ingredients", choices=sorted(SUPPORTED_RECORD_TYPES))
    parser.add_argument("--order-by", default="updated_at_desc", choices=["updated_at_desc", "usage_count_desc", "name_asc"])
    parser.add_argument("--limit", type=int, default=0, help="Maximum missing rows to process; 0 means all.")
    parser.add_argument("--delay-seconds", type=float, default=0.0, help="Optional delay between image requests.")
    parser.add_argument("--max-errors", type=int, default=10, help="Stop after this many failures; 0 disables the cap.")
    parser.add_argument("--env-file", default=".env", help="Optional env file to load if variables are missing.")
    parser.add_argument("--dry-run", action="store_true", help="List missing records without generating images.")
    args = parser.parse_args()
    if args.limit <= 0:
        args.limit = None
    return args


if __name__ == "__main__":
    generate_missing_images(parse_args())
