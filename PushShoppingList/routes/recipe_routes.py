from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

import subprocess
from pathlib import Path

recipe_bp = Blueprint("recipe_bp", __name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]

EXTRACT_SCRIPT = (
    PROJECT_DIR /
    "recipe-extractor" /
    "extract_recipes.py"
)

SORT_SCRIPT = (
    PROJECT_DIR /
    "PushShoppingList" /
    "scripts" /
    "sort_ingredients.py"
)

URLS_FILE = (
    PROJECT_DIR /
    "PushShoppingList" /
    "urls.txt"
)


@recipe_bp.route("/extract_recipe", methods=["POST"])
def extract_recipe_route():
    recipe_urls = request.form.get("recipe_urls", "")

    urls = [
        line.strip()
        for line in recipe_urls.splitlines()
        if line.strip()
    ]

    URLS_FILE.write_text(
        "\n".join(urls),
        encoding="utf-8",
    )

    subprocess.run(
        ["py", "-3.11", str(EXTRACT_SCRIPT)],
        cwd=str(PROJECT_DIR),
    )

    subprocess.run(
        ["py", "-3.11", str(SORT_SCRIPT)],
        cwd=str(PROJECT_DIR),
    )

    return redirect("/")


@recipe_bp.route("/api/extract_recipe", methods=["POST"])
def api_extract_recipe_route():
    data = request.get_json(force=True)

    url = str(data.get("url", "")).strip()

    URLS_FILE.write_text(
        url,
        encoding="utf-8",
    )

    subprocess.run(
        ["py", "-3.11", str(EXTRACT_SCRIPT)],
        cwd=str(PROJECT_DIR),
    )

    subprocess.run(
        ["py", "-3.11", str(SORT_SCRIPT)],
        cwd=str(PROJECT_DIR),
    )

    return jsonify({
        "ok": True,
    })