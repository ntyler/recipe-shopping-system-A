import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from PIL import ImageOps


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
GENERATED_STATIC_PREFIX = "/static/generated/"

IMAGE_VARIANTS = {
    "thumb": {"max_size": (240, 240), "width": 240, "quality": 72},
    "card": {"max_size": (640, 640), "width": 640, "quality": 78},
    "detail": {"max_size": (1280, 1280), "width": 1280, "quality": 82},
}

VARIANT_SUFFIX_SEPARATOR = "__"


def generated_static_cache_seconds():
    return 31536000


def is_cacheable_generated_static_path(path):
    return str(path or "").startswith(GENERATED_STATIC_PREFIX)


def local_static_image_path(image_url):
    parsed = urlsplit(str(image_url or ""))
    path = parsed.path

    if not path.startswith("/static/"):
        return None

    relative = Path(*path[len("/static/"):].split("/"))
    candidate = STATIC_DIR / relative

    try:
        candidate = candidate.resolve()
        base = STATIC_DIR.resolve()
    except OSError:
        return None

    if candidate != base and base not in candidate.parents:
        return None

    if not candidate.is_file():
        return None

    return candidate


def webp_variant_path(image_path, variant):
    spec = IMAGE_VARIANTS.get(str(variant or ""))

    if not spec:
        return None

    image_path = Path(image_path)
    suffix = f"{VARIANT_SUFFIX_SEPARATOR}{variant}.webp"

    if image_path.name.endswith(tuple(
        f"{VARIANT_SUFFIX_SEPARATOR}{name}.webp"
        for name in IMAGE_VARIANTS
    )):
        return None

    return image_path.with_name(f"{image_path.stem}{suffix}")


def ensure_webp_variant(image_path, variant):
    image_path = Path(image_path)
    spec = IMAGE_VARIANTS.get(str(variant or ""))

    if not spec or not image_path.is_file():
        return None

    variant_path = webp_variant_path(image_path, variant)
    if not variant_path:
        return None

    try:
        if (
            variant_path.is_file()
            and variant_path.stat().st_mtime >= image_path.stat().st_mtime
            and variant_path.stat().st_size > 0
        ):
            return variant_path
    except OSError:
        return None

    try:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image)
            if getattr(image, "is_animated", False):
                return None

            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

            image.thumbnail(spec["max_size"], Image.Resampling.LANCZOS)
            variant_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(
                variant_path,
                "WEBP",
                quality=spec["quality"],
                method=6,
                optimize=True,
            )
    except Exception:
        return None

    return variant_path if variant_path.is_file() else None


def ensure_webp_variants(image_path, variants=None):
    variants = variants or IMAGE_VARIANTS.keys()
    created = {}

    for variant in variants:
        variant_path = ensure_webp_variant(image_path, variant)
        if variant_path:
            created[variant] = variant_path

    return created


def static_url_for_path(image_path):
    image_path = Path(image_path)

    try:
        relative = image_path.resolve().relative_to(STATIC_DIR.resolve())
    except ValueError:
        return ""

    return "/static/" + str(relative).replace("\\", "/")


def image_cache_version(image_path):
    try:
        stat = Path(image_path).stat()
    except OSError:
        return ""

    return f"{int(stat.st_mtime)}-{stat.st_size}"


def local_static_image_variants(image_url, variants=None):
    image_path = local_static_image_path(image_url)

    if not image_path:
        return {}

    variant_paths = ensure_webp_variants(image_path, variants=variants)
    variants = {
        name: static_url_for_path(path)
        for name, path in variant_paths.items()
    }
    return image_variant_payload(str(image_url), variants)


def image_variant_payload(original_url, variants):
    variants = variants if isinstance(variants, dict) else {}
    srcset_parts = []

    for name in ("thumb", "card", "detail"):
        variant_url = variants.get(name)
        spec = IMAGE_VARIANTS.get(name, {})
        if variant_url and spec.get("width"):
            srcset_parts.append(f"{variant_url} {spec['width']}w")

    return {
        "thumb_url": variants.get("thumb", ""),
        "card_url": variants.get("card", ""),
        "detail_url": variants.get("detail", ""),
        "display_url": variants.get("card") or variants.get("thumb") or original_url,
        "srcset": ", ".join(srcset_parts),
        "full_url": original_url,
    }


def cover_image_variant_payload(original_url, image_path, variant_url_builder, variants=None):
    image_path = Path(image_path) if image_path else None

    if not image_path or not image_path.is_file():
        return image_variant_payload(original_url, {})

    variant_paths = ensure_webp_variants(image_path, variants=variants)
    version = image_cache_version(image_path)
    variants = {
        name: variant_url_builder(name, version)
        for name in variant_paths
    }
    return image_variant_payload(original_url, variants)


def image_mimetype_for_path(image_path):
    guessed = mimetypes.guess_type(str(image_path or ""))[0]
    return guessed or "application/octet-stream"
