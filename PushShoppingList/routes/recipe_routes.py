from flask import Blueprint
from flask import redirect
from flask import request

from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url

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
        extract_recipe_from_url(url)

    return redirect("/")
