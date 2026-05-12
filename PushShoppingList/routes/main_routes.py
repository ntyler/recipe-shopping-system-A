from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request
from flask import render_template

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.home_address_service import save_home_address
from PushShoppingList.services.recipe_url_service import recipe_url_rows
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.shopping_list_service import save_items
from PushShoppingList.services.store_settings_service import load_store_settings

main_bp = Blueprint("main_bp", __name__)


DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k=",
        "urlStoreSelector": "https://info.aldi.us/stores",
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query=",
        "urlStoreSelector": "https://www.kroger.com/stores/search",
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q=",
        "urlStoreSelector": "https://www.walmart.com/",
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text=",
        "urlStoreSelector": "https://www.meijer.com/",
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm=",
        "urlStoreSelector": "https://www.target.com/store-locator/find-stores",
    },
    "costco": {
        "label": "Costco",
        "url": "https://www.costco.com/CatalogSearch?keyword=",
        "urlStoreSelector": "https://www.costco.com/s?keyword=&openFMW=true",
    },
}


def normalize(text):
    return " ".join(str(text).strip().lower().split())


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


@main_bp.route("/")
def index():
    items = load_items()
    store_settings = load_store_settings()

    return render_template(
        "index.html",
        message="",
        raw_items="\n".join(items),
        items=items,
        current_urls=recipe_url_rows(),
        home_address=load_home_address(),
        available_stores=store_settings["stores"],
        enabled_stores=store_settings["enabled_stores"],
        normalize=normalize,
        is_section_header=is_section_header,
    )


@main_bp.route("/clear", methods=["POST"])
def clear_list():
    save_items([])

    return redirect("/")


@main_bp.route("/save", methods=["POST"])
def save_list():
    raw_items = request.form.get("items", "")
    items = [
        line.strip()
        for line in raw_items.splitlines()
        if line.strip()
    ]

    save_items(items)

    return redirect("/")


@main_bp.route("/sort", methods=["POST"])
def sort_list():
    sort_ingredients()

    return redirect("/")


@main_bp.route("/save_home_address", methods=["POST"])
def save_home_address_route():
    saved_address = save_home_address(request.form)

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        return jsonify({
            "ok": True,
            "home_address": saved_address,
        })

    return redirect("/#home-address-section")
