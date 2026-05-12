from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from pathlib import Path

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url
from PushShoppingList.services.shopping_list_service import add_items

recipe_bp = Blueprint("recipe_bp", __name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]

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

    extracted_any = False

    for url in urls:
        result = extract_recipe_from_url(url)

        if result.get("ok"):
            add_items(result.get("ingredients", []))
            extracted_any = True

    if extracted_any:
        sort_ingredients()

    return redirect("/")


@recipe_bp.route("/api/extract_recipe", methods=["POST"])
def api_extract_recipe_route():
    data = request.get_json(force=True)

    url = str(data.get("url", "")).strip()

    URLS_FILE.write_text(
        url,
        encoding="utf-8",
    )

    result = extract_recipe_from_url(url)

    if not result.get("ok"):
        return jsonify(result), 400

    add_items(result.get("ingredients", []))
    sort_ingredients()

    return jsonify(result)
