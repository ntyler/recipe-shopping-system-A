"""Ingredient editor context and image previews; previews never update a record."""
from io import BytesIO

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from PIL import Image, ImageOps, UnidentifiedImageError

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_master_image_service as master_images
from PushShoppingList.services import ingredient_deletion_service as ingredient_deletion


def ingredient_editor_context(record):
    owner = record["user_id"]
    with master_data.existing_recipe_master_read_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, normalized_name FROM ingredients WHERE user_id = ? ORDER BY id", (owner,),
        ).fetchall()
        aliases = connection.execute(
            "SELECT ingredient_id, alias_name FROM ingredient_aliases WHERE user_id = ? ORDER BY normalized_alias", (owner,),
        ).fetchall()
    by_id = {row["id"]: {**dict(row), "aliases": []} for row in rows}
    for alias in aliases:
        if alias["ingredient_id"] in by_id:
            by_id[alias["ingredient_id"]]["aliases"].append(alias["alias_name"])
    usage = master_data.list_master_record_recipe_references("ingredients", record["id"], user_id=owner, limit=1)
    # Ingredients are created from workspace recipes, not a system seed registry.
    # Section classifier provenance describes assignment, not ingredient origin.
    source_label = "User-created" if owner and owner != master_data.LOCAL_USER_ID else "Workspace ingredient"
    deletion_details = ingredient_deletion.ingredient_deletion_details([record]).get(record["id"], {})
    return {
        "record": {
            key: record[key] for key in ("id", "name", "normalized_name", "store_section", "image_url", "updated_at")
        } | {
            "aliases": by_id[record["id"]]["aliases"],
            "source_label": source_label,
            "usage_count": usage["total"],
            "section_editable": True,
            **deletion_details,
        },
        "registry": list(by_id.values()),
        "sections": [{key: section[key] for key in ("section_key", "display_name", "icon")}
                     for section in master_data.ingredient_store_section_details(user_id=owner)],
    }


def _image_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="ingredient-editor-image-v1")


def prepare_ingredient_image(record, *, uploaded_file=None, generate=False):
    if generate:
        prompt = master_images.build_master_ingredient_image_prompt(record, 1)
        image_bytes = master_images.request_master_ingredient_image_bytes(prompt, record)
    elif uploaded_file:
        image_bytes = uploaded_file.read(10 * 1024 * 1024 + 1)
    else:
        raise ValueError("Choose an image to replace the current thumbnail.")
    if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
        raise ValueError("Choose an image of 10 MB or smaller.")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.width * image.height > 25_000_000:
                raise ValueError("Choose an image with no more than 25 million pixels.")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1600, 1600))
            output = BytesIO()
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(output, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Choose a valid PNG, JPG, WebP, GIF, BMP, or AVIF image.") from exc
    image_url, image_path = master_images.save_master_ingredient_image(record, output.getvalue())
    token = _image_serializer().dumps({
        "ingredient_id": record["id"], "user_id": record["user_id"],
        "image_url": image_url, "image_path": image_path,
    })
    return {"image_url": image_url, "token": token}


def resolve_ingredient_image(record, change):
    if change is None:
        return None
    if change == {"action": "remove"}:
        return {"image_url": "", "image_path": ""}
    if not isinstance(change, dict) or change.get("action") != "replace":
        raise ValueError("Choose a replacement image or Remove image.")
    try:
        preview = _image_serializer().loads(change.get("token", ""), max_age=86400)
    except (BadSignature, TypeError) as exc:
        raise ValueError("The image preview expired or is invalid. Choose the image again.") from exc
    if preview.get("ingredient_id") != record["id"] or preview.get("user_id") != record["user_id"]:
        raise ValueError("This image preview belongs to another ingredient.")
    return {key: preview[key] for key in ("image_url", "image_path")}
