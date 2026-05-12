from flask import Blueprint
from flask import render_template

from PushShoppingList.services.shopping_list_service import load_items

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

    return render_template(
        "index.html",
        message="",
        raw_items="\n".join(items),
        items=items,
        current_urls=[],
        home_address={
            "street": "5905 Arlo Drive",
            "apartment": "Apt 2213",
            "city": "Indianapolis",
            "state": "IN",
            "zip": "46237",
            "full_address": "5905 Arlo Drive Apt 2213, Indianapolis, IN 46237",
        },
        available_stores=DEFAULT_STORES,
        enabled_stores=["meijer", "aldi"],
        normalize=normalize,
        is_section_header=is_section_header,
    )
