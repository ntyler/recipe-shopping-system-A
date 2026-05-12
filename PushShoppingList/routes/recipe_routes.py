from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url
from PushShoppingList.services.shopping_list_service import add_items

recipe_bp = Blueprint("recipe_bp", __name__)


@recipe_bp.route("/extract_recipe", methods=["POST"])
def extract_recipe_route():
    recipe_urls = request.form.get("recipe_urls", "")

    urls = [
        line.strip()
        for line in recipe_urls.splitlines()
        if line.strip()
    ]

    for url in urls:
        result = extract_recipe_from_url(url)

        if result.get("ok"):
            add_items(result.get("ingredients", []))

    return redirect("/")


@recipe_bp.route("/api/extract_recipe", methods=["POST"])
def api_extract_recipe_route():
    data = request.get_json(force=True)
    url = str(data.get("url", "")).strip()

    result = extract_recipe_from_url(url)

    if result.get("ok"):
        add_items(result.get("ingredients", []))

    return jsonify(result)