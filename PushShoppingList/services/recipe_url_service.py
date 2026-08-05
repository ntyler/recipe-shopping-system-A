from pathlib import Path
import json
from fractions import Fraction
from threading import Lock
from urllib.parse import parse_qs
from urllib.parse import urlparse
from urllib.parse import urlunparse

from PushShoppingList.services.request_security_service import build_canonical_url
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.storage_service import guest_data_root
from PushShoppingList.services.storage_service import scoped_extractor_data_path
from PushShoppingList.services.storage_service import scoped_package_path
from PushShoppingList.services.storage_service import user_data_root


BASE_DIR = Path(__file__).resolve().parent.parent
URLS_FILE = scoped_package_path("urls.txt")
RECIPE_INGREDIENTS_FILE = scoped_extractor_data_path("recipe_ingredients.json")
url_file_lock = Lock()
RECIPE_INGREDIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _private_viewer_user_id(viewer_user_id=None):
    """Return a viewer assertion without using it as workspace authority."""

    if viewer_user_id is None:
        return str((current_user() or {}).get("user_id") or "")
    return str(viewer_user_id or "").strip()


def _private_recipe_url(path, *, viewer_user_id=None, **parameters):
    overrides = {
        "viewer_user_id": _private_viewer_user_id(viewer_user_id),
        **parameters,
    }
    return build_canonical_url(path, overrides=overrides)


def recipe_edit_page_url(recipe_url, viewer_user_id=None):
    """Build the canonical editor URL for the active registered viewer."""
    recipe_url = str(recipe_url or "").strip()
    if not recipe_url:
        return ""

    return _private_recipe_url(
        "/recipe/edit",
        viewer_user_id=viewer_user_id,
        url=recipe_url,
    )


def recipe_cover_image_url(recipe_url, *, variant="", version="", viewer_user_id=None):
    recipe_url = str(recipe_url or "").strip()
    if not recipe_url:
        return ""
    variant = str(variant or "").strip().lower()
    if variant == "original":
        variant = ""
    return _private_recipe_url(
        "/recipe_cover_image",
        viewer_user_id=viewer_user_id,
        url=recipe_url,
        variant=variant,
        v=str(version or "").strip(),
    )


def recipe_archive_pdf_url(
    recipe_url,
    *,
    kind="",
    download=False,
    version="",
    viewer_user_id=None,
):
    recipe_url = str(recipe_url or "").strip()
    if not recipe_url:
        return ""
    kind = str(kind or "").strip().lower()
    kind = (
        "generated_recipe"
        if kind in {
            "generated_recipe",
            "generated",
            "recipe",
            "clean",
            "clean_recipe",
            "generated-recipe",
        }
        else ""
    )
    return _private_recipe_url(
        "/recipe_archive_pdf",
        viewer_user_id=viewer_user_id,
        url=recipe_url,
        kind=kind,
        download="1" if download else "",
        v=str(version or "").strip(),
    )


def restaurant_source_logo_url(restaurant_id, *, version="", viewer_user_id=None):
    restaurant_id = str(restaurant_id or "").strip()
    if not restaurant_id:
        return ""
    return _private_recipe_url(
        "/restaurant_source_logo",
        viewer_user_id=viewer_user_id,
        restaurant_id=restaurant_id,
        v=str(version or "").strip(),
    )


