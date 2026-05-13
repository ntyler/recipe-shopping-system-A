from pathlib import Path
import json
from threading import Lock
from urllib.parse import urlparse
from urllib.parse import urlunparse


BASE_DIR = Path(__file__).resolve().parent.parent
URLS_FILE = BASE_DIR / "urls.txt"
RECIPE_INGREDIENTS_FILE = BASE_DIR / "services" / "recipe-extractor" / "data" / "recipe_ingredients.json"
url_file_lock = Lock()
RECIPE_INGREDIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_recipe_urls():
    return read_recipe_urls()


def read_recipe_urls():
    if not URLS_FILE.exists():
        return []

    return [
        line.strip()
        for line in URLS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
    return [
        {
            "url": url,
            "name": recipe_url_name(url),
            "quantity": recipe_url_quantity(url),
        }
        for url in load_recipe_urls()
    ]


def recipe_url_quantity(url):
    key = normalize_recipe_url_key(url)
    meta = load_recipe_url_meta()
    recipe_meta = meta.get(key, {})
    return normalize_recipe_quantity(recipe_meta.get("quantity", 1))


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
    try:
        value = int(quantity)
    except (TypeError, ValueError):
        value = 1

    return max(1, value)


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

    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        normalized_path,
        "",
        parsed.query,
        "",
    ))
