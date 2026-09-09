"""Shared, validated image drafts. Only a row Save attaches a preview to a record."""
from io import BytesIO

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from PIL import Image, ImageOps, UnidentifiedImageError

from PushShoppingList.services import recipe_master_image_service as master_images


def _image_serializer(record_type):
    return URLSafeTimedSerializer(current_app.secret_key, salt=f"{master_images.master_image_type_label(record_type)}-editor-image-v1")


def prepare_master_image(record, *, record_type="ingredients", uploaded_file=None, generate=False):
    if record_type not in master_images.SUPPORTED_MASTER_IMAGE_TYPES:
        raise ValueError("Unsupported image record type.")
    if generate:
        prompt = master_images.build_master_image_prompt(record_type, record, 1)
        image_bytes = (master_images.request_master_ingredient_image_bytes(prompt, record)
                       if record_type == "ingredients" else master_images.request_master_image_bytes(prompt, record, record_type=record_type))
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
    image_url, image_path = master_images.save_master_record_image(record, output.getvalue(), record_type=record_type)
    token = _image_serializer(record_type).dumps({
        f"{master_images.master_image_type_label(record_type)}_id": record["id"], "user_id": record["user_id"],
        "image_url": image_url, "image_path": image_path,
    })
    return {"image_url": image_url, "token": token}


def resolve_master_image(record, change, *, record_type="ingredients"):
    if record_type not in master_images.SUPPORTED_MASTER_IMAGE_TYPES:
        raise ValueError("Unsupported image record type.")
    if change is None:
        return None
    if change == {"action": "remove"}:
        return {"image_url": "", "image_path": ""}
    if not isinstance(change, dict) or change.get("action") != "replace":
        raise ValueError("Choose a replacement image or Remove image.")
    try:
        preview = _image_serializer(record_type).loads(change.get("token", ""), max_age=86400)
    except (BadSignature, TypeError) as exc:
        raise ValueError("The image preview expired or is invalid. Choose the image again.") from exc
    if preview.get(f"{master_images.master_image_type_label(record_type)}_id") != record["id"] or preview.get("user_id") != record["user_id"]:
        raise ValueError(f"This image preview belongs to another {master_images.master_image_type_label(record_type)}.")
    return {key: preview[key] for key in ("image_url", "image_path")}