def canonicalize_private_recipe_url(value, *, viewer_user_id=None):
    """Refresh a stored private recipe URL for the active resolved viewer."""

    value = str(value or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return value

    parameters = parse_qs(parsed.query, keep_blank_values=True)

    def first(name):
        values = parameters.get(name) or []
        return str(values[0] if values else "")

    if parsed.path == "/recipe/edit":
        return recipe_edit_page_url(
            first("url"),
            viewer_user_id=viewer_user_id,
        ) or value
    if parsed.path == "/recipe_cover_image":
        return recipe_cover_image_url(
            first("url"),
            variant=first("variant"),
            version=first("v"),
            viewer_user_id=viewer_user_id,
        ) or value
    if parsed.path == "/recipe_archive_pdf":
        return recipe_archive_pdf_url(
            first("url"),
            kind=first("kind") or first("pdf_kind"),
            download=first("download").strip().lower() in {"1", "true", "yes"},
            version=first("v"),
            viewer_user_id=viewer_user_id,
        ) or value
    if parsed.path == "/restaurant_source_logo":
        return restaurant_source_logo_url(
            first("restaurant_id"),
            version=first("v"),
            viewer_user_id=viewer_user_id,
        ) or value

    return value


def load_recipe_urls():
    return read_recipe_urls()


def read_recipe_urls_file(path):
    if not path.exists():
        return []

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_recipe_urls():
    return read_recipe_urls_file(URLS_FILE)


def load_recipe_urls_for_owner(user_id="", guest_session_id=""):
    guest_session_id = str(guest_session_id or "").strip()
    user_id = str(user_id or "").strip()

    if guest_session_id:
        return read_recipe_urls_file(guest_data_root(guest_session_id) / "urls.txt")
    if user_id:
        return read_recipe_urls_file(user_data_root(user_id) / "urls.txt")
    return load_recipe_urls()


def save_recipe_urls(urls):
    with url_file_lock:
        write_recipe_urls(urls)


def write_recipe_urls(urls):
    cleaned_urls = []
    seen = set()

    for url in urls:
        url = str(url or "").strip()
        key = normalize_recipe_url_key(url)

        if url and key not in seen:
            cleaned_urls.append(url)
            seen.add(key)

    URLS_FILE.write_text(
        "\n".join(cleaned_urls) + ("\n" if cleaned_urls else ""),
        encoding="utf-8",
    )


def add_recipe_urls(urls):
    with url_file_lock:
        write_recipe_urls(read_recipe_urls() + list(urls))


def remove_recipe_url(url):
    target = normalize_recipe_url_key(url)
    with url_file_lock:
        write_recipe_urls([
            existing_url
            for existing_url in read_recipe_urls()
            if normalize_recipe_url_key(existing_url) != target
        ])
        meta = load_recipe_url_meta()
        meta.pop(target, None)
        save_recipe_url_meta(meta)


def recipe_url_rows():
    meta = load_recipe_url_meta()
    return [
        {
            "url": url,
            "name": recipe_url_display_name(url, meta=meta),
            "type": recipe_url_type(url),
            "quantity": recipe_url_quantity(url, meta=meta),
        }
        for url in load_recipe_urls()
    ]


def recipe_url_type(url):
    value = str(url or "").strip().lower()

    if value.startswith("uploaded://"):
        return "File"

    if value.startswith("manual://"):
        return "Manual"

    return "URL"


def recipe_url_quantity(url, meta=None):
    key = normalize_recipe_url_key(url)
    meta = meta if isinstance(meta, dict) else load_recipe_url_meta()
    recipe_meta = meta.get(key, {})
    return normalize_recipe_quantity(recipe_meta.get("quantity", 1))


def recipe_url_display_name(url, meta=None):
    key = normalize_recipe_url_key(url)
    meta = meta if isinstance(meta, dict) else load_recipe_url_meta()
    recipe_meta = meta.get(key, {})
    custom_name = str(recipe_meta.get("name") or "").strip()

    return custom_name or recipe_url_name(url)


def save_recipe_url_name(url, name):
    key = normalize_recipe_url_key(url)
    name = str(name or "").strip()

    if not key:
        return load_recipe_url_meta()

    with url_file_lock:
        meta = load_recipe_url_meta()
        recipe_meta = meta.get(key, {})

        if name:
            recipe_meta["name"] = name
        else:
            recipe_meta.pop("name", None)

        meta[key] = recipe_meta
        save_recipe_url_meta(meta)
        return meta


def save_recipe_url_names(records):
    records = records if isinstance(records, list) else []
    cleaned_records = []
    for record in records:
        record = record if isinstance(record, dict) else {}
        url = str(record.get("url") or record.get("recipe_url") or "").strip()
        name = str(record.get("name") or record.get("display_name") or record.get("recipe_title") or "").strip()
        key = normalize_recipe_url_key(url)
        if key:
            cleaned_records.append((key, name))

    if not cleaned_records:
        return load_recipe_url_meta()

    with url_file_lock:
        meta = load_recipe_url_meta()
        for key, name in cleaned_records:
            recipe_meta = meta.get(key, {})
            if name:
                recipe_meta["name"] = name
            else:
                recipe_meta.pop("name", None)
            meta[key] = recipe_meta
        save_recipe_url_meta(meta)
        return meta


def save_recipe_url_quantity(url, quantity):
    key = normalize_recipe_url_key(url)

    if not key:
        return load_recipe_url_meta()

    with url_file_lock:
        meta = load_recipe_url_meta()
        recipe_meta = meta.get(key, {})
        recipe_meta["quantity"] = normalize_recipe_quantity(quantity)
        meta[key] = recipe_meta
        save_recipe_url_meta(meta)
        return meta


def load_recipe_url_meta():
    if not RECIPE_INGREDIENTS_FILE.exists():
        return {}

    try:
        data = json.loads(RECIPE_INGREDIENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def save_recipe_url_meta(meta):
    RECIPE_INGREDIENTS_FILE.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def normalize_recipe_quantity(quantity):
    if isinstance(quantity, (int, float)):
        value = float(quantity)
        if value <= 0:
            value = 1
        return int(value) if value.is_integer() else value

    text = str(quantity or "").strip().lower().replace("x", "")
    text = text.replace("×", "").strip()

    try:
        if "/" in text:
            value = float(Fraction(text.replace(" ", "")))
        else:
            value = float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        value = 1.0

    if value <= 0:
        value = 1.0

    return int(value) if value.is_integer() else value


def recipe_url_name(url):
    parsed = urlparse(url)
    path_name = parsed.path.strip("/").split("/")[-1]
    name = path_name or parsed.netloc or url
    return name.replace("-", " ").replace("_", " ").title()


def normalize_recipe_url_key(url):
    url = str(url or "").strip()

    if not url:
        return ""

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return url.rstrip("/")

    normalized_path = parsed.path.rstrip("/")
    normalized_query = parsed.query
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "instagram.com" in host and len(path_parts) >= 2 and path_parts[0].lower() in {"reel", "reels"}:
        normalized_path = f"/reel/{path_parts[1]}"
        normalized_query = ""
    elif "youtube.com" in host and len(path_parts) >= 2 and path_parts[0].lower() == "shorts":
        normalized_path = f"/shorts/{path_parts[1]}"
        normalized_query = ""
    elif "youtu.be" in host and path_parts:
        normalized_path = f"/{path_parts[0]}"
        normalized_query = ""

    return urlunparse((
        parsed.scheme.lower(),
        host,
        normalized_path,
        "",
        normalized_query,
        "",
    ))
