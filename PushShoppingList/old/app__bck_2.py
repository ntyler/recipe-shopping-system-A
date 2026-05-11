from flask import Flask, request, redirect, render_template_string
from pathlib import Path
import subprocess
import threading
import json
import requests
import sys
import traceback
import uuid
import re
import os

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Make imports work whether app.py lives in PushShoppingList or project root.
for import_path in [BASE_DIR, PROJECT_ROOT]:
    import_path_text = str(import_path)
    if import_path_text not in sys.path:
        sys.path.insert(0, import_path_text)

try:
    import grab_best_products as gbp
except Exception as import_error:
    gbp = None
    print(f"Could not import grab_best_products.py: {import_error}")

try:
    from store_product_scraper import (
        run_scraper,
        scrape_store_searches_parallel,
        scrape_all_stores,
    )
except Exception as import_error:
    run_scraper = None
    scrape_store_searches_parallel = None
    scrape_all_stores = None
    print(f"Could not import store_product_scraper.py: {import_error}")


SHOPPING_LIST_FILE = BASE_DIR / "shopping_list.txt"
ITEM_SOURCES_FILE = BASE_DIR / "shopping_item_sources.json"
ITEM_STATE_FILE = BASE_DIR / "shopping_item_state.json"
RECIPE_DETAILS_FILE = BASE_DIR / "recipe_details.json"

URL_HISTORY_FILE = BASE_DIR / "url_history_log.txt"
CURRENT_URL_LOG_FILE = BASE_DIR / "current_url_log.txt"

EXTRACTOR_FILE = BASE_DIR.parent / "recipe-extractor" / "extract_recipe_ingredients.py"
FIND_NEAREST_STORES_FILE = PROJECT_ROOT / "find_nearest_stores.py"
EXTRACTOR_FOLDER = EXTRACTOR_FILE.parent
URLS_FILE = EXTRACTOR_FOLDER / "urls.txt"
OUTPUT_FOLDER = EXTRACTOR_FOLDER / "data" / "output"

STORE_SETTINGS_FILE = BASE_DIR / "shopping_store_settings.json"
STORES_FILE = BASE_DIR / "shopping_stores.json"
STORE_RESULTS_FILE = BASE_DIR / "shopping_stores_Results.json"
PRODUCT_CHOICES_FILE = BASE_DIR / "shopping_product_choices.json"
ACTIVE_BULK_JOB_FILE = BASE_DIR / "active_bulk_job.txt"
ACTIVE_EXTRACT_JOB_FILE = BASE_DIR / "active_extract_job.txt"
ACTIVE_NEAREST_STORES_JOB_FILE = BASE_DIR / "active_nearest_stores_job.txt"

DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k=",
        "urlStoreSelector": "https://info.aldi.us/stores"
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query=",
        "urlStoreSelector": "https://www.kroger.com/stores/search"
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q=",
        "urlStoreSelector": "https://www.walmart.com/"
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text=",
        "urlStoreSelector": "https://www.meijer.com/"
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm=",
        "urlStoreSelector": "https://www.target.com/store-locator/find-stores"
    },
    "costco": {
        "label": "Costco",
        "url": "https://www.costco.com/CatalogSearch?keyword=",
        "urlStoreSelector": "https://www.costco.com/s?keyword=&openFMW=true"
    }
}

DEFAULT_ENABLED_STORES = ["meijer", "aldi"]

NTFY_TOPIC = "nathaniel-shopping-list-12345"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

file_lock = threading.Lock()

bulk_product_lock = threading.Lock()
bulk_product_jobs = {}

extract_lock = threading.Lock()
extract_jobs = {}

nearest_stores_lock = threading.Lock()
nearest_stores_jobs = {}


SECTION_ORDER = {
    "PRODUCE": 1,
    "DAIRY": 2,
    "DRY GOODS": 3,
    "CANNED": 4,
    "BEVERAGES": 5,
    "SPICES": 6,
    "OILS": 7,
    "BAKERY": 8,
    "MISC": 9,
}

STORE_ORDER = list(DEFAULT_STORES.keys()) + ["unselected"]

DEFAULT_ITEMS = []

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Shopping List</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
        body {
            font-family: Arial;
            padding: 16px;
            background: #111;
            color: white;
        }

        h1, h2 {
            text-align: center;
        }

        textarea {
            width: 100%;
            height: 160px;
            font-size: 16px;
            padding: 10px;
            border-radius: 8px;
            box-sizing: border-box;
            background: #333;
            color: white;
        }

        .box,
        .app-card,
        .recipe-card {
            max-width: 900px;
            margin: 0 auto 18px auto;
            padding: 22px;
            border-radius: 12px;
            background: #1b1b1b;
            border: 1px solid #2d2d2d;
            box-shadow: 0 8px 24px rgba(0,0,0,0.35);
            box-sizing: border-box;
        }

        .app-card h2,
        .recipe-card h2 {
            margin-top: 0;
            margin-bottom: 14px;
        }

        .recipe-card h2 {
            margin-bottom: 6px;
        }

        .helper-text {
            text-align: center;
            color: #aaa;
            margin-top: 0;
            margin-bottom: 14px;
            font-size: 14px;
        }

        .recipe-url-box,
        .edit-items-box {
            background: #202425;
            border: 1px solid #555;
            color: #fff;
            border-radius: 10px;
            padding: 14px;
            line-height: 1.5;
            resize: vertical;
            outline: none;
            box-sizing: border-box;
        }

        .recipe-url-box {
            height: 120px;
        }

        .edit-items-box {
            min-height: 180px;
        }

        .recipe-url-box:focus,
        .edit-items-box:focus {
            border-color: #00cc66;
            box-shadow: 0 0 0 3px rgba(0,204,102,0.18);
        }

        .recipe-url-box::placeholder {
            color: #888;
            opacity: 1;
        }

        button {
            width: 100%;
            padding: 14px;
            margin-top: 10px;
            font-size: 18px;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
        }

        .extract-btn { background: #107C10; }
        .save-btn { background: #0078D7; }
        .sort-btn { background: #6a00cc; }
        .clear-btn { background: #cc0000; }
        .reset-checks-btn { background: #444; }
        .reset-stores-btn { background: #8a5a00; }



        .store-manager-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-top: 12px;
        }

        .store-manager-row {
            display: grid;
            grid-template-columns: 34px minmax(100px, 140px) minmax(0, 1fr) 70px 78px;
            gap: 10px;
            align-items: center;
            background: #202425;
            border: 1px solid #444;
            border-radius: 10px;
            padding: 10px;
        }

        .store-manager-row input[type="checkbox"] {
            transform: scale(1.2);
            cursor: pointer;
        }

        .store-manager-label {
            color: #fff;
            font-weight: bold;
        }

        .store-manager-url {
            color: #aaa;
            font-size: 12px;
            word-break: break-all;
        }

        .store-location-details {
            grid-column: 2 / 6;
            background: #181b1c;
            border: 1px solid #333;
            border-radius: 9px;
            padding: 9px 10px;
            font-size: 12px;
            line-height: 1.45;
            color: #bbb;
        }

        .store-detail-line {
            margin-top: 3px;
        }

        .store-detail-label {
            color: #888;
            font-weight: bold;
            text-transform: uppercase;
            font-size: 10px;
            letter-spacing: 0.04em;
            margin-right: 5px;
        }

        .store-detail-link {
            color: #7dd3fc;
            text-decoration: none;
            word-break: break-word;
        }

        .store-detail-link:hover {
            color: #38bdf8;
            text-decoration: underline;
        }

        .store-choice-toggle {
            width: auto;
            margin-top: 6px;
            padding: 5px 9px;
            font-size: 12px;
            background: #333;
            border-radius: 6px;
        }

        .store-candidate-list {
            display: none;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #333;
        }

        .store-candidate-list.open {
            display: block;
        }

        .store-candidate-item {
            padding: 6px 0;
            border-bottom: 1px solid #252525;
        }

        .store-candidate-item:last-child {
            border-bottom: none;
        }

        .store-candidate-form {
            margin: 0;
        }

        .store-candidate-select-btn {
            width: 100%;
            margin-top: 0;
            padding: 8px 9px;
            background: #202425;
            border: 1px solid #444;
            border-radius: 8px;
            text-align: left;
            font-size: 12px;
            color: #ddd;
            display: block;
        }

        .store-candidate-select-btn:hover {
            background: #263033;
            border-color: #777;
        }

        .store-candidate-select-btn.selected {
            background: #12351f;
            border-color: #22c55e;
            box-shadow: 0 0 0 1px rgba(34,197,94,0.35);
        }

        .store-candidate-top-line {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            flex-wrap: wrap;
        }

        .store-selected-badge {
            color: #86efac;
            font-weight: bold;
            font-size: 11px;
            white-space: nowrap;
        }

        .store-candidate-actions {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 74px;
            gap: 8px;
            align-items: stretch;
        }

        .store-candidate-edit-btn {
            width: 100%;
            margin-top: 0;
            padding: 8px 9px;
            font-size: 12px;
            background: #3a3f45;
            border: 1px solid #444;
            border-radius: 8px;
        }

        .store-candidate-edit-btn:hover {
            background: #4b5563;
        }

        .store-candidate-edit-form {
            display: none;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-top: 8px;
            padding: 10px;
            border: 1px solid #333;
            border-radius: 8px;
            background: #151818;
        }

        .store-candidate-edit-form.open {
            display: grid;
        }

        .store-candidate-edit-field {
            display: flex;
            flex-direction: column;
            gap: 4px;
            color: #aaa;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .store-candidate-edit-field.full-width {
            grid-column: 1 / -1;
        }

        .store-candidate-edit-field input {
            width: 100%;
            box-sizing: border-box;
            background: #202425;
            color: #fff;
            border: 1px solid #555;
            border-radius: 7px;
            padding: 8px 9px;
            font-size: 12px;
            text-transform: none;
            letter-spacing: 0;
        }

        .store-candidate-save-btn {
            grid-column: 1 / -1;
            width: 100%;
            margin-top: 0;
            padding: 9px 10px;
            font-size: 13px;
            background: #107C10;
        }

        .store-delete-btn {
            width: auto;
            margin-top: 0;
            padding: 7px 10px;
            font-size: 12px;
            background: #7f1d1d;
        }

        .store-edit-btn {
            width: auto;
            margin-top: 0;
            padding: 7px 10px;
            font-size: 12px;
            background: #444;
        }

        .store-edit-btn:hover {
            background: #666;
        }

        .store-edit-form {
            display: none;
            grid-template-columns: minmax(120px, 160px) minmax(140px, 180px) minmax(220px, 1fr) minmax(220px, 1fr) 110px;
            gap: 10px;
            align-items: end;
            background: #181818;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 10px;
            margin: -6px 0 10px 0;
        }

        .store-edit-form.open {
            display: grid;
        }

        .store-edit-field {
            display: flex;
            flex-direction: column;
            gap: 4px;
            color: #aaa;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .store-edit-field input {
            width: 100%;
            box-sizing: border-box;
            background: #202425;
            color: #fff;
            border: 1px solid #555;
            border-radius: 7px;
            padding: 8px 9px;
            font-size: 13px;
            text-transform: none;
            letter-spacing: 0;
        }

        .store-edit-field input::placeholder {
            color: #777;
        }

        .store-edit-save-btn {
            width: 100%;
            margin-top: 0;
            padding: 9px 12px;
            font-size: 13px;
            background: #107C10;
        }

        .add-store-grid {
            display: grid;
            grid-template-columns: minmax(100px, 150px) minmax(120px, 1fr) minmax(150px, 1.3fr) minmax(150px, 1.3fr);
            gap: 10px;
            margin-top: 12px;
        }

        .add-store-grid input {
            width: 100%;
            box-sizing: border-box;
            background: #202425;
            color: #fff;
            border: 1px solid #555;
            border-radius: 8px;
            padding: 11px 12px;
            font-size: 15px;
            outline: none;
        }

        .add-store-grid input:focus {
            border-color: #00cc66;
            box-shadow: 0 0 0 3px rgba(0,204,102,0.16);
        }

        .add-store-help {
            color: #aaa;
            font-size: 12px;
            margin-top: 8px;
            text-align: center;
            line-height: 1.35;
        }

        .address-grid {
            display: grid;
            grid-template-columns: minmax(160px, 1.2fr) minmax(120px, 0.8fr) minmax(150px, 1fr) 80px 100px;
            gap: 10px;
            margin-top: 12px;
        }

        .address-grid input {
            width: 100%;
            box-sizing: border-box;
            background: #202425;
            color: #fff;
            border: 1px solid #555;
            border-radius: 8px;
            padding: 11px 12px;
            font-size: 15px;
            outline: none;
        }

        .address-grid input:focus {
            border-color: #00cc66;
            box-shadow: 0 0 0 3px rgba(0,204,102,0.16);
        }

        .address-actions-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 12px;
        }

        .address-save-btn {
            background: #0078D7;
            margin-top: 0;
        }

        .nearest-stores-btn {
            background: #0f766e;
            margin-top: 0;
        }

        .address-summary-box {
            margin-top: 12px;
            background: #181b1c;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 12px 14px;
            color: #ddd;
            font-size: 14px;
            line-height: 1.45;
            text-align: center;
        }

        .store-options-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 10px;
            margin-top: 10px;
        }

        .store-option-label {
            display: flex;
            align-items: center;
            gap: 8px;
            background: #202425;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 10px;
            color: #ddd;
            cursor: pointer;
        }

        .store-option-label input {
            transform: scale(1.15);
            cursor: pointer;
        }

        .store-save-btn {
            background: #0078D7;
        }

        .actions-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 10px;
        }

        .actions-grid form {
            margin: 0;
        }

        .actions-grid button {
            margin-top: 0;
        }


        .view-control-section {
            margin-top: 16px;
            padding-top: 14px;
            border-top: 1px solid #333;
        }

        .view-control-section:first-of-type {
            margin-top: 10px;
            padding-top: 0;
            border-top: none;
        }

        .view-control-title {
            color: #aaa;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 8px;
            text-align: center;
        }

        .view-control-row {
            display: flex;
            gap: 10px;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
        }

        .view-toggle-box {
            margin-top: 0;
        }

        .behavior-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 15px;
            color: #ddd;
            background: #202425;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 10px 12px;
            cursor: pointer;
        }

        .behavior-toggle input {
            transform: scale(1.15);
            cursor: pointer;
        }

        .view-action-btn {
            width: auto;
            min-width: 190px;
            margin-top: 0;
            padding: 11px 16px;
            font-size: 15px;
        }

        .view-action-form {
            margin: 0;
        }

        .view-settings-card {
            text-align: center;
        }

        .view-toggle-box {
            display: flex;
            gap: 10px;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            margin-top: 10px;
        }

        .view-toggle-btn {
            width: auto;
            padding: 10px 18px;
            font-size: 15px;
            background: #333;
            margin-top: 0;
        }

        .view-toggle-btn.active {
            background: #0078D7;
            font-weight: bold;
        }


        .show-item-buttons-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: 16px;
            font-size: 15px;
            color: #ddd;
        }

        .show-item-buttons-toggle input {
            transform: scale(1.2);
            cursor: pointer;
        }

        body.hide-item-buttons .item-actions {
            display: none !important;
        }

        body.hide-best-product .product-link-line {
            display: none !important;
        }

        body.hide-checked-items .row.row-checked {
            display: none !important;
        }

        body.compact-mode .source-line {
            display: none !important;
        }

        body.compact-mode .row {
            padding: 7px 10px;
            margin-top: 6px;
        }

        body.compact-mode .item-actions {
            margin-top: 6px;
        }

        .collapsible-header {
            cursor: pointer;
            user-select: none;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        .collapsible-header:hover {
            filter: brightness(1.15);
        }

        .header-title {
            min-width: 0;
        }

        .header-count {
            color: #aaa;
            font-size: 14px;
            margin-left: 6px;
            font-weight: normal;
        }

        .header-toggle-icon {
            color: #aaa;
            font-size: 13px;
            white-space: nowrap;
            font-weight: normal;
        }

        .collapsed-by-header {
            display: none !important;
        }

        .open-url-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: 16px;
            font-size: 15px;
            color: #ddd;
        }

        .open-url-toggle input {
            transform: scale(1.2);
            cursor: pointer;
        }

        .row {
            display: flex;
            background: #222;
            margin: 10px auto 0 auto;
            padding: 10px;
            border-radius: 8px;
            align-items: flex-start;
            max-width: 900px;
            box-sizing: border-box;
        }

        .section-header-row {
            position: sticky;
            top: 0;
            z-index: 40;
            max-width: 900px;
            margin: 24px auto 8px auto;
            padding: 10px 8px;
            font-size: 20px;
            font-weight: bold;
            color: #00cc66;
            background: #111;
            border-bottom: 1px solid #333;
            text-transform: uppercase;
            box-sizing: border-box;
            box-shadow: 0 2px 8px rgba(0,0,0,0.45);
        }

        .store-header-row {
            position: sticky;
            top: 0;
            z-index: 45;
            max-width: 900px;
            margin: 28px auto 8px auto;
            padding: 12px 8px;
            font-size: 24px;
            font-weight: bold;
            color: #4da3ff;
            background: #111;
            border-bottom: 2px solid #333;
            text-transform: uppercase;
            box-sizing: border-box;
            box-shadow: 0 2px 8px rgba(0,0,0,0.45);
        }

        .store-section-header {
            max-width: 900px;
            margin: 18px auto 8px auto;
            padding: 8px;
            font-size: 18px;
            font-weight: bold;
            color: #00cc66;
            border-bottom: 1px solid #333;
            text-transform: uppercase;
            box-sizing: border-box;
        }

        .recipe-view-card .store-section-header {
            margin-left: 0;
            margin-right: 0;
        }

        .items-title {
            max-width: 900px;
            margin: 0 auto 10px auto;
        }

        .recipe-view-card {
            max-width: 900px;
            margin: 12px auto 18px auto;
            padding: 16px;
            background: #1b1b1b;
            border: 1px solid #2d2d2d;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.25);
            box-sizing: border-box;
        }

        .recipe-view-title {
            position: sticky;
            top: 0;
            z-index: 20;
            background: #1b1b1b;
            color: #00cc66;
            font-weight: bold;
            margin: -16px -16px 12px -16px;
            padding: 14px 16px;
            font-size: 18px;
            border-bottom: 1px solid #333;
            border-radius: 12px 12px 0 0;
        }

        .recipe-view-title a {
            color: #ddd;
            text-decoration: none;
        }

        .recipe-view-title a:hover {
            color: #00cc66;
            text-decoration: underline;
        }

        .recipe-meta {
            color: #aaa;
            margin: 4px 0 12px 0;
            font-size: 14px;
        }

        .recipe-detail-box {
            background: #202425;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 12px 14px;
            margin: 12px 0;
        }

        .recipe-divider {
            height: 1px;
            background: #333;
            margin: 12px 0;
        }

        .recipe-detail-title {
            color: #4da3ff;
            font-weight: bold;
            font-size: 16px;
            margin-bottom: 8px;
        }

        .recipe-detail-list {
            margin: 0;
            padding-left: 22px;
            color: #ddd;
            line-height: 1.45;
        }

        .recipe-detail-list li {
            margin-bottom: 6px;
        }

        .recipe-task-row {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            margin-bottom: 8px;
        }

        .recipe-task-check {
            margin-top: 3px;
            transform: scale(1.15);
            cursor: pointer;
            flex: 0 0 auto;
        }

        .recipe-task-text.done {
            text-decoration: line-through;
            color: #777;
        }

        .recipe-detail-muted {
            color: #888;
            font-size: 13px;
        }

        .nutrition-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-top: 6px;
        }

        .nutrition-item {
            background: #181818;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 14px;
        }

        .nutrition-label {
            color: #aaa;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .nutrition-value {
            color: #fff;
            font-weight: bold;
            margin-top: 3px;
        }

        .detail-toggle,
        .nutrition-toggle {
            width: 100%;
            margin-top: 0;
            padding: 10px 12px;
            background: #181818;
            border: 1px solid #333;
            border-radius: 8px;
            color: #4da3ff;
            font-size: 16px;
            font-weight: bold;
            text-align: left;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .card-collapse-toggle {
            width: 100%;
            margin-top: 0;
            padding: 12px 14px;
            background: #181818;
            border: 1px solid #333;
            border-radius: 8px;
            color: #fff;
            font-size: 22px;
            font-weight: bold;
            text-align: left;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-sizing: border-box;
        }

        .card-collapse-toggle:hover {
            background: #222;
        }

        .card-collapse-icon {
            color: #aaa;
            font-size: 14px;
            font-weight: normal;
        }

        .card-collapse-content {
            margin-top: 12px;
        }

        .card-collapse-content.collapsed {
            display: none;
        }

        .detail-toggle:hover,
        .nutrition-toggle:hover {
            background: #222;
        }

        .detail-toggle-icon,
        .nutrition-toggle-icon {
            color: #aaa;
            font-size: 14px;
        }

        .detail-content,
        .nutrition-content {
            margin-top: 10px;
        }

        .detail-content.collapsed,
        .nutrition-content.collapsed {
            display: none;
        }

        .recipe-view-card .row {
            margin-left: 0;
            margin-right: 0;
        }

        .item { flex: 1; width: 100%; }

        .item-actions {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: 8px;
            flex-wrap: wrap;
            width: 100%;
            margin-top: 10px;
            margin-left: 30px;
            box-sizing: border-box;
        }

        .item-actions form {
            margin: 0;
        }

        .row {
            flex-direction: column;
        }

        .row > .item {
            width: 100%;
        }



        .item-main-line {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .item-check {
            transform: scale(1.2);
            cursor: pointer;
        }

        .checked-item-text {
            text-decoration: line-through;
            color: #777;
        }

        .source-line {
            font-size: 13px;
            margin-top: 4px;
            margin-left: 30px;
            color: #aaa;
        }

        .source-link {
            color: #888;
            font-size: 13px;
            text-decoration: none;
        }

        .source-link:hover {
            color: #00cc66;
            text-decoration: underline;
        }

        .store-btn {
            width: auto;
            margin-left: 5px;
            margin-top: 0;
            padding: 8px 12px;
            font-size: 14px;
            background: #444;
        }

        .store-btn.active {
            background: #0078D7;
            color: white;
            font-weight: bold;
        }

        .message {
            max-width: 900px;
            margin: 0 auto 12px auto;
            text-align: center;
            color: #00cc66;
            font-weight: bold;
        }

        .log-box {
            background: #181818;
            padding: 12px;
            border-radius: 10px;
            margin-top: 10px;
            font-size: 13px;
            word-break: break-word;
            border: 1px solid #2d2d2d;
        }

        .log-box a {
            color: #aaa;
            text-decoration: none;
        }

        .log-box a:hover {
            color: #00cc66;
            text-decoration: underline;
        }

        .recipe-label {
            color: #00cc66;
            font-weight: bold;
        }

        .recipe-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
            gap: 10px;
        }

        .recipe-row:last-child {
            margin-bottom: 0;
        }

        .recipe-left { flex: 1; }

        .remove-recipe-form { margin: 0; }

        .remove-recipe-btn {
            width: auto;
            margin: 0;
            padding: 5px 10px;
            font-size: 12px;
            background: #aa0000;
            border-radius: 5px;
        }



        .clear-one-product-form {
            margin: 0 0 0 5px;
        }

        .clear-one-product-btn {
            width: auto;
            margin-left: 0;
            margin-top: 0;
            padding: 8px 12px;
            font-size: 14px;
            background: #7f1d1d;
        }

        .clear-one-product-btn:hover {
            background: #991b1b;
        }

        .product-search-form {
            margin: 0 0 0 5px;
        }

        .product-search-btn {
            width: auto;
            margin-left: 0;
            margin-top: 0;
            padding: 8px 12px;
            font-size: 14px;
            background: #0f766e;
        }

        .product-search-btn:hover {
            background: #0d9488;
        }

        .product-modal-backdrop {
            position: fixed;
            inset: 0;
            z-index: 2000;
            background: rgba(0,0,0,0.72);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 18px;
            box-sizing: border-box;
        }

        .product-choice-card {
            width: min(940px, 100%);
            max-height: 88vh;
            overflow-y: auto;
            padding: 18px;
            border-radius: 14px;
            background: #1b1b1b;
            border: 1px solid #777;
            box-shadow: 0 18px 60px rgba(0,0,0,0.75);
            box-sizing: border-box;
        }

        .product-choice-header {
            position: sticky;
            top: -18px;
            z-index: 5;
            background: #1b1b1b;
            padding: 4px 0 12px 0;
            border-bottom: 1px solid #333;
            margin-bottom: 12px;
        }

        .product-choice-title-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        .product-choice-card h2 {
            flex: 1;
            margin: 0;
            text-align: center;
        }

        .product-close-btn {
            width: auto;
            margin: 0;
            padding: 7px 11px;
            font-size: 14px;
            background: #444;
            border-radius: 8px;
        }

        .product-close-btn:hover {
            background: #666;
        }

        .product-choice-subtitle {
            color: #aaa;
            text-align: center;
            font-size: 14px;
            margin: 0 0 14px 0;
        }

        .product-option {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 120px;
            gap: 12px;
            align-items: center;
            background: #202425;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 12px;
            margin-top: 10px;
        }

        .product-option-name {
            color: #fff;
            font-weight: bold;
            line-height: 1.35;
        }

        .product-option-name-link {
            color: #7dd3fc;
            text-decoration: none;
            font-weight: bold;
            line-height: 1.35;
        }

        .product-option-name-link:hover {
            color: #38bdf8;
            text-decoration: underline;
        }

        .product-organic-badge {
            display: inline-block;
            margin-left: 6px;
            padding: 2px 6px;
            border-radius: 999px;
            background: #14532d;
            color: #86efac;
            font-size: 11px;
            vertical-align: middle;
        }

        .product-option-meta {
            color: #aaa;
            font-size: 13px;
            margin-top: 4px;
            line-height: 1.4;
        }

        .product-option-url {
            color: #888;
            font-size: 12px;
            text-decoration: none;
            word-break: break-word;
        }

        .product-option-url:hover {
            color: #00cc66;
            text-decoration: underline;
        }

        .select-product-btn {
            width: 100%;
            margin-top: 0;
            padding: 10px;
            font-size: 14px;
            background: #0078D7;
        }

        .select-product-btn.selected {
            background: #107C10;
            font-weight: bold;
        }

        .product-link-line {
            color: #7dd3fc;
        }

        .product-link-line a {
            color: #7dd3fc;
        }

        .product-link-line a:hover {
            color: #38bdf8;
        }


        .bulk-product-actions {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            max-width: 560px;
            margin: 14px auto 0 auto;
        }

        .grab-products-btn {
            background: #0f766e;
            margin-top: 0;
            font-size: 15px;
            padding: 11px;
        }

        .clear-products-btn {
            background: #7f1d1d;
            margin-top: 0;
            font-size: 15px;
            padding: 11px;
        }


        .bulk-preview-controls {
            display: flex;
            gap: 8px;
            justify-content: flex-end;
            align-items: center;
            margin: 10px 0;
            flex-wrap: wrap;
        }

        .bulk-preview-control-btn {
            width: auto;
            margin-top: 0;
            padding: 7px 11px;
            font-size: 13px;
            background: #333;
            border-radius: 7px;
        }

        .bulk-preview-checkbox {
            transform: scale(1.15);
            cursor: pointer;
            flex: 0 0 auto;
        }

        .bulk-preview-item label {
            display: flex;
            align-items: center;
            gap: 10px;
            width: 100%;
            cursor: pointer;
        }

        .bulk-preview-list {
            background: #181818;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 12px;
            margin-top: 12px;
            max-height: 45vh;
            overflow-y: auto;
        }

        .bulk-preview-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 9px 8px;
            border-bottom: 1px solid #2a2a2a;
            color: #ddd;
        }

        .bulk-progress-item {
            display: grid;
            grid-template-columns: 28px minmax(0, 1fr) minmax(220px, 290px) auto;
            align-items: center;
            gap: 10px;
            padding: 9px 8px;
            border-bottom: 1px solid #2a2a2a;
            color: #ddd;
        }

        .bulk-preview-item:last-child,
        .bulk-progress-item:last-child {
            border-bottom: none;
        }


        .bulk-preview-store-badge {
            display: inline-block;
            margin-left: 8px;
            padding: 2px 7px;
            border-radius: 999px;
            background: #0f172a;
            border: 1px solid #334155;
            color: #7dd3fc;
            font-size: 12px;
            font-weight: bold;
            vertical-align: middle;
        }

        .bulk-preview-index {
            color: #00cc66;
            min-width: 34px;
            font-weight: bold;
        }

        .bulk-modal-actions {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 14px;
        }

        .bulk-continue-btn {
            background: #107C10;
            margin-top: 0;
        }

        .bulk-cancel-btn {
            background: #aa0000;
            margin-top: 0;
        }

        .bulk-secondary-btn {
            background: #444;
            margin-top: 0;
        }

        .bulk-progress-status {
            background: #111;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 12px;
            margin-top: 12px;
        }

        .bulk-active-line {
            color: #fff;
            font-weight: bold;
            text-align: center;
            margin-bottom: 10px;
        }

        .bulk-active-ingredient {
            color: #00cc66;
        }

        .bulk-progress-bar-wrap {
            height: 12px;
            border-radius: 999px;
            background: #2a2a2a;
            overflow: hidden;
            margin-top: 10px;
        }

        .bulk-progress-bar {
            height: 100%;
            width: 0%;
            background: #0078D7;
            transition: width 0.25s ease;
        }

        .bulk-spinner {
            width: 34px;
            height: 34px;
            border: 4px solid #333;
            border-top: 4px solid #00cc66;
            border-radius: 50%;
            animation: spin 0.85s linear infinite;
            margin: 0 auto 10px auto;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .bulk-progress-check {
            width: 18px;
            height: 18px;
            accent-color: #00cc66;
            flex: 0 0 auto;
        }

        .bulk-progress-text.done {
            color: #777;
            text-decoration: line-through;
        }

        .bulk-progress-text.active {
            color: #00cc66;
            font-weight: bold;
        }

        .bulk-progress-meta {
            color: #aaa;
            font-size: 12px;
            text-align: left;
            border-left: 1px solid #333;
            padding-left: 12px;
            min-height: 34px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 3px;
            min-width: 0;
        }

        .bulk-product-name {
            color: #ddd;
            font-size: 12px;
            line-height: 1.25;
            overflow-wrap: anywhere;
        }

        .bulk-product-price {
            color: #fff;
            font-size: 13px;
            font-weight: bold;
            line-height: 1.2;
        }

        .bulk-product-status {
            color: #aaa;
            font-size: 12px;
            line-height: 1.25;
        }

        .bulk-error {
            color: #ff8a8a;
        }

        .bulk-progress-main {
            display: flex;
            flex-direction: column;
            min-width: 0;
            flex: 1;
        }

        .bulk-progress-title-line {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }


        .bulk-progress-store-link {
            color: #60a5fa;
            text-decoration: none;
            font-size: 12px;
        }

        .bulk-progress-store-link:hover {
            color: #93c5fd;
            text-decoration: underline;
        }

        .bulk-skip-reason {
            color: #fbbf24;
            font-size: 12px;
            margin-top: 3px;
            line-height: 1.25;
        }

        .bulk-progress-store-line {
            color: #7dd3fc;
            font-size: 12px;
            margin-left: 0;
            margin-top: 4px;
            line-height: 1.25;
        }

        .bulk-alt-modal-backdrop {
            position: fixed;
            inset: 0;
            z-index: 9999;
            background: rgba(0,0,0,0.72);
            display: none;
            align-items: center;
            justify-content: center;
            padding: 18px;
            box-sizing: border-box;
        }

        .bulk-alt-modal-backdrop.open {
            display: flex;
        }

        .bulk-alt-modal {
            width: min(860px, 94vw);
            max-height: 82vh;
            overflow-y: auto;
            background: #1b1b1b;
            border: 1px solid #777;
            border-radius: 14px;
            box-shadow: 0 18px 80px rgba(0,0,0,0.9);
            padding: 18px;
            box-sizing: border-box;
        }

        .bulk-alt-modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            border-bottom: 1px solid #333;
            padding-bottom: 12px;
            margin-bottom: 12px;
        }

        .bulk-alt-modal-title {
            margin: 0;
            flex: 1;
            text-align: center;
        }

        .bulk-alt-modal-subtitle {
            text-align: center;
            color: #aaa;
            margin: 0 0 12px 0;
            font-size: 14px;
        }


        .bulk-alt-toggle {
            width: auto;
            margin-top: 6px;
            padding: 5px 9px;
            font-size: 12px;
            background: #333;
            border-radius: 6px;
        }

        .bulk-alt-toggle:hover {
            background: #444;
        }

        .bulk-choices {
            display: none !important;
        }

        .bulk-choices.open {
            display: block;
        }

        .bulk-alt-option {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 92px;
            gap: 8px;
            align-items: center;
            padding: 8px;
            border-bottom: 1px solid #2a2a2a;
        }

        .bulk-alt-option:last-child {
            border-bottom: none;
        }

        .bulk-alt-name {
            color: #ddd;
            font-size: 13px;
            font-weight: bold;
        }

        .bulk-alt-link {
            color: #7dd3fc;
            text-decoration: none;
        }

        .bulk-alt-link:hover {
            color: #38bdf8;
            text-decoration: underline;
        }

        .bulk-alt-meta {
            color: #aaa;
            font-size: 12px;
            margin-top: 3px;
        }

        .bulk-alt-select-btn {
            width: auto;
            margin-top: 0;
            padding: 7px 9px;
            font-size: 12px;
            background: #0078D7;
        }

        .bulk-alt-select-btn.selected {
            background: #107C10;
            font-weight: bold;
        }

        .bulk-selected-badge {
            display: none;
        }

        .bulk-review-note {
            text-align: center;
            color: #facc15;
            font-weight: bold;
            margin-top: 10px;
        }

        .bulk-finish-btn {
            background: #107C10;
            margin-top: 0;
        }


        @media (max-width: 650px) {
            .store-manager-row {
                grid-template-columns: 28px 1fr 62px 76px;
            }

            .store-manager-url {
                grid-column: 2 / 5;
            }

            .store-location-details {
                grid-column: 1 / 5;
            }

            .store-edit-form {
                grid-template-columns: 1fr;
            }

            .add-store-grid {
                grid-template-columns: 1fr;
            }


            .address-grid,
            .address-actions-grid {
                grid-template-columns: 1fr;
            }

            .actions-grid {
                grid-template-columns: 1fr;
            }

            .row {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                align-items: center;
            }

            .item {
                min-width: 0;
                flex: 1 0 100%;
            }

            .item-actions {
                margin-left: 30px;
            }

            .store-btn,
            .product-search-btn,
            .clear-one-product-btn {
                width: 74px;
                min-width: 74px;
                max-width: 74px;
                margin-left: 0;
                padding: 10px 6px;
                font-size: 15px;
                text-align: center;
            }

            .product-search-form,
            .clear-one-product-form {
                margin-left: 0;
            }

            .product-option {
                grid-template-columns: 1fr;
            }

            .bulk-product-actions,
            .bulk-modal-actions {
                grid-template-columns: 1fr;
            }

            .bulk-alt-option {
                grid-template-columns: 1fr;
            }

            .bulk-progress-item {
                grid-template-columns: 24px minmax(0, 1fr);
            }

            .bulk-progress-meta {
                grid-column: 2 / 3;
                border-left: none;
                border-top: 1px solid #333;
                padding-left: 0;
                padding-top: 7px;
                margin-top: 3px;
            }

            .bulk-alt-toggle {
                grid-column: 2 / 3;
                justify-self: start;
            }

            .open-url-toggle,
            .show-item-buttons-toggle {
                margin-left: 0;
                width: 100%;
                justify-content: center;
            }

            .behavior-toggle {
                width: 100%;
                justify-content: center;
                box-sizing: border-box;
            }

            .view-action-form {
                width: 100%;
            }

            .view-action-btn {
                width: 100%;
                min-width: 100%;
            }
        }
    </style>
</head>

<body>

<h1>Shopping List</h1>

{% if message %}
<div class="message">{{ message }}</div>
{% endif %}

{% if product_choice_item and product_choices %}
<div class="product-modal-backdrop" id="productModalBackdrop" onclick="closeProductModalOnBackdrop(event)">
    <div class="product-choice-card" id="productChoices" role="dialog" aria-modal="true" aria-labelledby="productChoiceTitle">
        <div class="product-choice-header">
            <div class="product-choice-title-row">
                <div style="width:52px;"></div>
                <h2 id="productChoiceTitle">Choose Product</h2>
                <button type="button" class="product-close-btn" onclick="closeProductModal()">Close</button>
            </div>

            <p class="product-choice-subtitle">
                Select the best product for: <strong>{{ product_choice_item }}</strong>
            </p>
        </div>

        {% for product in product_choices %}
            <div class="product-option">
                <div>
                    <div class="product-option-name">
                        {% if product.product_url %}
                            <a class="product-option-name-link" href="{{ product.product_url }}" target="_blank" rel="noopener noreferrer">
                                {{ product.product_name or "Unknown product" }}
                            </a>
                        {% else %}
                            {{ product.product_name or "Unknown product" }}
                        {% endif %}
                        {% if product.is_organic %}
                            <span class="product-organic-badge">ORGANIC</span>
                        {% endif %}
                    </div>

                    <div class="product-option-meta">
                        Store: {{ product.product_location or product.store or "Unknown" }}
                        {% if product.product_cost %}
                            &nbsp;•&nbsp; Cost: {{ product.product_cost }}
                        {% endif %}
                        &nbsp;•&nbsp; Score: {{ product.score or 0 }}
                    </div>

                    {% if product.product_url %}
                        <a class="product-option-url" href="{{ product.product_url }}" target="_blank">
                            {{ product.product_url }}
                        </a>
                    {% endif %}
                </div>

                <form method="POST" action="/select_product" onsubmit="saveScroll()">
                    <input type="hidden" name="item" value="{{ product_choice_item }}">
                    <input type="hidden" name="product_json" value='{{ product | tojson }}'>
                    {% set selected_product_url = product_choice_selected.product_url if product_choice_selected else "" %}
                    {% set selected_product_name = product_choice_selected.product_name if product_choice_selected else "" %}
                    {% set selected = (selected_product_url and product.product_url == selected_product_url) or ((not selected_product_url) and selected_product_name and product.product_name == selected_product_name) %}
                    <button type="submit" class="select-product-btn {% if selected %}selected{% endif %}">
                        {% if selected %}Selected{% else %}Select{% endif %}
                    </button>
                </form>
            </div>
        {% endfor %}
    </div>
</div>
{% endif %}

{% if bulk_preview_items %}
<div class="product-modal-backdrop" id="bulkPreviewModalBackdrop" onclick="closeBulkPreviewOnBackdrop(event)">
    <div class="product-choice-card" role="dialog" aria-modal="true">
        <div class="product-choice-header">
            <div class="product-choice-title-row">
                <div style="width:52px;"></div>
                <h2>Review Products to Grab</h2>
                <button type="button" class="product-close-btn" onclick="closeBulkPreviewModal()">Close</button>
            </div>

            <p class="product-choice-subtitle">
                Only ingredients with a selected store will be reviewed. Existing saved product picks are skipped.
            </p>
        </div>

        <form method="POST" action="/start_grab_best_products" onsubmit="saveScroll(); return validateBulkSelection();">
            <div class="bulk-preview-controls">
                <button type="button" class="bulk-preview-control-btn" onclick="setAllBulkPreviewItems(true)">Select All</button>
                <button type="button" class="bulk-preview-control-btn" onclick="setAllBulkPreviewItems(false)">Clear All</button>
            </div>

            <div class="bulk-preview-list">
                {% for preview_item in bulk_preview_items %}
                    <div class="bulk-preview-item">
                        <label>
                            <input type="checkbox"
                                   class="bulk-preview-checkbox"
                                   name="bulk_items"
                                   value="{{ preview_item }}"
                                   checked>
                            <span class="bulk-preview-index">{{ loop.index }}.</span>
                            <span>
                                {{ preview_item }}
                                {% set selected_store = get_selected_store_for_item(preview_item) %}
                                {% if selected_store and selected_store in available_stores %}
                                    <span class="bulk-preview-store-badge">
                                        {{ available_stores[selected_store].label }}
                                    </span>
                                {% endif %}
                            </span>
                        </label>
                    </div>
                {% endfor %}
            </div>

            <div class="bulk-modal-actions">
                <button type="submit" class="bulk-continue-btn">Continue</button>
                <button type="button" class="bulk-secondary-btn" onclick="closeBulkPreviewModal()">Cancel</button>
            </div>
        </form>
    </div>
</div>
{% endif %}

{% if bulk_job_id %}
<div class="product-modal-backdrop" id="bulkProgressModalBackdrop">
    <div class="product-choice-card" role="dialog" aria-modal="true">
        <div class="product-choice-header">
            <div class="product-choice-title-row">
                <div style="width:52px;"></div>
                <h2>Grabbing Best Products</h2>
                <button type="button" class="product-close-btn" onclick="hideBulkProgressModal()">Hide</button>
            </div>

            <p class="product-choice-subtitle">
                You can cancel this operation at any time.
            </p>
        </div>

        <div class="bulk-progress-status">
            <div id="bulkSpinner" class="bulk-spinner"></div>

            <div class="bulk-active-line">
                Active ingredient:
                <span id="bulkActiveIngredient" class="bulk-active-ingredient">Starting...</span>
            </div>

            <div id="bulkSummary" class="product-choice-subtitle">Preparing...</div>

            <div class="bulk-progress-bar-wrap">
                <div id="bulkProgressBar" class="bulk-progress-bar"></div>
            </div>
        </div>

        <div id="bulkProgressList" class="bulk-preview-list"></div>

        <div class="bulk-alt-modal-backdrop" id="bulkAltModalBackdrop" onclick="closeBulkChoicesOnBackdrop(event)">
            <div class="bulk-alt-modal" role="dialog" aria-modal="true">
                <div class="bulk-alt-modal-header">
                    <div style="width:52px;"></div>
                    <h2 class="bulk-alt-modal-title">Choice Products</h2>
                    <button type="button" class="product-close-btn" onclick="closeBulkChoicesModal()">Close</button>
                </div>

                <p class="bulk-alt-modal-subtitle" id="bulkAltModalSubtitle"></p>

                <div id="bulkAltModalList"></div>
            </div>
        </div>

        <div id="bulkReviewNote" class="bulk-review-note" style="display:none;">
            Review the selected products below. Expand choices to make changes before finishing.
        </div>

        <div class="bulk-modal-actions">
            <button type="button" class="bulk-cancel-btn" id="bulkCancelBtn" onclick="cancelBulkGrab()">Cancel Operation</button>
            <button type="button" class="bulk-finish-btn" id="bulkFinishBtn" style="display:none;" onclick="finishBulkReview()">Finish / Keep Selections</button>
            <button type="button" class="bulk-secondary-btn" onclick="hideBulkProgressModal()">Hide</button>
        </div>
    </div>
</div>
{% endif %}


{% if extract_job_id %}
<div class="product-modal-backdrop" id="extractProgressModalBackdrop">
    <div class="product-choice-card" role="dialog" aria-modal="true">
        <div class="product-choice-header">
            <div class="product-choice-title-row">
                <div style="width:52px;"></div>
                <h2>Extracting Ingredients</h2>
                <button type="button" class="product-close-btn" onclick="hideExtractProgressModal()">Hide</button>
            </div>

            <p class="product-choice-subtitle">
                Your recipes are being processed. This page will update when extraction finishes.
            </p>
        </div>

        <div class="bulk-progress-status">
            <div id="extractSpinner" class="bulk-spinner"></div>

            <div class="bulk-active-line">
                Status:
                <span id="extractStatusText" class="bulk-active-ingredient">Starting...</span>
            </div>

            <div id="extractSummary" class="product-choice-subtitle">Preparing extraction...</div>

            <div class="bulk-progress-bar-wrap">
                <div id="extractProgressBar" class="bulk-progress-bar"></div>
            </div>
        </div>

        <div id="extractUrlList" class="bulk-preview-list"></div>

        <div class="bulk-modal-actions">
            <button type="button" class="bulk-secondary-btn" onclick="hideExtractProgressModal()">Hide</button>
        </div>
    </div>
</div>
{% endif %}

{% if nearest_job_id %}
<div class="product-modal-backdrop" id="nearestProgressModalBackdrop">
    <div class="product-choice-card" role="dialog" aria-modal="true">
        <div class="product-choice-header">
            <div class="product-choice-title-row">
                <div style="width:52px;"></div>
                <h2>Finding Nearest Stores</h2>
                <button type="button" class="product-close-btn" onclick="hideNearestProgressModal()">Hide</button>
            </div>

            <p class="product-choice-subtitle">
                Updating home store locations from your address. This popup syncs across your phone and computer.
            </p>
        </div>

        <div class="bulk-progress-status">
            <div id="nearestSpinner" class="bulk-spinner"></div>

            <div class="bulk-active-line">
                Status:
                <span id="nearestStatusText" class="bulk-active-ingredient">Starting...</span>
            </div>

            <div id="nearestSummary" class="product-choice-subtitle">Preparing nearest store lookup...</div>

            <div class="bulk-progress-bar-wrap">
                <div id="nearestProgressBar" class="bulk-progress-bar"></div>
            </div>
        </div>

        <div id="nearestLogList" class="bulk-preview-list"></div>

        <div class="bulk-modal-actions">
            <button type="button" class="bulk-secondary-btn" onclick="hideNearestProgressModal()">Hide</button>
        </div>
    </div>
</div>
{% endif %}

<div class="recipe-card">
    <h2>Enter Recipe Links</h2>
    <p class="helper-text">Paste one recipe URL per line</p>

    <form method="POST" action="/extract">
        <textarea
            class="recipe-url-box"
            name="urls"
            placeholder="https://www.forkinthekitchen.com/homemade-cheese-ravioli/&#10;https://www.forkinthekitchen.com/homemade-crispy-falafel/"></textarea>

        <button class="extract-btn" type="submit">Extract Ingredients</button>
    </form>
</div>

<div class="app-card">
    <h2>Edit Shopping Items</h2>

    <form method="POST" action="/save" onsubmit="saveScroll()">
        <textarea class="edit-items-box" name="items">{{ raw_items }}</textarea>
        <button class="save-btn">Save List</button>
    </form>

    <div class="actions-grid">
        <form method="POST" action="/sort" onsubmit="saveScroll()">
            <button class="sort-btn" type="submit">Sort List</button>
        </form>

        <form method="POST" action="/clear">
            <button class="clear-btn" type="submit">Clear List</button>
        </form>

    </div>
</div>

<div class="app-card">
    <h2>Current Recipe URL Log</h2>

    {% if current_urls %}
        <div class="log-box">
        {% for recipe in current_urls %}
            <div class="recipe-row">
                <div class="recipe-left">
                    <span class="recipe-label">Recipe {{ loop.index }}:</span>
                    <a href="{{ recipe.url }}" target="_blank">{{ recipe.name }}</a>
                </div>

                <form method="POST"
                      action="/remove_recipe"
                      class="remove-recipe-form"
                      onsubmit="saveScroll(); return confirm('Remove this recipe URL and any ingredients only used by this recipe?');">
                    <input type="hidden" name="url" value="{{ recipe.url }}">
                    <button type="submit" class="remove-recipe-btn">Remove</button>
                </form>
            </div>
        {% endfor %}
        </div>
    {% else %}
        <div class="log-box">No current recipe URLs yet.</div>
    {% endif %}
</div>

<div class="app-card" id="home-address-section">
    <h2>Home Address</h2>
    <p class="helper-text">This address is used by <strong>find_nearest_stores.py</strong> and saved into <strong>PushShoppingList/shopping_stores_Results.json</strong>.</p>

    <form method="POST" action="/save_home_address" onsubmit="saveScroll();">
        <div class="address-grid">
            <input name="address_street" value="{{ home_address.street }}" placeholder="Street, e.g. 5905 Arlo Drive" required>
            <input name="address_apartment" value="{{ home_address.apartment }}" placeholder="Apartment, e.g. Apt 2213">
            <input name="address_city" value="{{ home_address.city }}" placeholder="City, e.g. Indianapolis" required>
            <input name="address_state" value="{{ home_address.state }}" placeholder="State, e.g. IN" required>
            <input name="address_zip" value="{{ home_address.zip }}" placeholder="ZIP" required>
        </div>

        <div class="address-summary-box">
            <span class="store-detail-label">Current full address</span>
            {{ home_address.full_address }}
            {% if home_address.lat and home_address.lng %}
                <br>
                <span class="store-detail-label">Coordinates</span>
                {{ home_address.lat }}, {{ home_address.lng }}
            {% endif %}
        </div>

        <div class="address-actions-grid">
            <button type="submit" name="action" value="save" class="address-save-btn">Save Address</button>
            <button type="submit" name="action" value="run_find_nearest" class="nearest-stores-btn" onclick="saveScroll();">Run Find Nearest Stores</button>
        </div>
    </form>
</div>

<div class="app-card">
    <button type="button"
            class="card-collapse-toggle"
            data-collapse-key="store-options">
        <span>Store Options</span>
        <span class="card-collapse-icon">Show ▾</span>
    </button>

    <div class="card-collapse-content collapsed" data-collapse-content="store-options">
        <p class="helper-text">This is your editable store list. Check stores to show buttons next to each item.</p>

        <form id="store-options-form" method="POST" action="/save_store_settings" onsubmit="saveScroll()"></form>

    <div class="store-manager-list">
            {% for store_key, store in available_stores.items() %}
                {% set nearest = store_locations.get(store_key, {}) %}
                <div class="store-manager-row">
                    <input type="checkbox"
                           form="store-options-form"
                           name="enabled_stores"
                           value="{{ store_key }}"
                           title="Show {{ store.label }} buttons"
                           {% if store_key in enabled_stores %}checked{% endif %}>

                    <div class="store-manager-label">{{ store.label }}</div>

                    <div class="store-manager-url">
                        <div class="store-detail-line">
                            <span class="store-detail-label">Search</span>
                            <a class="store-detail-link" href="{{ store.url }}" target="_blank" rel="noopener noreferrer">{{ store.url }}</a>
                        </div>
                        {% if store.urlStoreSelector %}
                            <div class="store-detail-line">
                                <span class="store-detail-label">Store Selector URL</span>
                                <a class="store-detail-link" href="{{ store.urlStoreSelector }}" target="_blank" rel="noopener noreferrer">{{ store.urlStoreSelector }}</a>
                            </div>
                        {% endif %}
                    </div>

                    <button type="button"
                            class="store-edit-btn"
                            onclick="toggleStoreEdit('{{ store_key }}')">
                        Edit
                    </button>

                    <button type="submit"
                            form="delete-store-{{ store_key }}"
                            class="store-delete-btn"
                            onclick="saveScroll(); return confirm('Delete {{ store.label }} from your store list?');">
                        Delete
                    </button>

                    <div class="store-location-details">
                        {% if nearest %}
                            <div class="store-detail-line">
                                <span class="store-detail-label">Nearest</span>
                                <strong>{{ nearest.selected_name or nearest.store_name or store.label }}</strong>
                                {% if nearest.distance_miles is not none %}
                                    <span> • {{ nearest.distance_miles }} mi</span>
                                {% endif %}
                            </div>

                            {% if nearest.exact_address %}
                                <div class="store-detail-line">
                                    <span class="store-detail-label">Address</span>
                                    {% if nearest.place_url %}
                                        <a class="store-detail-link" href="{{ nearest.place_url }}" target="_blank" rel="noopener noreferrer">
                                            {{ nearest.exact_address }}
                                        </a>
                                    {% else %}
                                        {{ nearest.exact_address }}
                                    {% endif %}
                                </div>
                            {% endif %}

                            {% if nearest.website %}
                                <div class="store-detail-line">
                                    <span class="store-detail-label">Website</span>
                                    <a class="store-detail-link" href="{{ nearest.website }}" target="_blank" rel="noopener noreferrer">
                                        {{ nearest.website }}
                                    </a>
                                </div>
                            {% endif %}

                            {% if nearest.phone %}
                                <div class="store-detail-line">
                                    <span class="store-detail-label">Phone</span>{{ nearest.phone }}
                                </div>
                            {% endif %}

                            {% if nearest.candidates %}
                                <button type="button"
                                        class="store-choice-toggle"
                                        onclick="toggleStoreChoices('{{ store_key }}')">
                                    Choices ({{ nearest.candidates|length }})
                                </button>

                                <div class="store-candidate-list" id="store-choices-{{ store_key }}">
                                    {% for candidate in nearest.candidates %}
                                        {% set candidate_name = candidate.name or store.label %}
                                        {% set candidate_selected = (candidate.place_url and nearest.place_url and candidate.place_url == nearest.place_url) or (candidate.website and nearest.website and candidate.website == nearest.website) or (candidate.exact_address and nearest.exact_address and candidate.exact_address == nearest.exact_address) %}
                                        <div class="store-candidate-item">
                                            <div class="store-candidate-actions">
                                                <form method="POST"
                                                      action="/select_store_location_choice"
                                                      class="store-candidate-form"
                                                      onsubmit="saveScroll()">
                                                    <input type="hidden" name="store_key" value="{{ store_key }}">
                                                    <input type="hidden" name="candidate_index" value="{{ loop.index0 }}">
                                                    <button type="submit" class="store-candidate-select-btn {% if candidate_selected %}selected{% endif %}">
                                                        <div class="store-candidate-top-line">
                                                            <span>
                                                                <strong>{{ candidate_name }}</strong>
                                                                {% if candidate.distance_miles is not none %}
                                                                    <span> • {{ candidate.distance_miles }} mi</span>
                                                                {% endif %}
                                                            </span>
                                                            {% if candidate_selected %}
                                                                <span class="store-selected-badge">✓ Selected</span>
                                                            {% endif %}
                                                        </div>

                                                        {% if candidate.exact_address %}
                                                            <div class="store-detail-line">
                                                                <span class="store-detail-label">Address</span>
                                                                {{ candidate.exact_address }}
                                                            </div>
                                                        {% endif %}

                                                        {% if candidate.website %}
                                                            <div class="store-detail-line">
                                                                <span class="store-detail-label">Website</span>
                                                                {{ candidate.website }}
                                                            </div>
                                                        {% endif %}

                                                        {% if candidate.phone %}
                                                            <div class="store-detail-line">
                                                                <span class="store-detail-label">Phone</span>
                                                                {{ candidate.phone }}
                                                            </div>
                                                        {% endif %}
                                                    </button>
                                                </form>

                                                <button type="button"
                                                        class="store-candidate-edit-btn"
                                                        onclick="toggleStoreChoiceEdit('{{ store_key }}', '{{ loop.index0 }}')">
                                                    Edit
                                                </button>
                                            </div>

                                            <form id="store-choice-edit-{{ store_key }}-{{ loop.index0 }}"
                                                  method="POST"
                                                  action="/edit_store_location_choice"
                                                  class="store-candidate-edit-form"
                                                  onsubmit="saveScroll()">
                                                <input type="hidden" name="store_key" value="{{ store_key }}">
                                                <input type="hidden" name="candidate_index" value="{{ loop.index0 }}">

                                                <label class="store-candidate-edit-field">
                                                    <span>Name</span>
                                                    <input name="candidate_name" value="{{ candidate_name }}" required>
                                                </label>

                                                <label class="store-candidate-edit-field">
                                                    <span>Distance</span>
                                                    <input name="candidate_distance_miles" value="{{ candidate.distance_miles if candidate.distance_miles is not none else '' }}" placeholder="1.89">
                                                </label>

                                                <label class="store-candidate-edit-field full-width">
                                                    <span>Address</span>
                                                    <input name="candidate_exact_address" value="{{ candidate.exact_address or '' }}" required>
                                                </label>

                                                <label class="store-candidate-edit-field full-width">
                                                    <span>Website</span>
                                                    <input name="candidate_website" value="{{ candidate.website or '' }}" placeholder="https://...">
                                                </label>

                                                <label class="store-candidate-edit-field full-width">
                                                    <span>Google Maps URL</span>
                                                    <input name="candidate_place_url" value="{{ candidate.place_url or '' }}" placeholder="https://maps.google.com/...">
                                                </label>

                                                <label class="store-candidate-edit-field">
                                                    <span>Phone</span>
                                                    <input name="candidate_phone" value="{{ candidate.phone or '' }}">
                                                </label>

                                                <label class="store-candidate-edit-field">
                                                    <span>Latitude</span>
                                                    <input name="candidate_lat" value="{{ candidate.lat if candidate.lat is not none else '' }}">
                                                </label>

                                                <label class="store-candidate-edit-field">
                                                    <span>Longitude</span>
                                                    <input name="candidate_lng" value="{{ candidate.lng if candidate.lng is not none else '' }}">
                                                </label>

                                                <button type="submit" class="store-candidate-save-btn">Save Choice Edit</button>
                                            </form>
                                        </div>
                                    {% endfor %}
                                </div>
                            {% endif %}
                        {% else %}
                            <div class="store-detail-line">
                                <span class="store-detail-label">Nearest</span>
                                No nearest location saved yet. Run <code>update_home_stores.py</code>.
                            </div>
                        {% endif %}
                    </div>
                </div>

                <form id="edit-store-{{ store_key }}"
                      method="POST"
                      action="/edit_store"
                      class="store-edit-form"
                      onsubmit="saveScroll()">
                    <input type="hidden" name="old_store_key" value="{{ store_key }}">
                    <label class="store-edit-field">
                        <span>Store ID</span>
                        <input name="store_key"
                               value="{{ store_key }}"
                               placeholder="lowercase id, e.g. costco"
                               title="Store ID: lowercase, no spaces, e.g. costco"
                               required>
                    </label>
                    <label class="store-edit-field">
                        <span>Store Name</span>
                        <input name="store_label"
                               value="{{ store.label }}"
                               placeholder="Display name, e.g. Costco"
                               title="Store Name: what appears on the button, e.g. Costco"
                               required>
                    </label>
                    <label class="store-edit-field">
                        <span>Search URL</span>
                        <input name="store_url"
                               value="{{ store.url }}"
                               placeholder="Search URL ending before the item, e.g. https://www.costco.com/CatalogSearch?keyword="
                               title="Search URL: the app adds the ingredient after this URL"
                               required>
                    </label>
                    <label class="store-edit-field">
                        <span>Store Selector URL</span>
                        <input name="urlStoreSelector"
                               value="{{ store.urlStoreSelector or '' }}"
                               placeholder="Store selector page, e.g. https://info.aldi.us/stores"
                               title="Store Selector URL: first website opened when setting this store location">
                    </label>
                    <button type="submit" class="store-edit-save-btn">Save Edit</button>
                </form>
            {% endfor %}
    </div>

    <button type="submit" form="store-options-form" class="store-save-btn">Save Store Options</button>

    {% for store_key, store in available_stores.items() %}
        <form id="delete-store-{{ store_key }}" method="POST" action="/delete_store" style="display:none;">
            <input type="hidden" name="store_key" value="{{ store_key }}">
        </form>
    {% endfor %}

    <div class="view-control-section">
        <div class="view-control-title">Add Store</div>

        <form method="POST" action="/add_store" onsubmit="saveScroll()">
            <div class="add-store-grid">
                <input name="store_label" placeholder="Store name, e.g. Costco" required>
                <input name="homepage_url" placeholder="Homepage, e.g. https://www.costco.com">
                <input name="store_url" placeholder="Search URL override, e.g. https://site.com/search?q=">
                <input name="urlStoreSelector" placeholder="Store Selector URL, e.g. https://info.aldi.us/stores">
            </div>

            <div class="add-store-help">
                Enter a homepage and the app will guess a search URL. Store Selector URL is the first page opened when setting a store location.
            </div>

            <button type="submit" class="store-save-btn">Add Store</button>
        </form>
    </div>
    </div>
</div>

<div class="app-card view-settings-card">
    <h2>View &amp; Behavior</h2>
    <p class="helper-text">Choose how the list is displayed, how buttons behave, and manage resets.</p>

    <div class="view-control-section">
        <div class="view-control-title">Display View</div>
        <div class="view-toggle-box view-control-row">
            <button type="button" id="sectionViewBtn" class="view-toggle-btn" onclick="showView('section')">
                Section View
            </button>

            <button type="button" id="storeViewBtn" class="view-toggle-btn" onclick="showView('store')">
                Store View
            </button>

            <button type="button" id="recipeViewBtn" class="view-toggle-btn" onclick="showView('recipe')">
                Recipe View
            </button>
        </div>
    </div>

    <div class="view-control-section">
        <div class="view-control-title">Button Behavior</div>
        <div class="view-control-row">
            <label class="behavior-toggle">
                <input type="checkbox" id="openStoreUrlsToggle" checked onchange="saveOpenStoreUrlsSetting()">
                Open store URLs
            </label>

            <label class="behavior-toggle">
                <input type="checkbox" id="showItemButtonsToggle" checked onchange="saveShowItemButtonsSetting()">
                Show item buttons
            </label>

            <label class="behavior-toggle">
                <input type="checkbox" id="showBestProductToggle" checked onchange="saveShowBestProductSetting()">
                Show best product
            </label>

            <label class="behavior-toggle">
                <input type="checkbox" id="hideCheckedItemsToggle" onchange="saveHideCheckedItemsSetting()">
                Hide checked items
            </label>

            <label class="behavior-toggle">
                <input type="checkbox" id="compactModeToggle" onchange="saveCompactModeSetting()">
                Compact mode
            </label>
        </div>
    </div>

    <div class="view-control-section">
        <div class="view-control-title">Product Tools</div>
        <div class="view-control-row">
            <form class="view-action-form" method="POST" action="/preview_grab_best_products" onsubmit="saveScroll(); showInstantGrabLoading();">
                <button type="submit" class="grab-products-btn view-action-btn">Grab Best Products</button>
            </form>

            <form class="view-action-form" method="POST" action="/clear_product_picks" onsubmit="saveScroll(); return confirm('Clear all saved product picks?');">
                <button type="submit" class="clear-products-btn view-action-btn">Clear Product Picks</button>
            </form>
        </div>
    </div>

    <div class="view-control-section">
        <div class="view-control-title">Reset Tools</div>
        <div class="view-control-row">
            <form class="view-action-form" method="POST" action="/reset_checks" onsubmit="saveScroll(); resetAllRecipeCheckboxes();">
                <button class="reset-checks-btn view-action-btn" type="submit">Reset Checkboxes</button>
            </form>

            <form class="view-action-form" method="POST" action="/reset_stores" onsubmit="saveScroll()">
                <button class="reset-stores-btn view-action-btn" type="submit">Reset Stores</button>
            </form>
        </div>
    </div>
</div>

<div id="sectionView">

<h2 class="items-title">Items</h2>

{% for item in items %}

    {% if is_section_header(item) %}
        {% set section_name = item.replace("===", "").strip() %}
        <div class="section-header-row collapsible-header" data-collapse-scope="section" data-collapse-key="section|{{ section_name }}">
            <span class="header-title">
                {{ section_name }}
                <span class="header-count">({{ section_counts.get(section_name, 0) }})</span>
            </span>
            <span class="header-toggle-icon">Hide ▴</span>
        </div>
    {% else %}

        {% set item_key = normalize(item) %}
        {% set state = item_state.get(item_key, {}) %}

        <div class="row {% if state.get("checked") %}row-checked{% endif %}" data-key="{{ item_key }}">
            <div class="item">

                <div class="item-main-line">
                    <input type="checkbox"
                           class="item-check"
                           {% if state.get("checked") %}checked{% endif %}>

                    <span class="item-text {% if state.get("checked") %}checked-item-text{% endif %}">
                        {{ item }}
                    </span>
                </div>

                {% set recipe_sources = item_sources.get(item_key, []) %}

                {% if recipe_sources is string %}
                    {% set recipe_sources = [{"url": recipe_sources}] %}
                {% endif %}

                {% if recipe_sources %}
                    {# Selected/best product goes directly under the ingredient first. #}
                    {% for source in recipe_sources %}
                        {% if source is not string and (source.source_type == "product" or source.product_url) %}
                            <div class="source-line product-link-line">
                                {% if source.product_cost %}
                                    <span>{{ source.product_cost }}</span>
                                {% endif %}

                                {% if source.product_location %}
                                    <span>{{ source.product_location }}</span>
                                {% endif %}

                                {% if source.product_url %}
                                    <a class="source-link" href="{{ source.product_url }}" target="_blank">
                                        {{ source.product_name or "selected product" }}
                                    </a>
                                {% else %}
                                    <span>{{ source.product_name or "selected product" }}</span>
                                {% endif %}
                            </div>
                        {% endif %}
                    {% endfor %}

                    {# Recipe quantity/link comes after the selected product. #}
                    {% for source in recipe_sources %}
                        {% if source is string %}
                            <div class="source-line">
                                <a class="source-link" href="{{ source }}" target="_blank">
                                    recipe {{ get_recipe_number(source, recipe_map) }}
                                </a>
                            </div>
                        {% elif not (source.source_type == "product" or source.product_url) %}
                            <div class="source-line">
                                {% if source.quantity %}
                                    <span>{{ source.quantity }} {{ source.unit or "" }}</span>
                                {% endif %}

                                {% if source.url %}
                                    <a class="source-link" href="{{ source.url }}" target="_blank">
                                        (recipe {{ get_recipe_number(source.url, recipe_map) }})
                                    </a>
                                {% else %}
                                    <span class="source-link">(manual item)</span>
                                {% endif %}
                            </div>
                        {% endif %}
                    {% endfor %}
                {% endif %}

            </div>

                <div class="item-actions">
                    {% for store_key in enabled_stores %}
                        {% set store = available_stores.get(store_key) %}
                        {% if store %}
                            <button type="button"
                                    class="store-btn {% if state.get('store') == store_key %}active{% endif %}"
                                    data-store="{{ store_key }}"
                                    onclick="selectStore(this, '{{ item }}', '{{ store_key }}')">
                                {{ store.label }}
                            </button>
                        {% endif %}
                    {% endfor %}
                    {% if item_has_selected_product(item, item_sources) %}
                        <form method="POST" action="/choose_choice" class="product-search-form" onsubmit="saveScroll()">
                            <input type="hidden" name="item" value="{{ item }}">
                            <button type="submit" class="product-search-btn">Choices</button>
                        </form>

                        <form method="POST" action="/clear_product_pick" class="clear-one-product-form" onsubmit="saveScroll()">
                            <input type="hidden" name="item" value="{{ item }}">
                            <button type="submit" class="clear-one-product-btn">Clear Product</button>
                        </form>
                    {% else %}
                        <form method="POST" action="/find_products" class="product-search-form" onsubmit="saveScroll()">
                            <input type="hidden" name="item" value="{{ item }}">
                            <button type="submit" class="product-search-btn">Products</button>
                        </form>
                    {% endif %}
                </div>
        </div>
    {% endif %}

{% endfor %}

</div>

<div id="storeView" style="display:none;">

<h2 class="items-title">Items by Store</h2>

{% for store_name, sections in store_view.items() %}

    {% if sections %}
        <div class="store-header-row collapsible-header" data-collapse-scope="store" data-collapse-key="store|{{ store_name }}">
            <span class="header-title">{{ store_name.upper() }}</span>
            <span class="header-toggle-icon">Hide ▴</span>
        </div>

        {% for section_name, section_items in sections.items() %}

            {% if section_items %}
                <div class="store-section-header collapsible-header" data-collapse-scope="store-section" data-collapse-key="store-section|{{ store_name }}|{{ section_name }}">
                    <span class="header-title">
                        {{ section_name }}
                        <span class="header-count">({{ section_items|length }})</span>
                    </span>
                    <span class="header-toggle-icon">Hide ▴</span>
                </div>

                {% for store_item in section_items %}
                    {% set item_key = normalize(store_item) %}
                    {% set state = item_state.get(item_key, {}) %}

                    <div class="row {% if state.get("checked") %}row-checked{% endif %}" data-key="{{ item_key }}">
                        <div class="item">
                            <div class="item-main-line">
                                <input type="checkbox"
                                       class="item-check"
                                       {% if state.get("checked") %}checked{% endif %}>

                                <span class="item-text {% if state.get("checked") %}checked-item-text{% endif %}">
                                    {{ store_item }}
                                </span>
                            </div>

                            {% set recipe_sources = item_sources.get(item_key, []) %}

                            {% if recipe_sources is string %}
                                {% set recipe_sources = [{"url": recipe_sources}] %}
                            {% endif %}

                            {% if recipe_sources %}
                                {# Selected/best product goes directly under the ingredient first. #}
                                {% for source in recipe_sources %}
                                    {% if source is not string and (source.source_type == "product" or source.product_url) %}
                                        <div class="source-line product-link-line">
                                            {% if source.product_cost %}
                                                <span>{{ source.product_cost }}</span>
                                            {% endif %}

                                            {% if source.product_location %}
                                                <span>{{ source.product_location }}</span>
                                            {% endif %}

                                            {% if source.product_url %}
                                                <a class="source-link" href="{{ source.product_url }}" target="_blank">
                                                    {{ source.product_name or "selected product" }}
                                                </a>
                                            {% else %}
                                                <span>{{ source.product_name or "selected product" }}</span>
                                            {% endif %}
                                        </div>
                                    {% endif %}
                                {% endfor %}

                                {# Recipe quantity/link comes after the selected product. #}
                                {% for source in recipe_sources %}
                                    {% if source is string %}
                                        <div class="source-line">
                                            <a class="source-link" href="{{ source }}" target="_blank">
                                                recipe {{ get_recipe_number(source, recipe_map) }}
                                            </a>
                                        </div>
                                    {% elif not (source.source_type == "product" or source.product_url) %}
                                        <div class="source-line">
                                            {% if source.quantity %}
                                                <span>{{ source.quantity }} {{ source.unit or "" }}</span>
                                            {% endif %}

                                            {% if source.url %}
                                                <a class="source-link" href="{{ source.url }}" target="_blank">
                                                    (recipe {{ get_recipe_number(source.url, recipe_map) }})
                                                </a>
                                            {% else %}
                                                <span class="source-link">(manual item)</span>
                                            {% endif %}
                                        </div>
                                    {% endif %}
                                {% endfor %}
                            {% endif %}
                        </div>

                            <div class="item-actions">
                                {% for store_key in enabled_stores %}
                                    {% set store = available_stores.get(store_key) %}
                                    {% if store %}
                                        <button type="button"
                                                class="store-btn {% if state.get('store') == store_key %}active{% endif %}"
                                                data-store="{{ store_key }}"
                                                onclick="selectStore(this, '{{ store_item }}', '{{ store_key }}')">
                                            {{ store.label }}
                                        </button>
                                    {% endif %}
                                {% endfor %}
                                {% if item_has_selected_product(store_item, item_sources) %}
                                    <form method="POST" action="/choose_choice" class="product-search-form" onsubmit="saveScroll()">
                                        <input type="hidden" name="item" value="{{ store_item }}">
                                        <button type="submit" class="product-search-btn">Choices</button>
                                    </form>

                                    <form method="POST" action="/clear_product_pick" class="clear-one-product-form" onsubmit="saveScroll()">
                                        <input type="hidden" name="item" value="{{ store_item }}">
                                        <button type="submit" class="clear-one-product-btn">Clear Product</button>
                                    </form>
                                {% else %}
                                    <form method="POST" action="/find_products" class="product-search-form" onsubmit="saveScroll()">
                                        <input type="hidden" name="item" value="{{ store_item }}">
                                        <button type="submit" class="product-search-btn">Products</button>
                                    </form>
                                {% endif %}
                            </div>
                    </div>
                {% endfor %}
            {% endif %}

        {% endfor %}
    {% endif %}

{% endfor %}

</div>

<div id="recipeView" style="display:none;">

<h2 class="items-title">Items by Recipe</h2>

{% if recipe_view %}
    {% for recipe in recipe_view %}
        <div class="recipe-view-card">
            <div class="recipe-view-title">
                Recipe {{ recipe.number }}:
                <a href="{{ recipe.url }}" target="_blank">{{ recipe.name }}</a>
            </div>

            {% if recipe.servings %}
                <div class="recipe-meta">
                    Servings: {{ recipe.servings }}
                </div>
            {% endif %}

            <button type="button"
                    class="detail-toggle"
                        data-detail-key="equipment|{{ recipe.url }}">
                    <span>Equipment</span>
                    <span class="detail-toggle-icon">Show ▾</span>
                </button>

                <div class="detail-content collapsed" data-detail-content="equipment|{{ recipe.url }}">
                    {% if recipe.equipment_items %}
                        <ul class="recipe-detail-list">
                            {% for equipment_item in recipe.equipment_items %}
                                <li>
                                    <div class="recipe-task-row">
                                        <input type="checkbox"
                                               class="recipe-task-check"
                                               data-task-key="equipment|{{ recipe.url }}|{{ loop.index }}">
                                        <span class="recipe-task-text">{{ equipment_item }}</span>
                                    </div>
                                </li>
                            {% endfor %}
                        </ul>
                    {% else %}
                        <div class="recipe-detail-muted">No equipment found.</div>
                    {% endif %}
                </div>

                <div class="recipe-divider"></div>

                <button type="button"
                        class="detail-toggle"
                        data-detail-key="instructions|{{ recipe.url }}">
                    <span>Instructions</span>
                    <span class="detail-toggle-icon">Show ▾</span>
                </button>

                <div class="detail-content collapsed" data-detail-content="instructions|{{ recipe.url }}">
                    {% if recipe.instruction_items %}
                        <ol class="recipe-detail-list">
                            {% for instruction in recipe.instruction_items %}
                                <li>
                                    <div class="recipe-task-row">
                                        <input type="checkbox"
                                               class="recipe-task-check"
                                               data-task-key="instruction|{{ recipe.url }}|{{ loop.index }}">
                                        <span class="recipe-task-text">{{ instruction }}</span>
                                    </div>
                                </li>
                            {% endfor %}
                        </ol>
                    {% else %}
                        <div class="recipe-detail-muted">No instructions found.</div>
                    {% endif %}
                </div>

                <div class="recipe-divider"></div>

                <button type="button"
                        class="nutrition-toggle"
                        data-nutrition-key="nutrition|{{ recipe.url }}">
                    <span>Nutrition</span>
                    <span class="nutrition-toggle-icon">Show ▾</span>
                </button>

                <div class="nutrition-content collapsed" data-nutrition-content="nutrition|{{ recipe.url }}">
                    {% if recipe.nutrition_items %}
                        <div class="nutrition-grid">
                            {% for nutrition_item in recipe.nutrition_items %}
                                <div class="nutrition-item">
                                    <div class="nutrition-label">{{ nutrition_item.label }}</div>
                                    <div class="nutrition-value">{{ nutrition_item.value }}</div>
                                </div>
                            {% endfor %}
                        </div>
                    {% else %}
                        <div class="recipe-detail-muted">No nutrition found.</div>
                    {% endif %}
                </div>

            {% if recipe["sections"] %}
                <div class="store-section-header">
                    INGREDIENTS
                </div>

                {% for section_name, section_items in recipe["sections"].items() %}
                    <div class="store-section-header collapsible-header" data-collapse-scope="recipe-section" data-collapse-key="recipe-section|{{ recipe.url }}|{{ section_name }}">
                        <span class="header-title">
                            {{ section_name }}
                            <span class="header-count">({{ section_items|length }})</span>
                        </span>
                        <span class="header-toggle-icon">Hide ▴</span>
                    </div>

                    {% for recipe_item in section_items %}
                        {% set item_key = normalize(recipe_item.name) %}
                        {% set state = item_state.get(item_key, {}) %}

                        <div class="row {% if state.get("checked") %}row-checked{% endif %}" data-key="{{ item_key }}">
                            <div class="item">

                                <div class="item-main-line">
                                    <input type="checkbox"
                                           class="item-check"
                                           {% if state.get("checked") %}checked{% endif %}>

                                    <span class="item-text {% if state.get("checked") %}checked-item-text{% endif %}">
                                        {{ recipe_item.name }}
                                    </span>
                                </div>

                                {% set selected_product = get_selected_product_for_item_key(item_key, item_sources) %}

                                {% if selected_product %}
                                    <div class="source-line product-link-line">
                                        {% if selected_product.product_cost %}
                                            <span>{{ selected_product.product_cost }}</span>
                                        {% endif %}

                                        {% if selected_product.product_location %}
                                            <span>{{ selected_product.product_location }}</span>
                                        {% endif %}

                                        {% if selected_product.product_url %}
                                            <a class="source-link" href="{{ selected_product.product_url }}" target="_blank">
                                                {{ selected_product.product_name or "selected product" }}
                                            </a>
                                        {% else %}
                                            <span>{{ selected_product.product_name or "selected product" }}</span>
                                        {% endif %}
                                    </div>
                                {% endif %}

                                <div class="source-line">
                                    {% if recipe_item.quantity %}
                                        <span>{{ recipe_item.quantity }} {{ recipe_item.unit or "" }}</span>
                                    {% endif %}

                                    {% if recipe_item.url %}
                                        <a class="source-link" href="{{ recipe_item.url }}" target="_blank">
                                            (recipe {{ recipe.number }})
                                        </a>
                                    {% endif %}
                                </div>

                            </div>

                                <div class="item-actions">
                                    {% for store_key in enabled_stores %}
                                        {% set store = available_stores.get(store_key) %}
                                        {% if store %}
                                            <button type="button"
                                                    class="store-btn {% if state.get('store') == store_key %}active{% endif %}"
                                                    data-store="{{ store_key }}"
                                                    onclick="selectStore(this, '{{ recipe_item.name }}', '{{ store_key }}')">
                                                {{ store.label }}
                                            </button>
                                        {% endif %}
                                    {% endfor %}
                                    {% if item_has_selected_product(recipe_item.name, item_sources) %}
                                        <form method="POST" action="/choose_choice" class="product-search-form" onsubmit="saveScroll()">
                                            <input type="hidden" name="item" value="{{ recipe_item.name }}">
                                            <button type="submit" class="product-search-btn">Choices</button>
                                        </form>

                                        <form method="POST" action="/clear_product_pick" class="clear-one-product-form" onsubmit="saveScroll()">
                                            <input type="hidden" name="item" value="{{ recipe_item.name }}">
                                            <button type="submit" class="clear-one-product-btn">Clear Product</button>
                                        </form>
                                    {% else %}
                                        <form method="POST" action="/find_products" class="product-search-form" onsubmit="saveScroll()">
                                            <input type="hidden" name="item" value="{{ recipe_item.name }}">
                                            <button type="submit" class="product-search-btn">Products</button>
                                        </form>
                                    {% endif %}
                                </div>
                        </div>
                    {% endfor %}
                {% endfor %}
            {% else %}
                <div class="source-line">No ingredients found for this recipe.</div>
            {% endif %}
        </div>
    {% endfor %}
{% else %}
    <div class="recipe-view-card">
        <div class="source-line">No recipe URLs yet.</div>
    </div>
{% endif %}

</div>

<script>
function saveScroll() {
    localStorage.setItem("scrollY", window.scrollY);
}

function restoreScroll() {
    const scrollY = localStorage.getItem("scrollY");

    if (scrollY !== null) {
        window.scrollTo(0, parseInt(scrollY));
        localStorage.removeItem("scrollY");
    }
}

function closeProductModal() {
    const modal = document.getElementById("productModalBackdrop");

    if (modal) {
        modal.remove();
    }

    const url = new URL(window.location.href);
    url.searchParams.delete("choose_item");

    if (url.searchParams.get("message") === "Product candidates ready") {
        url.searchParams.delete("message");
    }

    window.history.replaceState({}, "", url.toString());
}

function closeProductModalOnBackdrop(event) {
    if (event.target && event.target.id === "productModalBackdrop") {
        closeProductModal();
    }
}

function showView(viewName) {
    const sectionView = document.getElementById("sectionView");
    const storeView = document.getElementById("storeView");
    const recipeView = document.getElementById("recipeView");

    const sectionBtn = document.getElementById("sectionViewBtn");
    const storeBtn = document.getElementById("storeViewBtn");
    const recipeBtn = document.getElementById("recipeViewBtn");

    sectionView.style.display = "none";
    storeView.style.display = "none";
    recipeView.style.display = "none";

    sectionBtn.classList.remove("active");
    storeBtn.classList.remove("active");
    recipeBtn.classList.remove("active");

    if (viewName === "store") {
        storeView.style.display = "block";
        storeBtn.classList.add("active");
    } else if (viewName === "recipe") {
        recipeView.style.display = "block";
        recipeBtn.classList.add("active");
    } else {
        sectionView.style.display = "block";
        sectionBtn.classList.add("active");
    }

    localStorage.setItem("shopping_view", viewName);
}

function restoreView() {
    const savedView = localStorage.getItem("shopping_view") || "section";
    showView(savedView);
}

function saveOpenStoreUrlsSetting() {
    const toggle = document.getElementById("openStoreUrlsToggle");
    localStorage.setItem("open_store_urls", toggle.checked ? "true" : "false");
}

function restoreOpenStoreUrlsSetting() {
    const toggle = document.getElementById("openStoreUrlsToggle");
    const saved = localStorage.getItem("open_store_urls");

    if (!toggle) return;

    if (saved === null) {
        toggle.checked = true;
    } else {
        toggle.checked = saved === "true";
    }
}

function shouldOpenStoreUrls() {
    const toggle = document.getElementById("openStoreUrlsToggle");
    return toggle ? toggle.checked : true;
}

function saveShowItemButtonsSetting() {
    const toggle = document.getElementById("showItemButtonsToggle");
    const shouldShow = toggle ? toggle.checked : true;

    localStorage.setItem("show_item_buttons", shouldShow ? "true" : "false");
    applyShowItemButtonsSetting();
}

function restoreShowItemButtonsSetting() {
    const toggle = document.getElementById("showItemButtonsToggle");
    const saved = localStorage.getItem("show_item_buttons");

    if (!toggle) return;

    if (saved === null) {
        toggle.checked = true;
    } else {
        toggle.checked = saved === "true";
    }

    applyShowItemButtonsSetting();
}

function applyShowItemButtonsSetting() {
    const toggle = document.getElementById("showItemButtonsToggle");
    const shouldShow = toggle ? toggle.checked : true;

    if (shouldShow) {
        document.body.classList.remove("hide-item-buttons");
    } else {
        document.body.classList.add("hide-item-buttons");
    }
}

function saveShowBestProductSetting() {
    const toggle = document.getElementById("showBestProductToggle");
    const shouldShow = toggle ? toggle.checked : true;

    localStorage.setItem("show_best_product", shouldShow ? "true" : "false");
    applyShowBestProductSetting();
}

function restoreShowBestProductSetting() {
    const toggle = document.getElementById("showBestProductToggle");
    const saved = localStorage.getItem("show_best_product");

    if (!toggle) return;

    if (saved === null) {
        toggle.checked = true;
    } else {
        toggle.checked = saved === "true";
    }

    applyShowBestProductSetting();
}

function applyShowBestProductSetting() {
    const toggle = document.getElementById("showBestProductToggle");
    const shouldShow = toggle ? toggle.checked : true;

    if (shouldShow) {
        document.body.classList.remove("hide-best-product");
    } else {
        document.body.classList.add("hide-best-product");
    }
}

function saveHideCheckedItemsSetting() {
    const toggle = document.getElementById("hideCheckedItemsToggle");
    const shouldHide = toggle ? toggle.checked : false;

    localStorage.setItem("hide_checked_items", shouldHide ? "true" : "false");
    applyHideCheckedItemsSetting();
}

function restoreHideCheckedItemsSetting() {
    const toggle = document.getElementById("hideCheckedItemsToggle");
    const saved = localStorage.getItem("hide_checked_items");

    if (!toggle) return;

    toggle.checked = saved === "true";
    applyHideCheckedItemsSetting();
}

function applyHideCheckedItemsSetting() {
    const toggle = document.getElementById("hideCheckedItemsToggle");
    const shouldHide = toggle ? toggle.checked : false;

    if (shouldHide) {
        document.body.classList.add("hide-checked-items");
    } else {
        document.body.classList.remove("hide-checked-items");
    }
}

function saveCompactModeSetting() {
    const toggle = document.getElementById("compactModeToggle");
    const compact = toggle ? toggle.checked : false;

    localStorage.setItem("compact_mode", compact ? "true" : "false");
    applyCompactModeSetting();
}

function restoreCompactModeSetting() {
    const toggle = document.getElementById("compactModeToggle");
    const saved = localStorage.getItem("compact_mode");

    if (!toggle) return;

    toggle.checked = saved === "true";
    applyCompactModeSetting();
}

function applyCompactModeSetting() {
    const toggle = document.getElementById("compactModeToggle");
    const compact = toggle ? toggle.checked : false;

    if (compact) {
        document.body.classList.add("compact-mode");
    } else {
        document.body.classList.remove("compact-mode");
    }
}

function collapseStorageKey(key) {
    return "shopping_section_collapsed|" + key;
}

function setCollapsedRange(header, collapsed) {
    const scope = header.dataset.collapseScope || "";
    let next = header.nextElementSibling;

    while (next) {
        if (scope === "section" && next.classList.contains("section-header-row")) break;
        if (scope === "store" && next.classList.contains("store-header-row")) break;
        if (scope === "store-section" && (next.classList.contains("store-section-header") || next.classList.contains("store-header-row"))) break;
        if (scope === "recipe-section" && (next.classList.contains("store-section-header") || next.classList.contains("recipe-view-card"))) break;

        if (collapsed) {
            next.classList.add("collapsed-by-header");
        } else {
            next.classList.remove("collapsed-by-header");
        }

        next = next.nextElementSibling;
    }

    const icon = header.querySelector(".header-toggle-icon");
    if (icon) {
        icon.textContent = collapsed ? "Show ▾" : "Hide ▴";
    }
}

function setupCollapsibleHeaders() {
    document.querySelectorAll(".collapsible-header").forEach(header => {
        const key = header.dataset.collapseKey || header.textContent.trim();
        const saved = localStorage.getItem(collapseStorageKey(key));
        const collapsed = saved === "true";

        setCollapsedRange(header, collapsed);

        header.addEventListener("click", function(event) {
            if (event.target.closest("a, button, input, form")) return;

            const isCollapsed = header.querySelector(".header-toggle-icon")?.textContent.includes("Show");
            const nextCollapsed = !isCollapsed;

            setCollapsedRange(header, nextCollapsed);
            localStorage.setItem(collapseStorageKey(key), nextCollapsed ? "true" : "false");
        });
    });
}


function saveState(itemKey, checked, store) {
    return fetch("/save_state", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            item_key: itemKey,
            checked: checked,
            store: store
        })
    });
}

function selectStore(button, item, store) {
    const row = button.closest(".row");
    const key = row.dataset.key;

    if (!key) return;

    const openUrls = shouldOpenStoreUrls();
    const isCurrentlySelected = button.classList.contains("active");
    const newStore = isCurrentlySelected ? "unselected" : store;

    // Update every matching copy of this item immediately with no page refresh.
    document.querySelectorAll('.row[data-key="' + key + '"]').forEach(matchingRow => {
        matchingRow.querySelectorAll(".store-btn").forEach(btn => {
            btn.classList.remove("active");
        });

        if (newStore !== "unselected") {
            const matchingBtn = matchingRow.querySelector('.store-btn[data-store="' + newStore + '"]');

            if (matchingBtn) {
                matchingBtn.classList.add("active");
            }
        }
    });

    saveState(key, null, newStore)
        .catch(err => {
            console.log("State save failed:", err);
        });

    if (!openUrls || newStore === "unselected") {
        return;
    }

    const storeUrls = {{ store_urls | tojson }};
    const baseUrl = storeUrls[store] || "";

    if (!baseUrl) {
        console.log("Store URL missing for:", store);
        return;
    }

    window.open(
        baseUrl + encodeURIComponent(item),
        "_blank",
        "width=1200,height=800,menubar=no,toolbar=no,location=yes,resizable=yes,scrollbars=yes"
    );
}

function setupCheckboxes() {
    document.querySelectorAll(".row").forEach(row => {
        const key = row.dataset.key;
        const checkbox = row.querySelector(".item-check");
        const itemText = row.querySelector(".item-text");

        if (!key || !checkbox || !itemText) return;

        checkbox.addEventListener("change", function () {
            const isChecked = checkbox.checked;

            document.querySelectorAll('.row[data-key="' + key + '"]').forEach(matchingRow => {
                const matchingCheckbox = matchingRow.querySelector(".item-check");
                const matchingText = matchingRow.querySelector(".item-text");

                if (matchingCheckbox) {
                    matchingCheckbox.checked = isChecked;
                }

                if (matchingText) {
                    if (isChecked) {
                        matchingText.classList.add("checked-item-text");
                    } else {
                        matchingText.classList.remove("checked-item-text");
                    }
                }

                if (isChecked) {
                    matchingRow.classList.add("row-checked");
                } else {
                    matchingRow.classList.remove("row-checked");
                }
            });

            saveState(key, isChecked, null);
        });
    });
}

function recipeTaskStorageKey(rawKey) {
    return "recipe_task_done|" + rawKey;
}

function setupRecipeTaskCheckboxes() {
    document.querySelectorAll(".recipe-task-check").forEach(checkbox => {
        const rawKey = checkbox.dataset.taskKey || "";
        const storageKey = recipeTaskStorageKey(rawKey);
        const textEl = checkbox.closest(".recipe-task-row")?.querySelector(".recipe-task-text");

        const saved = localStorage.getItem(storageKey);

        if (saved === "true") {
            checkbox.checked = true;
            if (textEl) {
                textEl.classList.add("done");
            }
        }

        checkbox.addEventListener("change", function () {
            localStorage.setItem(storageKey, checkbox.checked ? "true" : "false");

            if (textEl) {
                if (checkbox.checked) {
                    textEl.classList.add("done");
                } else {
                    textEl.classList.remove("done");
                }
            }
        });
    });
}

function setupDetailToggles() {
    document.querySelectorAll(".detail-toggle").forEach(button => {
        const key = button.dataset.detailKey || "";
        const content = document.querySelector('[data-detail-content="' + key + '"]');
        const icon = button.querySelector(".detail-toggle-icon");

        if (!content || !icon) return;

        const storageKey = "recipe_detail_collapsed|" + key;
        const savedState = localStorage.getItem(storageKey);

        if (savedState === "open") {
            content.classList.remove("collapsed");
            icon.textContent = "Hide ▴";
        } else {
            content.classList.add("collapsed");
            icon.textContent = "Show ▾";
        }

        button.addEventListener("click", function () {
            const isCollapsed = content.classList.contains("collapsed");

            if (isCollapsed) {
                content.classList.remove("collapsed");
                icon.textContent = "Hide ▴";
                localStorage.setItem(storageKey, "open");
            } else {
                content.classList.add("collapsed");
                icon.textContent = "Show ▾";
                localStorage.setItem(storageKey, "closed");
            }
        });
    });
}

function setupNutritionToggles() {
    document.querySelectorAll(".nutrition-toggle").forEach(button => {
        const key = button.dataset.nutritionKey || "";
        const content = document.querySelector('[data-nutrition-content="' + key + '"]');
        const icon = button.querySelector(".nutrition-toggle-icon");

        if (!content || !icon) return;

        const storageKey = "nutrition_collapsed|" + key;
        const savedState = localStorage.getItem(storageKey);

        if (savedState === "open") {
            content.classList.remove("collapsed");
            icon.textContent = "Hide ▴";
        } else {
            content.classList.add("collapsed");
            icon.textContent = "Show ▾";
        }

        button.addEventListener("click", function () {
            const isCollapsed = content.classList.contains("collapsed");

            if (isCollapsed) {
                content.classList.remove("collapsed");
                icon.textContent = "Hide ▴";
                localStorage.setItem(storageKey, "open");
            } else {
                content.classList.add("collapsed");
                icon.textContent = "Show ▾";
                localStorage.setItem(storageKey, "closed");
            }
        });
    });
}

function resetAllRecipeCheckboxes() {
    Object.keys(localStorage).forEach(key => {
        if (key.startsWith("recipe_task_done|")) {
            localStorage.removeItem(key);
        }
    });

    document.querySelectorAll(".recipe-task-check").forEach(checkbox => {
        checkbox.checked = false;

        const textEl = checkbox.closest(".recipe-task-row")?.querySelector(".recipe-task-text");

        if (textEl) {
            textEl.classList.remove("done");
        }
    });
}



function setAllBulkPreviewItems(checked) {
    document.querySelectorAll(".bulk-preview-checkbox").forEach(checkbox => {
        checkbox.checked = checked;
    });
}

function validateBulkSelection() {
    const checkedItems = document.querySelectorAll(".bulk-preview-checkbox:checked");

    if (checkedItems.length === 0) {
        alert("Select at least one ingredient to grab.");
        return false;
    }

    return true;
}

function closeBulkPreviewModal() {
    const modal = document.getElementById("bulkPreviewModalBackdrop");

    if (modal) {
        modal.remove();
    }

    const url = new URL(window.location.href);
    url.searchParams.delete("bulk_preview");

    if (url.searchParams.get("message") === "Review products before grabbing") {
        url.searchParams.delete("message");
    }

    window.history.replaceState({}, "", url.toString());
}

function closeBulkPreviewOnBackdrop(event) {
    if (event.target && event.target.id === "bulkPreviewModalBackdrop") {
        closeBulkPreviewModal();
    }
}

function hideBulkProgressModal() {
    const modal = document.getElementById("bulkProgressModalBackdrop");

    if (modal) {
        modal.remove();
    }

    const url = new URL(window.location.href);
    url.searchParams.delete("bulk_job");

    window.history.replaceState({}, "", url.toString());
}

let bulkJobId = "{{ bulk_job_id or '' }}";
let bulkPollTimer = null;

function showBulkProgressModalForActiveJob(jobId) {
    if (!jobId || document.getElementById("bulkProgressModalBackdrop")) return;

    bulkJobId = jobId;

    const modal = document.createElement("div");
    modal.className = "product-modal-backdrop";
    modal.id = "bulkProgressModalBackdrop";
    modal.innerHTML = `
        <div class="product-choice-card" role="dialog" aria-modal="true">
            <div class="product-choice-header">
                <div class="product-choice-title-row">
                    <div style="width:52px;"></div>
                    <h2>Grabbing Best Products</h2>
                    <button type="button" class="product-close-btn" onclick="hideBulkProgressModal()">Hide</button>
                </div>

                <p class="product-choice-subtitle">
                    You can cancel this operation at any time.
                </p>
            </div>

            <div class="bulk-progress-status">
                <div id="bulkSpinner" class="bulk-spinner"></div>

                <div class="bulk-active-line">
                    Active ingredient:
                    <span id="bulkActiveIngredient" class="bulk-active-ingredient">Starting...</span>
                </div>

                <div id="bulkSummary" class="product-choice-subtitle">Preparing...</div>

                <div class="bulk-progress-bar-wrap">
                    <div id="bulkProgressBar" class="bulk-progress-bar"></div>
                </div>
            </div>

            <div id="bulkProgressList" class="bulk-preview-list"></div>

            <div class="bulk-alt-modal-backdrop" id="bulkAltModalBackdrop" onclick="closeBulkChoicesOnBackdrop(event)">
                <div class="bulk-alt-modal" role="dialog" aria-modal="true">
                    <div class="bulk-alt-modal-header">
                        <div style="width:52px;"></div>
                        <h2 class="bulk-alt-modal-title">Choice Products</h2>
                        <button type="button" class="product-close-btn" onclick="closeBulkChoicesModal()">Close</button>
                    </div>

                    <p class="bulk-alt-modal-subtitle" id="bulkAltModalSubtitle"></p>

                    <div id="bulkAltModalList"></div>
                </div>
            </div>

            <div id="bulkReviewNote" class="bulk-review-note" style="display:none;">
                Review the selected products below. Expand choices to make changes before finishing.
            </div>

            <div class="bulk-modal-actions">
                <button type="button" class="bulk-cancel-btn" id="bulkCancelBtn" onclick="cancelBulkGrab()">Cancel Operation</button>
                <button type="button" class="bulk-finish-btn" id="bulkFinishBtn" style="display:none;" onclick="finishBulkReview()">Finish / Keep Selections</button>
                <button type="button" class="bulk-secondary-btn" onclick="hideBulkProgressModal()">Hide</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const url = new URL(window.location.href);
    url.searchParams.set("bulk_job", jobId);
    window.history.replaceState({}, "", url.toString());

    pollBulkGrab();
}

function pollForActiveBulkJob() {
    if (bulkJobId) return;

    fetch("/active_bulk_product_status")
        .then(response => response.json())
        .then(data => {
            if (data.ok && data.bulk_job_id) {
                showBulkProgressModalForActiveJob(data.bulk_job_id);
                return;
            }

            setTimeout(pollForActiveBulkJob, 2000);
        })
        .catch(err => {
            console.log("Active bulk product poll failed:", err);
            setTimeout(pollForActiveBulkJob, 3000);
        });
}


function closeBulkChoicesModal() {
    const modal = document.getElementById("bulkAltModalBackdrop");
    if (modal) {
        modal.classList.remove("open");
    }
}

function closeBulkChoicesOnBackdrop(event) {
    if (event.target && event.target.id === "bulkAltModalBackdrop") {
        closeBulkChoicesModal();
    }
}

function productIdentity(value) {
    return String(value || "").trim().toLowerCase();
}

function isSameProduct(product, selectedProduct, selectedUrl) {
    const productUrl = productIdentity(product && product.product_url);
    const selectedProductUrl = productIdentity(selectedProduct && selectedProduct.product_url);
    const selectedEntryUrl = productIdentity(selectedUrl);

    if (productUrl && (productUrl === selectedEntryUrl || productUrl === selectedProductUrl)) {
        return true;
    }

    const productName = productIdentity(product && product.product_name);
    const selectedName = productIdentity(selectedProduct && selectedProduct.product_name);
    const productCost = productIdentity(product && product.product_cost);
    const selectedCost = productIdentity(selectedProduct && selectedProduct.product_cost);

    return Boolean(productName && selectedName && productName === selectedName && (!selectedCost || productCost === selectedCost));
}

function openBulkChoicesModal(jobId, entry) {
    const modal = document.getElementById("bulkAltModalBackdrop");
    const subtitle = document.getElementById("bulkAltModalSubtitle");
    const list = document.getElementById("bulkAltModalList");

    if (!modal || !subtitle || !list) return;

    subtitle.textContent = `Choose an choice for: ${entry.item}`;
    list.innerHTML = "";

    (entry.products || []).forEach(product => {
        const option = document.createElement("div");
        option.className = "bulk-alt-option";

        const details = document.createElement("div");

        let name;

        if (product.product_url) {
            name = document.createElement("a");
            name.href = product.product_url;
            name.target = "_blank";
            name.rel = "noopener noreferrer";
            name.className = "bulk-alt-name bulk-alt-link";
            name.textContent = product.product_name || "Unknown product";
        } else {
            name = document.createElement("div");
            name.className = "bulk-alt-name";
            name.textContent = product.product_name || "Unknown product";
        }

        const metaLine = document.createElement("div");
        metaLine.className = "bulk-alt-meta";
        metaLine.textContent = `${product.product_location || product.store || ""}${product.product_cost ? " • " + product.product_cost : ""}${product.is_organic ? " • ORGANIC" : ""}`;

        details.appendChild(name);
        details.appendChild(metaLine);

        const selectBtn = document.createElement("button");
        selectBtn.type = "button";
        selectBtn.className = "bulk-alt-select-btn";

        if (isSameProduct(product, entry.selected_product || null, entry.selected_product_url || "")) {
            selectBtn.classList.add("selected");
            selectBtn.textContent = "Selected";
        } else {
            selectBtn.textContent = "Choose";
        }

        selectBtn.onclick = function() {
            selectBulkChoice(jobId, entry.item, product);
            closeBulkChoicesModal();
        };

        option.appendChild(details);
        option.appendChild(selectBtn);
        list.appendChild(option);
    });

    modal.classList.add("open");
}

function renderBulkProgress(job) {
    const activeEl = document.getElementById("bulkActiveIngredient");
    const summaryEl = document.getElementById("bulkSummary");
    const barEl = document.getElementById("bulkProgressBar");
    const listEl = document.getElementById("bulkProgressList");
    const spinnerEl = document.getElementById("bulkSpinner");

    if (!activeEl || !summaryEl || !barEl || !listEl) return;

    const total = job.total || 0;
    const completed = job.completed || 0;
    const added = job.added || 0;
    const failed = job.failed || 0;
    const skipped = job.skipped || 0;
    const status = job.status || "running";
    const active = job.active_item || "Waiting...";

    activeEl.textContent = active;
    summaryEl.textContent = `${completed}/${total} done • Added ${added} • Skipped ${skipped} • Failed ${failed} • Status: ${status}`;

    const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
    barEl.style.width = percent + "%";

    if (spinnerEl) {
        spinnerEl.style.display = (status === "running" || status === "queued" || status === "cancel_requested") ? "block" : "none";
    }

    listEl.innerHTML = "";

    (job.items || []).forEach((entry, index) => {
        const row = document.createElement("div");
        row.className = "bulk-progress-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "bulk-progress-check";
        checkbox.disabled = true;
        checkbox.checked = ["done", "failed", "skipped", "cancelled"].includes(entry.status);

        const main = document.createElement("div");
        main.className = "bulk-progress-main";

        const titleLine = document.createElement("div");
        titleLine.className = "bulk-progress-title-line";

        const text = document.createElement("span");
        text.className = "bulk-progress-text";
        text.textContent = `${index + 1}. ${entry.item}`;

        if (entry.status === "done" || entry.status === "skipped") {
            text.classList.add("done");
        }

        if (entry.status === "running") {
            text.classList.add("active");
        }

        titleLine.appendChild(text);

        const storeLine = document.createElement("div");
        storeLine.className = "bulk-progress-store-line";
        const storeName = entry.selected_store_label || entry.selected_store || "";

        if (storeName && entry.selected_product_url) {
            const storeLink = document.createElement("a");
            storeLink.href = entry.selected_product_url;
            storeLink.target = "_blank";
            storeLink.rel = "noopener noreferrer";
            storeLink.textContent = storeName;
            storeLink.className = "bulk-progress-store-link";
            storeLine.appendChild(storeLink);
        } else {
            storeLine.textContent = storeName;
        }

        main.appendChild(titleLine);

        if (storeLine.textContent) {
            main.appendChild(storeLine);
        }

        if (Array.isArray(entry.scraper_urls) && entry.scraper_urls.length > 0) {
            const urlBlock = document.createElement("div");
            urlBlock.className = "bulk-skip-reason";

            entry.scraper_urls.forEach((scraperUrl, urlIndex) => {
                const link = document.createElement("a");
                link.href = scraperUrl;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.className = "bulk-progress-store-link";
                link.textContent = scraperUrl;

                urlBlock.appendChild(document.createTextNode(urlIndex === 0 ? "Scraper URL: " : "Scraper URL: "));
                urlBlock.appendChild(link);
                urlBlock.appendChild(document.createElement("br"));
            });

            main.appendChild(urlBlock);
        }

        const meta = document.createElement("div");
        meta.className = "bulk-progress-meta";

        if (entry.status === "failed") {
            meta.classList.add("bulk-error");
        }

        if (entry.status === "done" && (entry.product_name || entry.product_cost)) {
            const productName = document.createElement("div");
            productName.className = "bulk-product-name";
            productName.textContent = entry.product_name || "Selected product";
            meta.appendChild(productName);

            if (entry.product_cost) {
                const productPrice = document.createElement("div");
                productPrice.className = "bulk-product-price";
                productPrice.textContent = entry.product_cost;
                meta.appendChild(productPrice);
            }
        } else if (entry.status === "skipped" && entry.skip_reason) {
            const statusLine = document.createElement("div");
            statusLine.className = "bulk-product-status";
            statusLine.textContent = "skipped";
            meta.appendChild(statusLine);

            const reasonLine = document.createElement("div");
            reasonLine.className = "bulk-product-name";
            reasonLine.textContent = entry.skip_reason;
            meta.appendChild(reasonLine);
        } else {
            const statusLine = document.createElement("div");
            statusLine.className = "bulk-product-status";
            statusLine.textContent = entry.status || "pending";
            meta.appendChild(statusLine);
        }

        if (entry.status === "skipped" && entry.search_url) {
            const skippedSearchLine = document.createElement("div");
            skippedSearchLine.className = "bulk-skip-reason";

            const skippedSearchLink = document.createElement("a");
            skippedSearchLink.href = entry.search_url;
            skippedSearchLink.target = "_blank";
            skippedSearchLink.rel = "noopener noreferrer";
            skippedSearchLink.className = "bulk-progress-store-link";
            skippedSearchLink.textContent = entry.search_label || "Open store search";

            skippedSearchLine.appendChild(document.createTextNode("Search: "));
            skippedSearchLine.appendChild(skippedSearchLink);
            main.appendChild(skippedSearchLine);
        }

        row.appendChild(checkbox);
        row.appendChild(main);
        row.appendChild(meta);

        if ((entry.products || []).length > 1) {
            const altButton = document.createElement("button");
            altButton.type = "button";
            altButton.className = "bulk-alt-toggle";
            altButton.textContent = "Choices";
            altButton.onclick = function() {
                openBulkChoicesModal(job.job_id, entry);
            };
            row.appendChild(altButton);
        }

        listEl.appendChild(row);
    });

    const reviewNote = document.getElementById("bulkReviewNote");
    const finishBtn = document.getElementById("bulkFinishBtn");
    const cancelBtn = document.getElementById("bulkCancelBtn");

    if (status === "done") {
        if (bulkPollTimer) {
            clearTimeout(bulkPollTimer);
            bulkPollTimer = null;
        }

        bulkJobId = "";

        const modal = document.getElementById("bulkProgressModalBackdrop");

        if (modal) {
            modal.remove();
        }

        refreshShoppingListSilently("Best product grab complete");
        return;
    }

    if (status === "review") {
        if (reviewNote) reviewNote.style.display = "block";
        if (finishBtn) finishBtn.style.display = "block";
        if (cancelBtn) cancelBtn.style.display = "none";

        activeEl.textContent = "Review selected products";
        summaryEl.textContent = `${completed}/${total} done • Added ${added} • Skipped ${skipped} • Failed ${failed} • Ready for review`;

        if (bulkPollTimer) {
            clearTimeout(bulkPollTimer);
            bulkPollTimer = null;
        }

        // Keep polling during review so actions on another device
        // like Finish / Keep Selections are reflected here too.
        bulkPollTimer = setTimeout(pollBulkGrab, 2000);

        return;
    }

    if (["cancelled", "error"].includes(status)) {
        if (bulkPollTimer) {
            clearTimeout(bulkPollTimer);
            bulkPollTimer = null;
        }

        setTimeout(() => {
            const url = new URL(window.location.href);
            url.searchParams.delete("bulk_job");
            url.searchParams.set("message", "Best product grab cancelled");
            window.location.href = url.toString();
        }, 1600);
    }
}

function pollBulkGrab() {
    if (!bulkJobId) return;

    fetch(`/bulk_product_status/${bulkJobId}`)
        .then(response => response.json())
        .then(job => {
            if (!job.ok) {
                console.log("Bulk job status error:", job);
                return;
            }

            renderBulkProgress(job);

            if (!["review", "done", "cancelled", "error"].includes(job.status)) {
                bulkPollTimer = setTimeout(pollBulkGrab, 1000);
            }
        })
        .catch(err => {
            console.log("Bulk status poll failed:", err);
            bulkPollTimer = setTimeout(pollBulkGrab, 2000);
        });
}

function cancelBulkGrab() {
    if (!bulkJobId) return;

    fetch(`/cancel_bulk_product_grab/${bulkJobId}`, {
        method: "POST"
    })
        .then(response => response.json())
        .then(job => {
            renderBulkProgress(job);
        })
        .catch(err => {
            console.log("Cancel failed:", err);
        });
}


function selectBulkChoice(jobId, item, product) {
    fetch(`/bulk_select_product/${jobId}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            item: item,
            product: product
        })
    })
        .then(response => response.json())
        .then(job => {
            renderBulkProgress(job);
        })
        .catch(err => {
            console.log("Choice selection failed:", err);
        });
}

function refreshShoppingListSilently(doneMessage) {
    const currentScrollY = window.scrollY;
    const savedView = localStorage.getItem("shopping_view") || "section";

    const cleanUrl = new URL(window.location.href);
    cleanUrl.searchParams.delete("bulk_job");
    cleanUrl.searchParams.delete("bulk_preview");
    cleanUrl.searchParams.delete("choose_item");

    return fetch(cleanUrl.toString(), {
        method: "GET",
        headers: {
            "X-Requested-With": "fetch"
        }
    })
        .then(response => response.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, "text/html");

            ["sectionView", "storeView", "recipeView"].forEach(id => {
                const newEl = doc.getElementById(id);
                const oldEl = document.getElementById(id);

                if (newEl && oldEl) {
                    oldEl.replaceWith(newEl);
                }
            });

            const existingMessage = document.querySelector(".message");

            if (existingMessage) {
                existingMessage.textContent = doneMessage || "Best product grab complete";
            } else {
                const message = document.createElement("div");
                message.className = "message";
                message.textContent = doneMessage || "Best product grab complete";

                const h1 = document.querySelector("h1");
                if (h1 && h1.parentNode) {
                    h1.insertAdjacentElement("afterend", message);
                }
            }

            setupCheckboxes();
            setupCollapsibleHeaders();
            applyShowBestProductSetting();
            showView(savedView);

            window.history.replaceState({}, "", cleanUrl.toString());
            window.scrollTo(0, currentScrollY);
        });
}

function finishBulkReview() {
    if (!bulkJobId) return;

    const finishBtn = document.getElementById("bulkFinishBtn");

    if (finishBtn) {
        finishBtn.disabled = true;
        finishBtn.textContent = "Saving...";
    }

    fetch(`/finish_bulk_product_review/${bulkJobId}`, {
        method: "POST"
    })
        .then(response => response.json())
        .then(job => {
            bulkJobId = "";

            if (bulkPollTimer) {
                clearTimeout(bulkPollTimer);
                bulkPollTimer = null;
            }

            const modal = document.getElementById("bulkProgressModalBackdrop");

            if (modal) {
                modal.remove();
            }

            return refreshShoppingListSilently("Best product grab complete");
        })
        .catch(err => {
            console.log("Finish review failed:", err);

            if (finishBtn) {
                finishBtn.disabled = false;
                finishBtn.textContent = "Finish / Keep Selections";
            }
        });
}


let extractJobId = "{{ extract_job_id or '' }}";
let extractPollTimer = null;

function hideExtractProgressModal() {
    const modal = document.getElementById("extractProgressModalBackdrop");

    if (modal) {
        modal.remove();
    }

    const url = new URL(window.location.href);
    url.searchParams.delete("extract_job");

    window.history.replaceState({}, "", url.toString());
}

function renderExtractProgress(job) {
    const statusText = document.getElementById("extractStatusText");
    const summary = document.getElementById("extractSummary");
    const bar = document.getElementById("extractProgressBar");
    const spinner = document.getElementById("extractSpinner");
    const urlList = document.getElementById("extractUrlList");

    if (!statusText || !summary || !bar) return;

    statusText.textContent = job.message || job.status || "Working...";
    summary.textContent = job.summary || "Working...";
    bar.style.width = (job.progress || 0) + "%";

    if (spinner) {
        spinner.style.display = job.done ? "none" : "block";
    }

    if (urlList && Array.isArray(job.urls)) {
        urlList.innerHTML = "";

        job.urls.forEach((entry, index) => {
            const row = document.createElement("div");
            row.className = "bulk-progress-item";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.disabled = true;
            checkbox.className = "bulk-progress-check";
            checkbox.checked = entry.checked === true || ["done", "skipped"].includes(entry.status);

            const main = document.createElement("div");
            main.className = "bulk-progress-main";

            const titleLine = document.createElement("div");
            titleLine.className = "bulk-progress-title-line";

            const text = document.createElement("span");
            text.className = "bulk-progress-text";
            text.textContent = `${index + 1}. ${entry.url || entry}`;

            if (["done", "skipped"].includes(entry.status)) {
                text.classList.add("done");
            }

            if (["downloading", "extracting", "reading output", "saving"].includes(entry.status)) {
                text.classList.add("active");
            }

            titleLine.appendChild(text);

            const detailLine = document.createElement("div");
            detailLine.className = entry.status === "failed" ? "bulk-skip-reason bulk-error" : "bulk-skip-reason";

            let statusLabel = entry.status || "queued";
            let message = entry.message || "";
            detailLine.textContent = message ? `${statusLabel} • ${message}` : statusLabel;

            main.appendChild(titleLine);
            main.appendChild(detailLine);

            row.appendChild(checkbox);
            row.appendChild(main);
            urlList.appendChild(row);
        });
    }

    if (job.done) {
        if (extractPollTimer) {
            clearTimeout(extractPollTimer);
            extractPollTimer = null;
        }

        setTimeout(() => {
            const url = new URL(window.location.href);
            url.searchParams.delete("extract_job");
            url.searchParams.set("message", job.success ? (job.summary || "Extraction complete") : (job.summary || "Extraction failed"));
            window.location.href = url.toString();
        }, 1200);
    }
}

function pollExtractProgress() {
    if (!extractJobId) return;

    fetch(`/extract_status/${extractJobId}`)
        .then(response => response.json())
        .then(job => {
            if (!job.ok) {
                console.log("Extract job status error:", job);
                return;
            }

            renderExtractProgress(job);

            if (!job.done) {
                extractPollTimer = setTimeout(pollExtractProgress, 1000);
            }
        })
        .catch(err => {
            console.log("Extract status poll failed:", err);
            extractPollTimer = setTimeout(pollExtractProgress, 2000);
        });
}

function showExtractModalForActiveJob(jobId) {
    if (!jobId || document.getElementById("extractProgressModalBackdrop")) return;

    extractJobId = jobId;

    const modal = document.createElement("div");
    modal.className = "product-modal-backdrop";
    modal.id = "extractProgressModalBackdrop";
    modal.innerHTML = `
        <div class="product-choice-card" role="dialog" aria-modal="true">
            <div class="product-choice-header">
                <div class="product-choice-title-row">
                    <div style="width:52px;"></div>
                    <h2>Extracting Ingredients</h2>
                    <button type="button" class="product-close-btn" onclick="hideExtractProgressModal()">Hide</button>
                </div>

                <p class="product-choice-subtitle">
                    Your recipes are being processed. This page will update when extraction finishes.
                </p>
            </div>

            <div class="bulk-progress-status">
                <div id="extractSpinner" class="bulk-spinner"></div>
                <div class="bulk-active-line">
                    Status:
                    <span id="extractStatusText" class="bulk-active-ingredient">Starting...</span>
                </div>
                <div id="extractSummary" class="product-choice-subtitle">Preparing extraction...</div>
                <div class="bulk-progress-bar-wrap">
                    <div id="extractProgressBar" class="bulk-progress-bar"></div>
                </div>
            </div>

            <div id="extractUrlList" class="bulk-preview-list"></div>

            <div class="bulk-modal-actions">
                <button type="button" class="bulk-secondary-btn" onclick="hideExtractProgressModal()">Hide</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const url = new URL(window.location.href);
    url.searchParams.set("extract_job", jobId);
    window.history.replaceState({}, "", url.toString());

    pollExtractProgress();
}

function pollForActiveExtractJob() {
    if (extractJobId) return;

    fetch("/active_extract_status")
        .then(response => response.json())
        .then(data => {
            if (data.ok && data.extract_job_id) {
                showExtractModalForActiveJob(data.extract_job_id);
                return;
            }

            setTimeout(pollForActiveExtractJob, 2000);
        })
        .catch(err => {
            console.log("Active extract poll failed:", err);
            setTimeout(pollForActiveExtractJob, 3000);
        });
}



let nearestJobId = "{{ nearest_job_id or '' }}";
let nearestPollTimer = null;
let activeNearestPollTimer = null;

function hideNearestProgressModal() {
    const modal = document.getElementById("nearestProgressModalBackdrop");

    if (modal) {
        modal.remove();
    }

    nearestJobId = "";

    if (nearestPollTimer) {
        clearTimeout(nearestPollTimer);
        nearestPollTimer = null;
    }

    const url = new URL(window.location.href);
    url.searchParams.delete("nearest_job");

    window.history.replaceState({}, "", url.toString());

    if (!activeNearestPollTimer) {
        activeNearestPollTimer = setTimeout(pollForActiveNearestJob, 1000);
    }
}

function nearestStoreDisplayLine(line) {
    const raw = String(line || "").trim();
    const lower = raw.toLowerCase();

    if (!raw) return null;

    // Checkbox area only shows stores being reviewed.
    if (
        lower.includes("could not detect version_main") ||
        lower.includes("saving home address") ||
        lower.includes("address constants") ||
        lower.includes("queued nearest-store") ||
        lower.includes("starting find_nearest") ||
        lower.includes("loaded stores") ||
        lower.includes("getting home coordinates") ||
        lower.includes("home coordinates") ||
        lower.includes("saved results") ||
        lower.includes("nearest stores update complete")
    ) {
        return null;
    }

    if (lower.includes("processing")) {
        const parts = raw.split(/processing/i);
        const storeName = (parts.length > 1 ? parts[1] : raw).trim();
        return storeName ? `Reviewing ${storeName}` : raw;
    }

    if (lower.startsWith("reviewing ")) {
        return raw;
    }

    return null;
}

function renderNearestProgress(job) {
    const statusText = document.getElementById("nearestStatusText");
    const summary = document.getElementById("nearestSummary");
    const bar = document.getElementById("nearestProgressBar");
    const spinner = document.getElementById("nearestSpinner");
    const logList = document.getElementById("nearestLogList");

    if (!statusText || !summary || !bar) return;

    statusText.textContent = job.message || job.status || "Working...";
    summary.textContent = job.summary || "Updating nearest stores...";
    bar.style.width = (job.progress || 0) + "%";

    if (spinner) {
        spinner.style.display = job.done ? "none" : "block";
    }

    if (logList && Array.isArray(job.logs)) {
        logList.innerHTML = "";

        const storeLines = [];
        const seenStores = new Set();

        job.logs.forEach(line => {
            const displayLine = nearestStoreDisplayLine(line);

            if (!displayLine) return;

            const key = displayLine.toLowerCase();

            if (seenStores.has(key)) return;

            seenStores.add(key);
            storeLines.push(displayLine);
        });

        storeLines.slice(-40).forEach((line, index) => {
            const row = document.createElement("div");
            row.className = "bulk-progress-item";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.disabled = true;
            checkbox.className = "bulk-progress-check";
            checkbox.checked = job.done || index < storeLines.length - 1;

            const main = document.createElement("div");
            main.className = "bulk-progress-main";

            const titleLine = document.createElement("div");
            titleLine.className = "bulk-progress-title-line";

            const text = document.createElement("span");
            text.className = "bulk-progress-text";
            text.textContent = line;

            if (!job.done && index === Math.max(0, storeLines.slice(-40).length - 1)) {
                text.classList.add("active");
            } else {
                text.classList.add("done");
            }

            titleLine.appendChild(text);
            main.appendChild(titleLine);

            row.appendChild(checkbox);
            row.appendChild(main);
            logList.appendChild(row);
        });
    }

    if (job.done) {
        if (nearestPollTimer) {
            clearTimeout(nearestPollTimer);
            nearestPollTimer = null;
        }

        setTimeout(() => {
            const url = new URL(window.location.href);
            url.searchParams.delete("nearest_job");
            url.searchParams.set("message", job.success ? (job.summary || "Nearest stores updated") : (job.summary || "Nearest store update failed"));
            window.location.href = url.toString();
        }, 1200);
    }
}

function pollNearestProgress() {
    if (!nearestJobId) return;

    fetch(`/nearest_stores_status/${nearestJobId}`)
        .then(response => response.json())
        .then(job => {
            if (!job.ok) {
                console.log("Nearest stores status error:", job);
                return;
            }

            renderNearestProgress(job);

            if (!job.done) {
                nearestPollTimer = setTimeout(pollNearestProgress, 1000);
            }
        })
        .catch(err => {
            console.log("Nearest stores status poll failed:", err);
            nearestPollTimer = setTimeout(pollNearestProgress, 2000);
        });
}

function showNearestModalForActiveJob(jobId) {
    if (!jobId || document.getElementById("nearestProgressModalBackdrop")) return;

    nearestJobId = jobId;

    const modal = document.createElement("div");
    modal.className = "product-modal-backdrop";
    modal.id = "nearestProgressModalBackdrop";
    modal.innerHTML = `
        <div class="product-choice-card" role="dialog" aria-modal="true">
            <div class="product-choice-header">
                <div class="product-choice-title-row">
                    <div style="width:52px;"></div>
                    <h2>Finding Nearest Stores</h2>
                    <button type="button" class="product-close-btn" onclick="hideNearestProgressModal()">Hide</button>
                </div>

                <p class="product-choice-subtitle">
                    Updating home store locations from your address. This popup syncs across your phone and computer.
                </p>
            </div>

            <div class="bulk-progress-status">
                <div id="nearestSpinner" class="bulk-spinner"></div>
                <div class="bulk-active-line">
                    Status:
                    <span id="nearestStatusText" class="bulk-active-ingredient">Starting...</span>
                </div>
                <div id="nearestSummary" class="product-choice-subtitle">Preparing nearest store lookup...</div>
                <div class="bulk-progress-bar-wrap">
                    <div id="nearestProgressBar" class="bulk-progress-bar"></div>
                </div>
            </div>

            <div id="nearestLogList" class="bulk-preview-list"></div>

            <div class="bulk-modal-actions">
                <button type="button" class="bulk-secondary-btn" onclick="hideNearestProgressModal()">Hide</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const url = new URL(window.location.href);
    url.searchParams.set("nearest_job", jobId);
    window.history.replaceState({}, "", url.toString());

    pollNearestProgress();
}

function pollForActiveNearestJob() {
    if (activeNearestPollTimer) {
        clearTimeout(activeNearestPollTimer);
        activeNearestPollTimer = null;
    }

    fetch("/active_nearest_stores_status")
        .then(response => response.json())
        .then(data => {
            const activeJobId = data.ok ? (data.nearest_job_id || "") : "";
            const modal = document.getElementById("nearestProgressModalBackdrop");

            if (activeJobId) {
                if (!modal || nearestJobId !== activeJobId) {
                    showNearestModalForActiveJob(activeJobId);
                } else if (!nearestPollTimer) {
                    pollNearestProgress();
                }
            } else {
                if (modal && nearestJobId) {
                    modal.remove();

                    const url = new URL(window.location.href);
                    url.searchParams.delete("nearest_job");
                    window.history.replaceState({}, "", url.toString());
                }

                nearestJobId = "";
            }

            activeNearestPollTimer = setTimeout(pollForActiveNearestJob, 2000);
        })
        .catch(err => {
            console.log("Active nearest stores poll failed:", err);
            activeNearestPollTimer = setTimeout(pollForActiveNearestJob, 3000);
        });
}

function setupCardCollapseToggles() {
    document.querySelectorAll(".card-collapse-toggle").forEach(button => {
        const key = button.dataset.collapseKey || "";
        const content = document.querySelector('[data-collapse-content="' + key + '"]');
        const icon = button.querySelector(".card-collapse-icon");

        if (!content || !icon) return;

        const storageKey = "card_collapsed|" + key;
        const savedState = localStorage.getItem(storageKey);

        if (savedState === "open") {
            content.classList.remove("collapsed");
            icon.textContent = "Hide ▴";
        } else {
            content.classList.add("collapsed");
            icon.textContent = "Show ▾";
        }

        button.addEventListener("click", function () {
            const isCollapsed = content.classList.contains("collapsed");

            if (isCollapsed) {
                content.classList.remove("collapsed");
                icon.textContent = "Hide ▴";
                localStorage.setItem(storageKey, "open");
            } else {
                content.classList.add("collapsed");
                icon.textContent = "Show ▾";
                localStorage.setItem(storageKey, "closed");
            }
        });
    });
}


function toggleStoreEdit(storeKey) {
    const form = document.getElementById("edit-store-" + storeKey);

    if (!form) return;

    form.classList.toggle("open");
}

function toggleStoreChoices(storeKey) {
    const list = document.getElementById("store-choices-" + storeKey);

    if (!list) return;

    list.classList.toggle("open");
}

function toggleStoreChoiceEdit(storeKey, candidateIndex) {
    const form = document.getElementById("store-choice-edit-" + storeKey + "-" + candidateIndex);

    if (!form) return;

    form.classList.toggle("open");
}

function showInstantGrabLoading() {
    if (document.getElementById("bulkProgressModalBackdrop")) return true;

    const modal = document.createElement("div");
    modal.className = "product-modal-backdrop";
    modal.id = "bulkProgressModalBackdrop";
    modal.innerHTML = `
        <div class="product-choice-card" role="dialog" aria-modal="true">
            <div class="product-choice-header">
                <div class="product-choice-title-row">
                    <div style="width:52px;"></div>
                    <h2>Grabbing Best Products</h2>
                    <button type="button" class="product-close-btn" disabled>Loading</button>
                </div>
                <p class="product-choice-subtitle">Preparing product search...</p>
            </div>

            <div class="bulk-progress-status">
                <div class="bulk-spinner"></div>
                <div class="bulk-active-line">
                    Active ingredient:
                    <span class="bulk-active-ingredient">Starting...</span>
                </div>
                <div class="product-choice-subtitle">Checking selected stores and products...</div>
                <div class="bulk-progress-bar-wrap">
                    <div class="bulk-progress-bar" style="width:12%;"></div>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    return true;
}

document.addEventListener("DOMContentLoaded", function () {
    setupCheckboxes();
    setupRecipeTaskCheckboxes();
    setupDetailToggles();
    setupNutritionToggles();
    setupCardCollapseToggles();
    restoreOpenStoreUrlsSetting();
    restoreShowItemButtonsSetting();
    restoreShowBestProductSetting();
    restoreHideCheckedItemsSetting();
    restoreCompactModeSetting();
    restoreView();
    setupCollapsibleHeaders();
    restoreScroll();

    document.addEventListener("keydown", function(event) {
        if (event.key === "Escape") {
            closeProductModal();
            closeBulkPreviewModal();
            hideExtractProgressModal();
            hideNearestProgressModal();
        }
    });

    if (bulkJobId) {
        pollBulkGrab();
    } else {
        pollForActiveBulkJob();
    }

    if (extractJobId) {
        pollExtractProgress();
    } else {
        pollForActiveExtractJob();
    }

    if (nearestJobId) {
        pollNearestProgress();
    }

    pollForActiveNearestJob();
});
</script>

</body>
</html>
"""


def ensure_list():
    if not SHOPPING_LIST_FILE.exists():
        SHOPPING_LIST_FILE.write_text(
            "\n".join(DEFAULT_ITEMS),
            encoding="utf-8"
        )


def ensure_log_files():
    if not URL_HISTORY_FILE.exists():
        URL_HISTORY_FILE.write_text("", encoding="utf-8")

    if not CURRENT_URL_LOG_FILE.exists():
        CURRENT_URL_LOG_FILE.write_text("", encoding="utf-8")


def load_recipe_details():
    if not RECIPE_DETAILS_FILE.exists():
        RECIPE_DETAILS_FILE.write_text("{}", encoding="utf-8")
        PRODUCT_CHOICES_FILE.write_text("{}", encoding="utf-8")
        ACTIVE_BULK_JOB_FILE.write_text("", encoding="utf-8")
        ACTIVE_EXTRACT_JOB_FILE.write_text("", encoding="utf-8")
        return {}

    try:
        return json.loads(RECIPE_DETAILS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_recipe_details(details):
    with file_lock:
        RECIPE_DETAILS_FILE.write_text(
            json.dumps(details, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def load_item_state():
    if not ITEM_STATE_FILE.exists():
        ITEM_STATE_FILE.write_text("{}", encoding="utf-8")
        RECIPE_DETAILS_FILE.write_text("{}", encoding="utf-8")
        PRODUCT_CHOICES_FILE.write_text("{}", encoding="utf-8")
        return {}

    try:
        return json.loads(ITEM_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_item_state(state):
    with file_lock:
        ITEM_STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def load_store_location_results():
    if not STORE_RESULTS_FILE.exists():
        return {}

    try:
        data = json.loads(STORE_RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    stores = data.get("stores", {}) if isinstance(data, dict) else {}

    if not isinstance(stores, dict):
        return {}

    cleaned = {}

    for raw_key, value in stores.items():
        key = normalize_store_key(raw_key)

        if key and isinstance(value, dict):
            cleaned[key] = value

    return cleaned


def load_store_results_payload():
    if not STORE_RESULTS_FILE.exists():
        return {"home_address": {}, "stores": {}}

    try:
        data = json.loads(STORE_RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"home_address": {}, "stores": {}}

    if not isinstance(data, dict):
        data = {"home_address": {}, "stores": {}}

    if not isinstance(data.get("stores"), dict):
        data["stores"] = {}

    if not isinstance(data.get("home_address"), dict):
        data["home_address"] = {}

    return data


def save_store_results_payload(data):
    if not isinstance(data, dict):
        data = {"home_address": {}, "stores": {}}

    if not isinstance(data.get("stores"), dict):
        data["stores"] = {}

    STORE_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with file_lock:
        STORE_RESULTS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def clean_maps_prefix(value):
    return str(value or "").replace("", "").replace("", "").strip()


def build_full_home_address(home):
    street = str(home.get("street") or "").strip()
    apartment = str(home.get("apartment") or "").strip()
    city = str(home.get("city") or "").strip()
    state = str(home.get("state") or "").strip()
    zip_code = str(home.get("zip") or "").strip()

    street_line = " ".join(part for part in [street, apartment] if part).strip()
    city_line = ", ".join(part for part in [city, state] if part).strip()

    if city_line and zip_code:
        city_line = f"{city_line} {zip_code}"

    return ", ".join(part for part in [street_line, city_line] if part).strip()


def default_home_address():
    return {
        "street": "5905 Arlo Drive",
        "apartment": "Apt 2213",
        "city": "Indianapolis",
        "state": "IN",
        "zip": "46237",
        "full_address": "5905 Arlo Drive Apt 2213, Indianapolis, IN 46237",
        "lat": None,
        "lng": None,
    }


def load_home_address_form():
    payload = load_store_results_payload()
    home = payload.get("home_address", {})

    if not isinstance(home, dict):
        home = {}

    result = default_home_address()
    result.update({key: home.get(key, result.get(key)) for key in result})
    result["full_address"] = home.get("full_address") or build_full_home_address(result)
    return result


def save_home_address_to_results(form_data):
    payload = load_store_results_payload()
    old_home = payload.get("home_address", {}) if isinstance(payload.get("home_address"), dict) else {}

    home = {
        "street": str(form_data.get("address_street") or "").strip(),
        "apartment": str(form_data.get("address_apartment") or "").strip(),
        "city": str(form_data.get("address_city") or "").strip(),
        "state": str(form_data.get("address_state") or "").strip(),
        "zip": str(form_data.get("address_zip") or "").strip(),
        "lat": old_home.get("lat"),
        "lng": old_home.get("lng"),
    }

    home["full_address"] = build_full_home_address(home)
    payload["home_address"] = home
    save_store_results_payload(payload)
    return home


def update_find_nearest_stores_address_constants(home):
    if not FIND_NEAREST_STORES_FILE.exists():
        return False, f"Missing file: {FIND_NEAREST_STORES_FILE}"

    text = FIND_NEAREST_STORES_FILE.read_text(encoding="utf-8")

    replacements = {
        "ADDRESS_STREET": home.get("street", ""),
        "ADDRESS_APARTMENT": home.get("apartment", ""),
        "ADDRESS_CITY": home.get("city", ""),
        "ADDRESS_STATE": home.get("state", ""),
        "ADDRESS_ZIP": home.get("zip", ""),
    }

    for name, value in replacements.items():
        value_json = json.dumps(str(value or ""))
        text = re.sub(rf'^{name}\s*=\s*["\'].+?["\']', f'{name} = {value_json}', text, flags=re.MULTILINE)

    FIND_NEAREST_STORES_FILE.write_text(text, encoding="utf-8")
    return True, "find_nearest_stores.py address constants updated"


def find_nearest_subprocess_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_find_nearest_stores_script():
    if not FIND_NEAREST_STORES_FILE.exists():
        return False, f"Missing file: {FIND_NEAREST_STORES_FILE}"

    completed = subprocess.run(
        ["py", "-3.11", "-X", "utf8", str(FIND_NEAREST_STORES_FILE)],
        cwd=str(PROJECT_ROOT),
        check=False,
        env=find_nearest_subprocess_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if completed.returncode == 0:
        return True, "Nearest stores updated"

    return False, f"find_nearest_stores.py exited with code {completed.returncode}"

def sort_stores_alpha(stores):
    if not isinstance(stores, dict):
        return {}

    return dict(
        sorted(
            stores.items(),
            key=lambda item: str(item[1].get("label", item[0])).strip().lower()
        )
    )


def save_all_stores(stores):
    cleaned = {}

    if not isinstance(stores, dict):
        stores = {}

    for raw_key, raw_store in stores.items():
        key = normalize_store_key(raw_key)

        if not key or not isinstance(raw_store, dict):
            continue

        label = str(raw_store.get("label") or key.title()).strip()
        url = str(raw_store.get("url") or "").strip()
        url_store_selector = str(raw_store.get("urlStoreSelector") or "").strip()

        if not label or not url:
            continue

        cleaned[key] = {
            "label": label,
            "url": url,
            "urlStoreSelector": url_store_selector
        }

    cleaned = sort_stores_alpha(cleaned)

    with file_lock:
        STORES_FILE.write_text(
            json.dumps(cleaned, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    return cleaned


def load_all_stores():
    if not STORES_FILE.exists():
        return save_all_stores(DEFAULT_STORES.copy())

    try:
        data = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return save_all_stores(DEFAULT_STORES.copy())

    if not isinstance(data, dict) or not data:
        return save_all_stores(DEFAULT_STORES.copy())

    cleaned = {}

    for raw_key, raw_store in data.items():
        key = normalize_store_key(raw_key)

        if not key or not isinstance(raw_store, dict):
            continue

        label = str(raw_store.get("label") or key.title()).strip()
        url = str(raw_store.get("url") or "").strip()
        url_store_selector = str(raw_store.get("urlStoreSelector") or "").strip()

        if not label or not url:
            continue

        cleaned[key] = {
            "label": label,
            "url": url,
            "urlStoreSelector": url_store_selector
        }

    if not cleaned:
        cleaned = DEFAULT_STORES.copy()

    return sort_stores_alpha(cleaned)


def normalize_store_key(text):
    text = str(text or "").strip().lower()
    allowed = []

    for char in text:
        if char.isalnum():
            allowed.append(char)
        elif char in [" ", "-", "_"]:
            allowed.append("_")

    key = "".join(allowed)

    while "__" in key:
        key = key.replace("__", "_")

    return key.strip("_")


def guess_store_search_url(homepage_url):
    homepage_url = str(homepage_url or "").strip()

    if not homepage_url:
        return ""

    if not homepage_url.startswith(("http://", "https://")):
        homepage_url = "https://" + homepage_url

    homepage_url = homepage_url.rstrip("/")

    common_patterns = [
        "/search?q=",
        "/search?query=",
        "/search?keyword=",
        "/s?k=",
        "/s?searchTerm=",
        "/catalogsearch/result/?q=",
        "/shopping/search.html?text=",
    ]

    return homepage_url + common_patterns[0]


def default_enabled_stores():
    stores = load_all_stores()
    defaults = []

    for store_key in DEFAULT_ENABLED_STORES:
        if store_key in stores and store_key not in defaults:
            defaults.append(store_key)

    if defaults:
        return defaults

    return list(stores.keys())[:2]


def load_store_settings():
    stores = load_all_stores()
    defaults = default_enabled_stores()

    # First run only: seed the enabled store list from defaults.
    # After the settings file exists, an empty enabled_stores list is valid
    # and must stay empty instead of falling back to defaults.
    if not STORE_SETTINGS_FILE.exists():
        save_store_settings(defaults)
        return defaults.copy()

    try:
        data = json.loads(STORE_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return defaults.copy()

    enabled = data.get("enabled_stores", [])

    if not isinstance(enabled, list):
        enabled = []

    cleaned = []

    for store_key in enabled:
        store_key = normalize_store_key(store_key)

        if store_key in stores and store_key not in cleaned:
            cleaned.append(store_key)

    return cleaned


def save_store_settings(enabled_stores):
    stores = load_all_stores()
    cleaned = []

    for store_key in enabled_stores:
        store_key = normalize_store_key(store_key)

        if store_key in stores and store_key not in cleaned:
            cleaned.append(store_key)

    with file_lock:
        STORE_SETTINGS_FILE.write_text(
            json.dumps({"enabled_stores": cleaned}, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    return cleaned


def store_urls_for_enabled_stores(enabled_stores):
    stores = load_all_stores()

    return {
        store_key: stores[store_key]["url"]
        for store_key in enabled_stores
        if store_key in stores
    }


def load_product_choices():
    if not PRODUCT_CHOICES_FILE.exists():
        return {}

    try:
        data = json.loads(PRODUCT_CHOICES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_product_choices(data):
    with file_lock:
        PRODUCT_CHOICES_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def flatten_product_results(scrape_result):
    products = []

    if isinstance(scrape_result, dict):
        if isinstance(scrape_result.get("results"), list):
            products.extend(scrape_result.get("results") or [])

        for store_result in scrape_result.get("stores", []) or []:
            if isinstance(store_result, dict) and isinstance(store_result.get("results"), list):
                products.extend(store_result.get("results") or [])

    seen = set()
    unique = []

    for product in products:
        if not isinstance(product, dict):
            continue

        key = product.get("product_url") or normalize(product.get("product_name", ""))

        if not key or key in seen:
            continue

        seen.add(key)
        unique.append(product)

    return sorted(
        unique,
        key=lambda product: product.get("score", 0) or 0,
        reverse=True
    )


def get_product_choices_for_item(item_key):
    choices = load_product_choices()
    entry = choices.get(item_key, {})

    if not isinstance(entry, dict):
        return None, []

    item = entry.get("item")
    products = entry.get("products", [])

    if not isinstance(products, list):
        products = []

    return item, products


def get_selected_product_for_item_key(item_key, item_sources=None):
    item_sources = item_sources or load_item_sources()
    source_list = item_sources.get(item_key, [])

    if isinstance(source_list, str):
        source_list = [{"url": source_list}]

    if isinstance(source_list, dict):
        source_list = [source_list]

    if not isinstance(source_list, list):
        source_list = []

    selected_product = None

    for source in source_list:
        if not isinstance(source, dict):
            continue

        if source.get("source_type") == "product" or source.get("product_url"):
            selected_product = {
                "product_name": source.get("product_name"),
                "product_url": source.get("product_url"),
                "product_location": source.get("product_location"),
                "product_cost": source.get("product_cost"),
                "store": source.get("store"),
                "is_organic": source.get("is_organic"),
                "score": source.get("score"),
            }

    return selected_product


def append_selected_product_to_item_sources(item, product):
    item_key = normalize(item)
    sources = load_item_sources()

    if item_key not in sources:
        sources[item_key] = []

    if isinstance(sources[item_key], str):
        sources[item_key] = [{"url": sources[item_key]}]

    if isinstance(sources[item_key], dict):
        sources[item_key] = [sources[item_key]]

    if not isinstance(sources[item_key], list):
        sources[item_key] = []

    product_url = product.get("product_url")
    product_store = product.get("store")
    product_location = product.get("product_location")

    cleaned_sources = []

    for source in sources[item_key]:
        if not isinstance(source, dict):
            cleaned_sources.append(source)
            continue

        is_product = source.get("source_type") == "product" or source.get("product_url")

        if is_product:
            same_url = product_url and source.get("product_url") == product_url
            same_store = (
                (product_store and source.get("store") == product_store)
                or (product_location and source.get("product_location") == product_location)
            )

            if same_url or same_store:
                continue

        cleaned_sources.append(source)

    cleaned_sources.append({
        "source_type": "product",
        "url": None,
        "product_name": product.get("product_name"),
        "product_url": product_url,
        "product_location": product_location,
        "product_cost": product.get("product_cost"),
        "store": product_store,
        "is_organic": product.get("is_organic"),
        "score": product.get("score"),
    })

    sources[item_key] = cleaned_sources
    save_item_sources(sources)

    if product_store:
        state = load_item_state()

        if item_key not in state or not isinstance(state[item_key], dict):
            state[item_key] = {}

        state[item_key]["store"] = product_store
        save_item_state(state)




def get_selected_store_for_item(item, item_state=None):
    item_state = item_state or load_item_state()
    item_key = normalize(item)
    state = item_state.get(item_key, {})

    if not isinstance(state, dict):
        return None

    store = state.get("store")

    stores = load_all_stores()

    if store in stores:
        return store

    return None


def item_has_selected_product(item, item_sources=None):
    item_sources = item_sources or load_item_sources()
    sources = get_source_list_for_item(item, item_sources)

    for source in sources:
        if isinstance(source, dict) and (source.get("source_type") == "product" or source.get("product_url")):
            return True

    return False


def grab_best_product_for_item(item, enabled_stores):
    if scrape_store_product is None:
        return None

    selected_store = get_selected_store_for_item(item)

    # If no store is selected, do nothing for this ingredient.
    if not selected_store:
        return None

    scrape_result = scrape_store_product(
        store=selected_store,
        item=item,
        headless=True,
        wait_seconds=5,
        max_results=5
    )

    products = flatten_product_results(scrape_result)

    if not products:
        return None

    best_product = products[0]
    append_selected_product_to_item_sources(item, best_product)

    choices = load_product_choices()
    item_key = normalize(item)
    choices[item_key] = {
        "item": item,
        "products": products,
        "selected_product": best_product,
        "selected_product_url": best_product.get("product_url"),
        "raw_result": scrape_result
    }
    save_product_choices(choices)

    return best_product


def grab_product_candidates_for_item(item, enabled_stores):
    """Search products using the selected store URL for this ingredient."""
    selected_store = get_selected_store_for_item(item)

    if not selected_store:
        return None, [], None

    all_stores = load_all_stores()

    if selected_store not in all_stores:
        return None, [], {
            "ok": False,
            "query": item,
            "error": f"Selected store is no longer available: {selected_store}",
        }

    scrape_result = None
    products = []
    search_url = build_scraper_url_for_item(item, selected_store)

    # Preferred path: feed store_product_scraper.py a list of URLs.
    # This keeps app.py responsible for building the URL list and lets the scraper open them.
    if run_scraper is not None and search_url:
        try:
            scrape_result = run_scraper([search_url])
            products = flatten_products_from_run_scraper(scrape_result, selected_store)
        except TypeError:
            # Some versions use keyword arguments. Try a second common shape.
            scrape_result = run_scraper(urls=[search_url])
            products = flatten_products_from_run_scraper(scrape_result, selected_store)

    # Fallback for older scraper versions that expose item/store helpers instead.
    if not products:
        if scrape_store_searches_parallel is not None:
            scrape_result = scrape_store_searches_parallel(
                item=item,
                stores=[selected_store],
                headless=False,
                wait_seconds=7,
                max_workers=1,
                max_results=8,
            )
        elif scrape_all_stores is not None:
            scrape_result = scrape_all_stores(
                item=item,
                stores=[selected_store],
                headless=False,
                wait_seconds=7,
                max_results=8,
            )
        else:
            return None, [], None

        products = flatten_product_results(scrape_result)

    if not products:
        return None, [], scrape_result

    best_product = products[0]
    best_product = normalize_scraper_product(best_product, selected_store) or best_product
    append_selected_product_to_item_sources(item, best_product)

    choices = load_product_choices()
    item_key = normalize(item)
    choices[item_key] = {
        "item": item,
        "products": products,
        "selected_product": best_product,
        "selected_product_url": best_product.get("product_url"),
        "raw_result": scrape_result,
        "selected_store": selected_store,
        "search_url": search_url,
    }
    save_product_choices(choices)

    return best_product, products, scrape_result

def clear_selected_product_sources():
    sources = load_item_sources()
    changed = 0

    for item_key, source_list in list(sources.items()):
        if isinstance(source_list, str):
            source_list = [{"url": source_list}]

        if isinstance(source_list, dict):
            source_list = [source_list]

        if not isinstance(source_list, list):
            continue

        cleaned = []

        for source in source_list:
            if isinstance(source, dict) and (source.get("source_type") == "product" or source.get("product_url")):
                changed += 1
                continue

            cleaned.append(source)

        sources[item_key] = cleaned

    save_item_sources(sources)
    save_product_choices({})

    return changed


def clear_selected_product_for_item(item):
    item_key = normalize(item)
    sources = load_item_sources()
    changed = 0

    source_list = sources.get(item_key, [])

    if isinstance(source_list, str):
        source_list = [{"url": source_list}]

    if isinstance(source_list, dict):
        source_list = [source_list]

    if not isinstance(source_list, list):
        source_list = []

    cleaned = []

    for source in source_list:
        if isinstance(source, dict) and (source.get("source_type") == "product" or source.get("product_url")):
            changed += 1
            continue

        cleaned.append(source)

    sources[item_key] = cleaned
    save_item_sources(sources)

    choices = load_product_choices()

    if item_key in choices:
        if isinstance(choices[item_key], dict):
            choices[item_key].pop("selected_product", None)
        save_product_choices(choices)

    return changed


def get_grabbable_product_items(skip_existing=True):
    raw_text, items = load_items()
    item_sources = load_item_sources()
    item_state = load_item_state()
    actual_items = []

    for item in items:
        if not item.strip() or is_section_header(item):
            continue

        selected_store = get_selected_store_for_item(item, item_state)

        # Only grab products for ingredients that already have a selected store.
        if not selected_store:
            continue

        if skip_existing and item_has_selected_product(item, item_sources):
            continue

        actual_items.append(item)

    return actual_items



def build_store_search_details(item, selected_store=None):
    """Return a clickable manual search URL and display label for a skipped/failed product lookup."""
    selected_store = selected_store or get_selected_store_for_item(item)

    if not selected_store:
        return None, None

    stores = load_all_stores()
    store_info = stores.get(selected_store, {})
    base_url = store_info.get("url", "")
    store_label = store_info.get("label", selected_store.title())

    if not base_url:
        return None, f"{store_label} → {item}"

    return base_url + requests.utils.quote(str(item)), f"{store_label} → {item}"


def build_scraper_url_for_item(item, selected_store=None):
    """Build the exact store search URL passed into store_product_scraper.run_scraper()."""
    search_url, _label = build_store_search_details(item, selected_store)
    return search_url


def build_scraper_urls_for_items(items):
    """Return only URLs for ingredients that have a selected store and no saved best product."""
    urls = []
    url_to_item = {}

    for item in items:
        selected_store = get_selected_store_for_item(item)
        if not selected_store:
            continue

        url = build_scraper_url_for_item(item, selected_store)
        print(url)
        if not url:
            continue

        urls.append(url)
        url_to_item[url] = item

    print(urls)
    return urls, url_to_item


def normalize_scraper_product(product, selected_store=None):
    if not isinstance(product, dict):
        return None

    cleaned = dict(product)

    # Accept common field names returned by scraper variants.
    if not cleaned.get("product_name"):
        cleaned["product_name"] = cleaned.get("name") or cleaned.get("title")

    if not cleaned.get("product_url"):
        cleaned["product_url"] = cleaned.get("url") or cleaned.get("href") or cleaned.get("link")

    if not cleaned.get("product_cost"):
        cleaned["product_cost"] = cleaned.get("price") or cleaned.get("cost")

    if selected_store and not cleaned.get("store"):
        cleaned["store"] = selected_store

    if selected_store and not cleaned.get("product_location"):
        cleaned["product_location"] = load_all_stores().get(selected_store, {}).get("label", selected_store.title())

    if cleaned.get("product_name") or cleaned.get("product_url"):
        return cleaned

    return None


def flatten_products_from_run_scraper(scrape_result, selected_store=None):
    """Flatten several possible run_scraper return shapes into product dictionaries."""
    raw_products = []

    if isinstance(scrape_result, list):
        for entry in scrape_result:
            if isinstance(entry, dict) and isinstance(entry.get("results"), list):
                raw_products.extend(entry.get("results") or [])
            elif isinstance(entry, dict) and isinstance(entry.get("products"), list):
                raw_products.extend(entry.get("products") or [])
            elif isinstance(entry, dict):
                raw_products.append(entry)
    elif isinstance(scrape_result, dict):
        for key in ["results", "products", "items"]:
            if isinstance(scrape_result.get(key), list):
                raw_products.extend(scrape_result.get(key) or [])

        for key in ["stores", "urls", "data"]:
            if isinstance(scrape_result.get(key), list):
                for entry in scrape_result.get(key) or []:
                    if isinstance(entry, dict) and isinstance(entry.get("results"), list):
                        raw_products.extend(entry.get("results") or [])
                    elif isinstance(entry, dict) and isinstance(entry.get("products"), list):
                        raw_products.extend(entry.get("products") or [])

    products = []
    seen = set()

    for raw_product in raw_products:
        product = normalize_scraper_product(raw_product, selected_store)
        if not product:
            continue

        identity = product.get("product_url") or normalize(product.get("product_name", ""))
        if not identity or identity in seen:
            continue

        seen.add(identity)
        products.append(product)

    return sorted(products, key=lambda product: product.get("score", 0) or 0, reverse=True)


def save_active_bulk_job(job_id):
    try:
        with file_lock:
            ACTIVE_BULK_JOB_FILE.write_text(job_id or "", encoding="utf-8")
    except Exception as e:
        print(f"Could not save active bulk job: {e}")


def clear_active_bulk_job(job_id=None):
    try:
        current = ""

        if ACTIVE_BULK_JOB_FILE.exists():
            current = ACTIVE_BULK_JOB_FILE.read_text(encoding="utf-8").strip()

        if job_id is None or not current or current == job_id:
            save_active_bulk_job("")
    except Exception as e:
        print(f"Could not clear active bulk job: {e}")


def load_active_bulk_job():
    if not ACTIVE_BULK_JOB_FILE.exists():
        return ""

    try:
        job_id = ACTIVE_BULK_JOB_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

    if not job_id:
        return ""

    job = get_bulk_product_job(job_id)

    if job and job.get("status") in ["queued", "running", "cancel_requested", "review"]:
        return job_id

    clear_active_bulk_job(job_id)
    return ""


def save_active_extract_job(job_id):
    try:
        with file_lock:
            ACTIVE_EXTRACT_JOB_FILE.write_text(job_id or "", encoding="utf-8")
    except Exception as e:
        print(f"Could not save active extract job: {e}")


def clear_active_extract_job(job_id=None):
    try:
        current = ""

        if ACTIVE_EXTRACT_JOB_FILE.exists():
            current = ACTIVE_EXTRACT_JOB_FILE.read_text(encoding="utf-8").strip()

        if job_id is None or not current or current == job_id:
            save_active_extract_job("")
    except Exception as e:
        print(f"Could not clear active extract job: {e}")


def load_active_extract_job():
    if not ACTIVE_EXTRACT_JOB_FILE.exists():
        return ""

    try:
        job_id = ACTIVE_EXTRACT_JOB_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

    if not job_id:
        return ""

    job = get_extract_job(job_id)

    if job and not job.get("done") and job.get("status") in ["queued", "running"]:
        return job_id

    clear_active_extract_job(job_id)
    return ""




def save_active_nearest_stores_job(job_id):
    try:
        with file_lock:
            ACTIVE_NEAREST_STORES_JOB_FILE.write_text(job_id or "", encoding="utf-8")
    except Exception as e:
        print(f"Could not save active nearest stores job: {e}")


def clear_active_nearest_stores_job(job_id=None):
    try:
        current = ""

        if ACTIVE_NEAREST_STORES_JOB_FILE.exists():
            current = ACTIVE_NEAREST_STORES_JOB_FILE.read_text(encoding="utf-8").strip()

        if job_id is None or not current or current == job_id:
            save_active_nearest_stores_job("")
    except Exception as e:
        print(f"Could not clear active nearest stores job: {e}")


def load_active_nearest_stores_job():
    if not ACTIVE_NEAREST_STORES_JOB_FILE.exists():
        return ""

    try:
        job_id = ACTIVE_NEAREST_STORES_JOB_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

    if not job_id:
        return ""

    job = get_nearest_stores_job(job_id)

    if job and not job.get("done") and job.get("status") in ["queued", "running"]:
        return job_id

    clear_active_nearest_stores_job(job_id)
    return ""


def create_nearest_stores_job(home):
    job_id = uuid.uuid4().hex
    full_address = build_full_home_address(home)

    with nearest_stores_lock:
        nearest_stores_jobs[job_id] = {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "message": "Queued",
            "summary": f"Queued nearest-store update for {full_address}.",
            "progress": 5,
            "done": False,
            "success": False,
            "active_store": "",
            "error": None,
            "logs": [],
        }

    return job_id


def get_nearest_stores_job(job_id):
    with nearest_stores_lock:
        job = nearest_stores_jobs.get(job_id)

        if not job:
            return None

        return json.loads(json.dumps(job))


def update_nearest_stores_job(job_id, **updates):
    if not job_id:
        return None

    with nearest_stores_lock:
        job = nearest_stores_jobs.get(job_id)

        if not job:
            return None

        extra_log = updates.pop("log", None)
        job.update(updates)

        if extra_log:
            logs = job.setdefault("logs", [])
            logs.append(str(extra_log))
            job["logs"] = logs[-80:]

        return json.loads(json.dumps(job))


def run_find_nearest_stores_job(job_id, home):
    try:
        update_nearest_stores_job(
            job_id,
            status="running",
            message="Saving address...",
            summary="Saving home address and updating find_nearest_stores.py.",
            progress=8,
            log="Saving home address.",
        )

        ok, message = update_find_nearest_stores_address_constants(home)

        update_nearest_stores_job(
            job_id,
            message=message,
            summary=message,
            progress=12,
            log=message,
        )

        if not ok:
            update_nearest_stores_job(
                job_id,
                status="error",
                message="Could not update find_nearest_stores.py.",
                summary=message,
                progress=100,
                done=True,
                success=False,
                error=message,
                log=message,
            )
            clear_active_nearest_stores_job(job_id)
            return

        if not FIND_NEAREST_STORES_FILE.exists():
            error = f"Missing file: {FIND_NEAREST_STORES_FILE}"
            update_nearest_stores_job(
                job_id,
                status="error",
                message="find_nearest_stores.py not found.",
                summary=error,
                progress=100,
                done=True,
                success=False,
                error=error,
                log=error,
            )
            clear_active_nearest_stores_job(job_id)
            return

        update_nearest_stores_job(
            job_id,
            message="Running find_nearest_stores.py...",
            summary="Chrome may open while Google Maps finds the closest stores.",
            progress=18,
            log="Starting find_nearest_stores.py.",
        )

        process = subprocess.Popen(
            ["py", "-3.11", "-X", "utf8", str(FIND_NEAREST_STORES_FILE)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=find_nearest_subprocess_env(),
        )

        loaded_stores = []
        completed_markers = 0

        if process.stdout:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                lower_line = line.lower()

                # This undetected_chromedriver warning is noise. Do not show it
                # as the active status and do not add it to the checkbox list.
                if "could not detect version_main" in lower_line:
                    continue

                progress = None
                active_store = None
                store_log_line = None
                message_line = line

                if "loaded stores:" in lower_line:
                    progress = 20
                    message_line = "Loaded store list."
                elif "getting home coordinates" in lower_line:
                    progress = 25
                    message_line = "Getting home coordinates..."
                elif "home coordinates" in lower_line:
                    progress = 32
                    message_line = "Home coordinates found."
                elif "processing" in lower_line:
                    active_store = line.split("Processing", 1)[-1].strip() if "Processing" in line else ""
                    active_store = active_store.strip(" .:-")
                    if active_store and active_store not in loaded_stores:
                        loaded_stores.append(active_store)
                    progress = min(85, 35 + (len(loaded_stores) * 8))
                    message_line = f"Reviewing {active_store}" if active_store else line
                    store_log_line = message_line
                elif "done" in lower_line or "saved results" in lower_line:
                    progress = 95
                    message_line = "Saving nearest store results..."
                else:
                    progress = min(90, 35 + (len(loaded_stores) * 8)) if loaded_stores else 25
                    message_line = (
                        f"Finding nearest stores... {len(loaded_stores)} store(s) started."
                        if loaded_stores
                        else "Finding nearest stores..."
                    )

                update_nearest_stores_job(
                    job_id,
                    status="running",
                    message=message_line,
                    summary=f"Finding nearest stores... {len(loaded_stores)} store(s) started.",
                    progress=progress,
                    active_store=active_store or loaded_stores[-1] if loaded_stores else "",
                    log=store_log_line,
                )

        return_code = process.wait()

        if return_code == 0:
            update_nearest_stores_job(
                job_id,
                status="done",
                message="Nearest stores updated.",
                summary="Nearest stores updated and saved to shopping_stores_Results.json.",
                progress=100,
                done=True,
                success=True,
                error=None,
                log="Nearest stores update complete.",
            )
            send_phone_message("Nearest stores updated")
        else:
            error = f"find_nearest_stores.py exited with code {return_code}"
            update_nearest_stores_job(
                job_id,
                status="error",
                message="Nearest store update failed.",
                summary=error,
                progress=100,
                done=True,
                success=False,
                error=error,
                log=error,
            )
            send_phone_message(error)

    except Exception as e:
        traceback.print_exc()
        update_nearest_stores_job(
            job_id,
            status="error",
            message="Nearest store update failed.",
            summary=str(e),
            progress=100,
            done=True,
            success=False,
            error=str(e),
            log=f"Error: {e}",
        )
        send_phone_message(f"Nearest store update failed: {e}")
    finally:
        # Leave the finished job available briefly so both devices can render completion.
        clear_active_nearest_stores_job(job_id)

def create_bulk_product_job(items):
    job_id = uuid.uuid4().hex
    stores = load_all_stores()

    job_items = []

    for item in items:
        selected_store = get_selected_store_for_item(item)
        selected_store_label = stores.get(selected_store, {}).get("label", "") if selected_store else ""
        search_url, search_label = build_store_search_details(item, selected_store)

        job_items.append({
            "item": item,
            "status": "pending",
            "product_name": None,
            "product_cost": None,
            "selected_product_url": None,
            "selected_product": None,
            "selected_store": selected_store,
            "selected_store_label": selected_store_label,
            "search_url": search_url,
            "search_label": search_label,
            "scraper_urls": [search_url] if search_url else [],
            "products": [],
            "skip_reason": None,
            "error": None,
        })

    job = {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "cancel_requested": False,
        "active_item": "Queued",
        "total": len(items),
        "completed": 0,
        "added": 0,
        "failed": 0,
        "skipped": 0,
        "scraper_urls": [entry["search_url"] for entry in job_items if entry.get("search_url")],
        "items": job_items,
    }

    with bulk_product_lock:
        bulk_product_jobs[job_id] = job

    return job_id


def get_bulk_product_job(job_id):
    with bulk_product_lock:
        job = bulk_product_jobs.get(job_id)

        if not job:
            return None

        return json.loads(json.dumps(job))


def update_bulk_product_job(job_id, updater):
    with bulk_product_lock:
        job = bulk_product_jobs.get(job_id)

        if not job:
            return None

        updater(job)
        return json.loads(json.dumps(job))


def run_bulk_product_job(job_id, enabled_stores=None):
    """Run Grab Best Products through store_product_scraper.py.

    app.py now only builds the URL list, stores job state, and exposes JSON status.
    The live popup wording/progress comes from store_product_scraper.run_scraper()
    through the progress_callback below.
    """

    def set_status(status, active_item=None):
        def updater(job):
            job["status"] = status

            if active_item is not None:
                job["active_item"] = active_item

        update_bulk_product_job(job_id, updater)

    def mark_job_error(message):
        def updater(job):
            job["status"] = "error"
            job["active_item"] = message
            job["failed"] = job.get("total", 0)
            job["completed"] = job.get("total", 0)
            job["error"] = message

            for entry in job.get("items", []):
                if entry.get("status") in ["pending", "running"]:
                    entry["status"] = "failed"
                    entry["error"] = message

        update_bulk_product_job(job_id, updater)
        clear_active_bulk_job(job_id)

    try:
        if run_scraper is None:
            mark_job_error("store_product_scraper.py could not be imported")
            return

        job_snapshot = get_bulk_product_job(job_id)

        if not job_snapshot:
            return

        items = [
            entry.get("item")
            for entry in job_snapshot.get("items", [])
            if entry.get("item")
        ]

        if not items:
            set_status("review", "No items selected")
            clear_active_bulk_job(job_id)
            return

        scraper_urls = []
        url_to_item = {}
        item_to_url = {}

        for item in items:
            selected_store = get_selected_store_for_item(item)
            search_url = build_scraper_url_for_item(item, selected_store)

            if search_url:
                scraper_urls.append(search_url)
                url_to_item[search_url] = item
                item_to_url[item] = search_url

        print("\n==============================")
        print("SCRAPER URLS BUILT BY app.py BEFORE SCRAPER CALL")
        for index, url in enumerate(scraper_urls, start=1):
            print(f"{index}. {url}")
        print("==============================\n")

        def mark_urls_ready(job):
            job["status"] = "running"
            job["active_item"] = "URL list ready"
            job["scraper_urls"] = scraper_urls

            for entry in job.get("items", []):
                item = entry.get("item")
                selected_store = get_selected_store_for_item(item)
                store_label = load_all_stores().get(selected_store, {}).get("label", "") if selected_store else ""
                search_url = item_to_url.get(item)

                entry["status"] = "running" if search_url else "skipped"
                entry["selected_store"] = selected_store
                entry["selected_store_label"] = store_label
                entry["search_url"] = search_url
                entry["search_label"] = f"{store_label} → {item}" if store_label and item else None
                entry["scraper_urls"] = [search_url] if search_url else []

                if not search_url:
                    entry["skip_reason"] = "No scraper URL was built. Select a store for this item."

        update_bulk_product_job(job_id, mark_urls_ready)

        if not scraper_urls:
            def mark_no_urls(job):
                job["status"] = "review"
                job["active_item"] = "No scraper URLs were built"
                job["completed"] = job.get("total", len(job.get("items", [])))
                job["skipped"] = len(job.get("items", []))

                for entry in job.get("items", []):
                    entry["status"] = "skipped"
                    entry["skip_reason"] = entry.get("skip_reason") or "No scraper URL was built. Select a store for this item."

            update_bulk_product_job(job_id, mark_no_urls)
            clear_active_bulk_job(job_id)
            return

        current_job = get_bulk_product_job(job_id) or {}

        if current_job.get("cancel_requested"):
            set_status("cancelled", "Cancelled before scraper started")
            clear_active_bulk_job(job_id)
            return

        def progress_callback(progress):
            if not isinstance(progress, dict):
                return

            active_url = progress.get("active_url")
            active_item = url_to_item.get(active_url) or progress.get("active_item") or progress.get("message") or "Working..."
            completed = int(progress.get("completed", 0) or 0)
            total = int(progress.get("total", len(scraper_urls)) or len(scraper_urls))
            message = progress.get("message") or "Working..."
            result = progress.get("result")

            def updater(job):
                if job.get("cancel_requested"):
                    job["status"] = "cancel_requested"
                    job["active_item"] = "Cancelling after current ingredient..."
                    return

                job["status"] = "running"
                job["active_item"] = active_item
                job["completed"] = min(completed, job.get("total", total))
                job["progress_message"] = message

                if isinstance(result, dict):
                    result_url = result.get("url") or result.get("search_url") or active_url
                    result_item = url_to_item.get(result_url) or active_item
                    selected_store = result.get("store") or get_selected_store_for_item(result_item)
                    products = flatten_products_from_run_scraper({"results": [result]}, selected_store)

                    if not products:
                        products = flatten_products_from_run_scraper(result, selected_store)

                    best_product = None
                    if isinstance(result.get("best_match"), dict):
                        best_product = normalize_scraper_product(result.get("best_match"), selected_store)
                    elif products:
                        best_product = products[0]

                    for entry in job.get("items", []):
                        if entry.get("item") != result_item:
                            continue

                        entry["status"] = "done" if best_product else "skipped"
                        entry["products"] = products
                        entry["selected_store"] = selected_store or entry.get("selected_store")
                        entry["selected_store_label"] = result.get("store_name") or entry.get("selected_store_label")
                        entry["search_url"] = result_url or entry.get("search_url")
                        entry["scraper_urls"] = [result_url] if result_url else entry.get("scraper_urls", [])

                        if best_product:
                            entry["product_name"] = best_product.get("product_name")
                            entry["product_cost"] = best_product.get("product_cost")
                            entry["selected_product_url"] = best_product.get("product_url")
                            entry["selected_product"] = best_product
                        else:
                            entry["skip_reason"] = result.get("error") or "No product match found."
                        break

            update_bulk_product_job(job_id, updater)

        result = run_scraper(
            scraper_urls,
            progress_callback=progress_callback,
            headless=False,
            wait_seconds=5.0,
            max_workers=4,
            max_results=10,
        )

        result_entries = []
        if isinstance(result, dict):
            result_entries = result.get("results") or []
        elif isinstance(result, list):
            result_entries = result

        result_items_by_name = {}

        for scrape_entry in result_entries:
            if not isinstance(scrape_entry, dict):
                continue

            result_url = scrape_entry.get("url") or scrape_entry.get("search_url")
            item = url_to_item.get(result_url) or scrape_entry.get("query")

            if not item:
                continue

            selected_store = scrape_entry.get("store") or get_selected_store_for_item(item)
            products = flatten_products_from_run_scraper(scrape_entry, selected_store)

            best_product = None
            if isinstance(scrape_entry.get("best_match"), dict):
                best_product = normalize_scraper_product(scrape_entry.get("best_match"), selected_store)
            elif products:
                best_product = products[0]

            result_items_by_name[item] = {
                "item": item,
                "status": "done" if best_product else "skipped",
                "product_name": best_product.get("product_name") if best_product else None,
                "product_cost": best_product.get("product_cost") if best_product else None,
                "selected_product_url": best_product.get("product_url") if best_product else None,
                "selected_product": best_product,
                "selected_store": selected_store,
                "selected_store_label": scrape_entry.get("store_name") or load_all_stores().get(selected_store, {}).get("label", selected_store or ""),
                "search_url": result_url or item_to_url.get(item),
                "search_label": None,
                "scraper_urls": [result_url or item_to_url.get(item)] if (result_url or item_to_url.get(item)) else [],
                "products": products,
                "skip_reason": None if best_product else (scrape_entry.get("error") or "No product match found."),
                "error": scrape_entry.get("error"),
            }

        def mark_finished(job):
            job["status"] = "review" if result.get("ok", False) else "error"
            job["active_item"] = "Review selected products" if result.get("ok", False) else f"Error: {result.get('error', 'Unknown error')}"
            job["completed"] = job.get("total", len(job.get("items", [])))
            job["scraper_urls"] = scraper_urls
            job["error"] = result.get("error") if isinstance(result, dict) else None

            added = 0
            skipped = 0
            failed = 0

            for entry in job.get("items", []):
                item = entry.get("item")
                result_entry = result_items_by_name.get(item)

                if result_entry:
                    if result_entry.get("selected_store_label") and not result_entry.get("search_label"):
                        result_entry["search_label"] = f"{result_entry.get('selected_store_label')} → {item}"

                    entry.update(result_entry)

                elif entry.get("status") == "running":
                    entry["status"] = "skipped"
                    entry["skip_reason"] = "No result returned for this item."

                if entry.get("status") == "done" and entry.get("selected_product"):
                    added += 1
                elif entry.get("status") == "failed":
                    failed += 1
                elif entry.get("status") == "skipped":
                    skipped += 1

            job["added"] = added
            job["skipped"] = skipped
            job["failed"] = failed

        update_bulk_product_job(job_id, mark_finished)

        final_job = get_bulk_product_job(job_id) or {}

        if result.get("ok", False):
            send_phone_message(
                f"Best product grab ready for review. Added {final_job.get('added', 0)}, skipped {final_job.get('skipped', 0)}, failed {final_job.get('failed', 0)}."
            )
        else:
            send_phone_message(f"Best product grab failed: {result.get('error', 'Unknown error')}")

    except Exception as e:
        traceback.print_exc()

        def mark_error(job):
            job["status"] = "error"
            job["active_item"] = f"Error: {e}"
            job["error"] = str(e)
            job["failed"] = job.get("total", 0)
            job["completed"] = job.get("total", 0)

            for entry in job.get("items", []):
                if entry.get("status") in ["pending", "running"]:
                    entry["status"] = "failed"
                    entry["error"] = str(e)

        update_bulk_product_job(job_id, mark_error)
        send_phone_message(f"Best product grab failed: {e}")
    finally:
        clear_active_bulk_job(job_id)


def clean_recipe_url(url):
    if not url:
        return ""

    return str(url).strip().split("#")[0].split("?")[0].rstrip("/")


def recipe_slug(url):
    cleaned = clean_recipe_url(url)

    if not cleaned:
        return ""

    return cleaned.split("/")[-1].strip().lower()


def urls_match(url1, url2):
    clean1 = clean_recipe_url(url1)
    clean2 = clean_recipe_url(url2)

    if clean1 == clean2:
        return True

    slug1 = recipe_slug(url1)
    slug2 = recipe_slug(url2)

    return bool(slug1 and slug2 and slug1 == slug2)


def recipe_number_map(current_urls):
    mapping = {}

    for index, recipe in enumerate(current_urls, start=1):
        mapping[clean_recipe_url(recipe["url"])] = index

    return mapping


def get_recipe_number(source_url, recipe_map):
    if not source_url:
        return "manual"

    cleaned = clean_recipe_url(source_url)

    if cleaned in recipe_map:
        return recipe_map[cleaned]

    slug = recipe_slug(source_url)

    for recipe_url, number in recipe_map.items():
        if recipe_slug(recipe_url) == slug:
            return number

    return "?"


def recipe_name_from_url(url):
    name = clean_recipe_url(url).split("/")[-1]
    name = name.replace("-", " ").replace("_", " ").title()
    return name or url


def format_url_log_entry(url):
    return f"{recipe_name_from_url(url)}|{url}"


def normalize(text):
    return " ".join(str(text).strip().lower().split())


def is_section_header(text):
    text = text.strip()
    return text.startswith("===") and text.endswith("===")


def section_header(section_name):
    return f"=== {section_name} ==="


def remove_empty_sections_from_items(items):
    cleaned = []
    current_section = None
    current_items = []

    for item in items:
        if is_section_header(item):
            if current_section and current_items:
                cleaned.append(current_section)
                cleaned.extend(current_items)

            current_section = item
            current_items = []
        else:
            if current_section:
                current_items.append(item)
            else:
                cleaned.append(item)

    if current_section and current_items:
        cleaned.append(current_section)
        cleaned.extend(current_items)

    return cleaned


def get_source_list_for_item(item, item_sources):
    key = normalize(item)
    sources = item_sources.get(key, [])

    if isinstance(sources, str):
        sources = [{"url": sources}]

    if isinstance(sources, dict):
        sources = [sources]

    if not isinstance(sources, list):
        sources = []

    return sources


def get_item_store_section(item, item_sources):
    sources = get_source_list_for_item(item, item_sources)

    for source in sources:
        if isinstance(source, dict):
            section = source.get("store_section")
            if section:
                section = str(section).strip().upper()
                if section in SECTION_ORDER:
                    return section

    return "MISC"


def sort_items_with_sections(items, item_sources):
    actual_items = [
        item for item in items
        if item.strip() and not is_section_header(item)
    ]

    grouped = {section: [] for section in SECTION_ORDER.keys()}

    for item in actual_items:
        section = get_item_store_section(item, item_sources)
        grouped.setdefault(section, []).append(item)

    result = []

    for section in SECTION_ORDER.keys():
        section_items = grouped.get(section, [])

        if section_items:
            section_items = sorted(section_items, key=lambda item: normalize(item))
            result.append(section_header(section))
            result.extend(section_items)

    return result


def get_section_counts(items):
    counts = {}
    current_section = None

    for item in items:
        if is_section_header(item):
            current_section = item.replace("===", "").strip()
            counts[current_section] = 0
            continue

        if current_section:
            counts[current_section] = counts.get(current_section, 0) + 1

    return counts


def build_store_view(items, item_sources, item_state, enabled_stores):
    stores = load_all_stores()
    enabled_stores = [
        store_key for store_key in enabled_stores
        if store_key in stores
    ]

    store_view = {store_key: {} for store_key in enabled_stores}
    store_view["unselected"] = {}

    for store in store_view:
        for section in SECTION_ORDER.keys():
            store_view[store][section] = []

    for item in items:
        if is_section_header(item):
            continue

        item_key = normalize(item)
        state = item_state.get(item_key, {})
        store = state.get("store") or "unselected"

        if store not in enabled_stores:
            store = "unselected"

        section = get_item_store_section(item, item_sources)
        store_view[store][section].append(item)

    cleaned_store_view = {}
    display_order = enabled_stores + ["unselected"]

    for store in display_order:
        sections = store_view.get(store, {})
        cleaned_sections = {}

        for section in SECTION_ORDER.keys():
            section_items = sections.get(section, [])

            if section_items:
                cleaned_sections[section] = sorted(
                    section_items,
                    key=lambda x: normalize(x)
                )

        if cleaned_sections:
            if store == "unselected":
                display_name = "Unselected"
            else:
                display_name = stores.get(store, {}).get("label", store.title())

            cleaned_store_view[display_name] = cleaned_sections

    return cleaned_store_view



def normalize_text_list(value):
    if not value:
        return []

    if isinstance(value, str):
        value = [value]

    if not isinstance(value, list):
        return []

    cleaned = []

    for entry in value:
        if entry is None:
            continue

        if isinstance(entry, dict):
            text = (
                entry.get("text")
                or entry.get("instruction")
                or entry.get("step")
                or entry.get("name")
                or entry.get("equipment")
                or entry.get("item")
            )
        else:
            text = entry

        text = str(text).strip()

        if text:
            cleaned.append(text)

    return cleaned


def pretty_label(text):
    text = str(text or "").strip().replace("_", " ")
    return text.title()


def normalize_nutrition_items(nutrition):
    if not nutrition or not isinstance(nutrition, dict):
        return []

    preferred_order = [
        "serving_basis",
        "calories",
        "carbohydrates",
        "protein",
        "fat",
        "saturated_fat",
        "polyunsaturated_fat",
        "monounsaturated_fat",
        "trans_fat",
        "cholesterol",
        "sodium",
        "potassium",
        "fiber",
        "sugar",
        "vitamin_a",
        "vitamin_c",
        "calcium",
        "iron",
    ]

    items = []

    for key in preferred_order:
        value = nutrition.get(key)

        if value is None or value == "":
            continue

        items.append({
            "label": pretty_label(key),
            "value": str(value).strip()
        })

    other = nutrition.get("other", [])

    if isinstance(other, dict):
        other = [other]

    if isinstance(other, list):
        for entry in other:
            if not isinstance(entry, dict):
                continue

            name = entry.get("name")
            value = entry.get("value")

            if not name or value is None or value == "":
                continue

            items.append({
                "label": pretty_label(name),
                "value": str(value).strip()
            })

    return items

def build_recipe_view(items, item_sources, current_urls):
    recipe_view = []
    recipe_details = load_recipe_details()

    for index, recipe in enumerate(current_urls, start=1):
        section_groups = {section: [] for section in SECTION_ORDER.keys()}

        for item in items:
            if is_section_header(item):
                continue

            item_key = normalize(item)
            sources = item_sources.get(item_key, [])

            if isinstance(sources, str):
                sources = [{"url": sources}]

            if isinstance(sources, dict):
                sources = [sources]

            if not isinstance(sources, list):
                sources = []

            for source in sources:
                if isinstance(source, str):
                    source_url = source
                    quantity = None
                    unit = None
                    store_section = "MISC"
                else:
                    source_url = source.get("url", "")
                    quantity = source.get("quantity")
                    unit = source.get("unit")
                    store_section = str(
                        source.get("store_section") or "MISC"
                    ).strip().upper()

                if store_section not in SECTION_ORDER:
                    store_section = "MISC"

                if urls_match(source_url, recipe["url"]):
                    section_groups[store_section].append({
                        "name": item,
                        "quantity": quantity,
                        "unit": unit,
                        "url": source_url
                    })
                    break

        cleaned_sections = {}

        for section in SECTION_ORDER.keys():
            section_items = section_groups.get(section, [])

            if section_items:
                cleaned_sections[section] = sorted(
                    section_items,
                    key=lambda x: normalize(x["name"])
                )

        details = recipe_details.get(clean_recipe_url(recipe["url"]), {})

        recipe_view.append({
            "number": index,
            "name": details.get("recipe_title") or recipe["name"],
            "url": recipe["url"],
            "servings": details.get("servings"),
            "equipment": details.get("equipment", []),
            "instructions": details.get("instructions", []),
            "equipment_items": normalize_text_list(details.get("equipment", [])),
            "instruction_items": normalize_text_list(details.get("instructions", [])),
            "nutrition_items": normalize_nutrition_items(details.get("nutrition")),
            "sections": cleaned_sections
        })

    return recipe_view


def load_items():
    ensure_list()
    text = SHOPPING_LIST_FILE.read_text(encoding="utf-8")
    items = [line.strip() for line in text.splitlines() if line.strip()]
    return text, items


def save_items(items):
    with file_lock:
        SHOPPING_LIST_FILE.write_text(
            "\n".join(items),
            encoding="utf-8"
        )


def load_item_sources():
    if not ITEM_SOURCES_FILE.exists():
        return {}

    try:
        return json.loads(ITEM_SOURCES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_item_sources(sources):
    with file_lock:
        ITEM_SOURCES_FILE.write_text(
            json.dumps(sources, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def load_current_urls():
    ensure_log_files()

    results = []

    for line in CURRENT_URL_LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line:
            continue

        if "|" in line:
            name, url = line.split("|", 1)
        else:
            url = line
            name = recipe_name_from_url(url)

        results.append({
            "name": name,
            "url": url
        })

    return results


def save_current_urls(recipes):
    with file_lock:
        CURRENT_URL_LOG_FILE.write_text(
            "\n".join(
                f"{recipe['name']}|{recipe['url']}"
                for recipe in recipes
            ) + ("\n" if recipes else ""),
            encoding="utf-8"
        )


def append_urls_to_logs(urls):
    ensure_log_files()

    existing = load_current_urls()
    seen = set(clean_recipe_url(recipe["url"]) for recipe in existing)

    unique_urls = []

    for url in urls:
        cleaned = clean_recipe_url(url)

        if cleaned in seen:
            continue

        seen.add(cleaned)
        unique_urls.append(cleaned)

    with file_lock:
        with URL_HISTORY_FILE.open("a", encoding="utf-8") as f:
            for url in unique_urls:
                f.write(format_url_log_entry(url) + "\n")

        with CURRENT_URL_LOG_FILE.open("a", encoding="utf-8") as f:
            for url in unique_urls:
                f.write(format_url_log_entry(url) + "\n")


def send_phone_message(message):
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": "Shopping List",
                "Priority": "default",
                "Tags": "shopping_cart"
            },
            timeout=10
        )
        print("Phone message sent")
    except Exception as e:
        print(f"Could not send phone message: {e}")


def add_ingredients_without_duplicates(new_items):
    ensure_list()

    existing_items = [
        line.strip()
        for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not is_section_header(line)
    ]

    existing_set = set(normalize(item) for item in existing_items)
    filtered_new = []

    for item in new_items:
        item = item.strip()

        if not item or is_section_header(item):
            continue

        key = normalize(item)

        if key in existing_set:
            continue

        filtered_new.append(item)
        existing_set.add(key)

    final_items = existing_items + filtered_new
    save_items(final_items)

    added = len(filtered_new)
    skipped = len(new_items) - added

    print(f"Added {added} new shopping items.")
    print(f"Skipped {skipped} duplicate items.")

    return added, skipped


def load_ingredients_from_output_json(target_urls):
    ingredients = []
    sources = load_item_sources()
    recipe_details = load_recipe_details()

    if not OUTPUT_FOLDER.exists():
        return ingredients

    for json_file in OUTPUT_FOLDER.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            source_url = data.get("source_url", "")

            if not source_url:
                continue

            should_process = any(
                urls_match(source_url, target_url)
                for target_url in target_urls
            )

            if not should_process:
                print(f"Skipping old output JSON: {json_file.name}")
                continue

            print(f"Processing output JSON: {json_file.name}")

            recipe_details[clean_recipe_url(source_url)] = {
                "recipe_title": data.get("recipe_title"),
                "servings": data.get("servings"),
                "equipment": data.get("equipment", []),
                "instructions": data.get("instructions", []),
                "nutrition": data.get("nutrition")
            }

            for ing in data.get("ingredients", []):
                name = ing.get("ingredient")

                if name:
                    item_name = name.strip()
                    ingredients.append(item_name)

                    key = normalize(item_name)

                    quantity = ing.get("quantity")
                    unit = ing.get("unit")
                    original_text = ing.get("original_text")
                    store_section = ing.get("store_section")
                    store_section_order = ing.get("store_section_order")

                    if store_section:
                        store_section = str(store_section).strip().upper()

                    if store_section not in SECTION_ORDER:
                        store_section = "MISC"

                    try:
                        store_section_order = int(store_section_order)
                    except Exception:
                        store_section_order = SECTION_ORDER.get(store_section, 9)

                    if key not in sources:
                        sources[key] = []

                    if isinstance(sources[key], str):
                        sources[key] = [
                            {
                                "url": sources[key],
                                "quantity": None,
                                "unit": None,
                                "original_text": None,
                                "store_section": store_section,
                                "store_section_order": store_section_order
                            }
                        ]

                    converted_sources = []

                    for entry in sources[key]:
                        if isinstance(entry, str):
                            converted_sources.append(
                                {
                                    "url": entry,
                                    "quantity": None,
                                    "unit": None,
                                    "original_text": None,
                                    "store_section": store_section,
                                    "store_section_order": store_section_order
                                }
                            )
                        else:
                            converted_sources.append(entry)

                    sources[key] = converted_sources

                    existing_urls = [
                        entry.get("url")
                        for entry in sources[key]
                        if isinstance(entry, dict)
                    ]

                    already_exists = any(
                        urls_match(existing_url, source_url)
                        for existing_url in existing_urls
                        if existing_url
                    )

                    if not already_exists:
                        sources[key].append(
                            {
                                "url": source_url,
                                "quantity": quantity,
                                "unit": unit,
                                "original_text": original_text,
                                "store_section": store_section,
                                "store_section_order": store_section_order
                            }
                        )

        except Exception as e:
            print(f"Could not read {json_file}: {e}")

    save_recipe_details(recipe_details)
    save_item_sources(sources)
    return ingredients


def delete_existing_output_json_for_urls(urls):
    if not OUTPUT_FOLDER.exists():
        return

    for json_file in OUTPUT_FOLDER.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            source_url = data.get("source_url", "")

            if any(urls_match(source_url, url) for url in urls):
                json_file.unlink()
                print(f"Deleted old output JSON: {json_file.name}")

        except Exception:
            pass


def update_extract_job(job_id, **updates):
    if not job_id:
        return None

    with extract_lock:
        job = extract_jobs.get(job_id)

        if not job:
            return None

        job.update(updates)
        return json.loads(json.dumps(job))


def get_extract_job(job_id):
    with extract_lock:
        job = extract_jobs.get(job_id)

        if not job:
            return None

        return json.loads(json.dumps(job))


def create_extract_job(urls):
    job_id = uuid.uuid4().hex

    with extract_lock:
        extract_jobs[job_id] = {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "message": "Queued",
            "summary": f"Queued {len(urls)} recipe URL(s).",
            "progress": 5,
            "done": False,
            "success": False,
            "added": 0,
            "skipped": 0,
            "completed": 0,
            "total": len(urls),
            "active_url": "",
            "error": None,
            "urls": [
                {
                    "url": url,
                    "status": "queued",
                    "checked": False,
                    "message": "Waiting..."
                }
                for url in urls
            ],
        }

    return job_id


def update_extract_url(job_id, target_url, status, message="", checked=None):
    if not job_id:
        return None

    with extract_lock:
        job = extract_jobs.get(job_id)

        if not job:
            return None

        job["active_url"] = target_url

        for entry in job.get("urls", []):
            if isinstance(entry, dict) and urls_match(entry.get("url", ""), target_url):
                entry["status"] = status
                entry["message"] = message

                if checked is not None:
                    entry["checked"] = bool(checked)

                break

        completed = 0

        for entry in job.get("urls", []):
            if isinstance(entry, dict) and entry.get("status") in ["done", "failed", "skipped"]:
                completed += 1

        job["completed"] = completed
        total = job.get("total") or len(job.get("urls", [])) or 1
        job["progress"] = max(job.get("progress", 0), min(95, int((completed / total) * 90) + 5))

        return json.loads(json.dumps(job))


def run_extractor_and_update_list(urls, job_id=None):
    total_added = 0
    total_skipped = 0
    failed_count = 0

    try:
        print("Starting extractor...")
        update_extract_job(
            job_id,
            status="running",
            message="Preparing extraction...",
            summary=f"Preparing {len(urls)} recipe URL(s).",
            progress=5,
        )

        for index, url in enumerate(urls, start=1):
            update_extract_job(
                job_id,
                status="running",
                message=f"Downloading recipe {index} of {len(urls)}...",
                summary="Fetching recipe page and extracting ingredients.",
                active_url=url,
            )

            update_extract_url(
                job_id,
                url,
                "downloading",
                "Downloading recipe page...",
                checked=False,
            )

            try:
                delete_existing_output_json_for_urls([url])

                # Write one URL at a time so the progress modal can show exactly
                # which recipe is currently being downloaded/extracted.
                URLS_FILE.write_text(url, encoding="utf-8")

                update_extract_url(
                    job_id,
                    url,
                    "extracting",
                    "Running recipe extractor...",
                    checked=False,
                )

                subprocess_result = subprocess.run(
                    ["py", "-3.11", str(EXTRACTOR_FILE)],
                    cwd=str(EXTRACTOR_FOLDER),
                    check=False,
                )

                if subprocess_result.returncode != 0:
                    failed_count += 1
                    update_extract_url(
                        job_id,
                        url,
                        "failed",
                        f"Extractor exited with code {subprocess_result.returncode}.",
                        checked=False,
                    )
                    continue

                update_extract_url(
                    job_id,
                    url,
                    "reading output",
                    "Reading extracted JSON output...",
                    checked=False,
                )

                ingredients = load_ingredients_from_output_json([url])

                if ingredients:
                    update_extract_url(
                        job_id,
                        url,
                        "saving",
                        f"Saving {len(ingredients)} ingredient(s)...",
                        checked=False,
                    )

                    added, skipped = add_ingredients_without_duplicates(ingredients)
                    total_added += added
                    total_skipped += skipped

                    raw_text, items = load_items()
                    item_sources = load_item_sources()
                    sorted_items = sort_items_with_sections(items, item_sources)
                    sorted_items = remove_empty_sections_from_items(sorted_items)
                    save_items(sorted_items)

                    update_extract_url(
                        job_id,
                        url,
                        "done",
                        f"Downloaded and extracted. Added {added}; skipped {skipped} duplicate(s).",
                        checked=True,
                    )
                else:
                    total_skipped += 1
                    update_extract_url(
                        job_id,
                        url,
                        "skipped",
                        "Downloaded, but no matching ingredients were found.",
                        checked=True,
                    )

                current_job = get_extract_job(job_id) or {}
                completed = current_job.get("completed", index)
                total = current_job.get("total", len(urls)) or len(urls)
                update_extract_job(
                    job_id,
                    status="running",
                    message=f"Processed {completed} of {total} recipe(s).",
                    summary=f"Added {total_added} item(s). Skipped {total_skipped}. Failed {failed_count}.",
                    added=total_added,
                    skipped=total_skipped,
                )

            except Exception as recipe_error:
                failed_count += 1
                print(f"Recipe extraction failed for {url}: {recipe_error}")
                traceback.print_exc()
                update_extract_url(
                    job_id,
                    url,
                    "failed",
                    str(recipe_error),
                    checked=False,
                )

        success = failed_count == 0
        final_message = "Extraction complete" if success else "Extraction finished with errors"
        final_summary = f"Done! Added {total_added} item(s). Skipped {total_skipped}. Failed {failed_count}."

        update_extract_job(
            job_id,
            status="done" if success else "error",
            message=final_message,
            summary=final_summary,
            progress=100,
            done=True,
            success=success,
            added=total_added,
            skipped=total_skipped,
            error=None if success else final_summary,
        )

        clear_active_extract_job(job_id)
        send_phone_message(final_summary)

    except Exception as e:
        print(f"Extractor/update failed: {e}")
        traceback.print_exc()
        update_extract_job(
            job_id,
            status="error",
            message="Extraction failed",
            summary=str(e),
            progress=100,
            done=True,
            success=False,
            error=str(e),
        )
        clear_active_extract_job(job_id)
        send_phone_message(f"Extraction failed: {e}")


@app.route("/")
def home():
    raw_items, items = load_items()
    item_sources = load_item_sources()
    item_state = load_item_state()
    enabled_stores = load_store_settings()
    store_view = build_store_view(items, item_sources, item_state, enabled_stores)
    current_urls = load_current_urls()
    recipe_map = recipe_number_map(current_urls)
    recipe_view = build_recipe_view(items, item_sources, current_urls)
    message = request.args.get("message", "")
    choose_item_key = request.args.get("choose_item", "")
    product_choice_item, product_choices = get_product_choices_for_item(choose_item_key) if choose_item_key else (None, [])
    product_choice_selected = None

    if choose_item_key:
        choices = load_product_choices()
        choice_entry = choices.get(choose_item_key, {})

        if isinstance(choice_entry, dict):
            product_choice_selected = choice_entry.get("selected_product")

        if not product_choice_selected:
            product_choice_selected = get_selected_product_for_item_key(choose_item_key, item_sources)

    bulk_preview = request.args.get("bulk_preview", "")
    bulk_preview_items = get_grabbable_product_items(skip_existing=True) if bulk_preview else []
    bulk_job_id = request.args.get("bulk_job", "") or load_active_bulk_job()
    extract_job_id = request.args.get("extract_job", "") or load_active_extract_job()
    nearest_job_id = request.args.get("nearest_job", "") or load_active_nearest_stores_job()

    return render_template_string(
        HTML,
        raw_items=raw_items,
        items=items,
        section_counts=get_section_counts(items),
        item_sources=item_sources,
        item_state=item_state,
        store_view=store_view,
        recipe_view=recipe_view,
        current_urls=current_urls,
        recipe_map=recipe_map,
        get_recipe_number=get_recipe_number,
        normalize=normalize,
        is_section_header=is_section_header,
        item_has_selected_product=item_has_selected_product,
        get_selected_store_for_item=get_selected_store_for_item,
        get_selected_product_for_item_key=get_selected_product_for_item_key,
        available_stores=load_all_stores(),
        store_locations=load_store_location_results(),
        home_address=load_home_address_form(),
        enabled_stores=enabled_stores,
        store_urls=store_urls_for_enabled_stores(enabled_stores),
        product_choice_item=product_choice_item,
        product_choices=product_choices,
        product_choice_selected=product_choice_selected,
        bulk_preview_items=bulk_preview_items,
        bulk_job_id=bulk_job_id,
        extract_job_id=extract_job_id,
        nearest_job_id=nearest_job_id,
        message=message,
        ntfy_topic=NTFY_TOPIC
    )


@app.route("/save_home_address", methods=["POST"])
def save_home_address_route():
    home = save_home_address_to_results(request.form)
    ok, message = update_find_nearest_stores_address_constants(home)

    action = request.form.get("action", "save")

    if action == "run_find_nearest":
        if not ok:
            return redirect(f"/?message={message}")

        job_id = create_nearest_stores_job(home)
        save_active_nearest_stores_job(job_id)

        threading.Thread(
            target=run_find_nearest_stores_job,
            args=(job_id, home),
            daemon=True
        ).start()

        return redirect(f"/?message=Finding nearest stores&nearest_job={job_id}")

    return redirect("/?message=Home address saved")


@app.route("/save_state", methods=["POST"])
def save_state_route():
    data = request.get_json(force=True)

    item_key = data.get("item_key")
    checked = data.get("checked")
    store = data.get("store")

    if not item_key:
        return {"ok": False, "error": "Missing item_key"}, 400

    state = load_item_state()

    if item_key not in state:
        state[item_key] = {}

    if checked is not None:
        state[item_key]["checked"] = bool(checked)

    if store is not None:
        state[item_key]["store"] = store

    save_item_state(state)

    return {"ok": True}


@app.route("/reset_checks", methods=["POST"])
def reset_checks():
    state = load_item_state()

    for key in state:
        if isinstance(state[key], dict):
            state[key]["checked"] = False

    save_item_state(state)

    return redirect("/?message=All checkboxes reset")


@app.route("/add_store", methods=["POST"])
def add_store():
    label = request.form.get("store_label", "").strip()
    homepage_url = request.form.get("homepage_url", "").strip()
    store_url = request.form.get("store_url", "").strip()
    url_store_selector = request.form.get("urlStoreSelector", "").strip()

    if not label:
        return redirect("/?message=Store name is required")

    key = normalize_store_key(label)

    if not key:
        return redirect("/?message=Store name could not be converted to a store ID")

    if not store_url:
        store_url = guess_store_search_url(homepage_url)

    if not store_url:
        return redirect("/?message=Add a homepage URL or search URL")

    if not store_url.startswith(("http://", "https://")):
        store_url = "https://" + store_url

    if url_store_selector and not url_store_selector.startswith(("http://", "https://")):
        url_store_selector = "https://" + url_store_selector

    stores = load_all_stores()

    original_key = key
    counter = 2

    while key in stores:
        key = f"{original_key}_{counter}"
        counter += 1

    stores[key] = {
        "label": label,
        "url": store_url,
        "urlStoreSelector": url_store_selector
    }

    save_all_stores(stores)

    enabled_stores = load_store_settings()

    if key not in enabled_stores:
        enabled_stores.append(key)
        save_store_settings(enabled_stores)

    return redirect(f"/?message=Store added: {label}")


@app.route("/edit_store", methods=["POST"])
def edit_store():
    old_key = normalize_store_key(request.form.get("old_store_key", ""))
    new_key = normalize_store_key(request.form.get("store_key", ""))
    label = request.form.get("store_label", "").strip()
    store_url = request.form.get("store_url", "").strip()
    url_store_selector = request.form.get("urlStoreSelector", "").strip()

    stores = load_all_stores()

    if not old_key or old_key not in stores:
        return redirect("/?message=Store not found")

    if not new_key or not label or not store_url:
        return redirect("/?message=Missing store fields")

    if not store_url.startswith(("http://", "https://")):
        store_url = "https://" + store_url

    if url_store_selector and not url_store_selector.startswith(("http://", "https://")):
        url_store_selector = "https://" + url_store_selector

    if new_key != old_key and new_key in stores:
        return redirect("/?message=Store ID already exists")

    old_store = stores.pop(old_key)
    stores[new_key] = {
        **old_store,
        "label": label,
        "url": store_url,
        "urlStoreSelector": url_store_selector
    }

    save_all_stores(stores)

    enabled_stores = load_store_settings()
    enabled_stores = [
        new_key if key == old_key else key
        for key in enabled_stores
    ]
    save_store_settings(enabled_stores)

    state = load_item_state()

    for item_key in state:
        if isinstance(state[item_key], dict) and state[item_key].get("store") == old_key:
            state[item_key]["store"] = new_key

    save_item_state(state)

    return redirect(f"/?message=Store updated: {label}")



def optional_float(value):
    value = str(value or "").strip()

    if not value:
        return None

    try:
        return float(value)
    except Exception:
        return None


@app.route("/edit_store_location_choice", methods=["POST"])
def edit_store_location_choice():
    store_key = normalize_store_key(request.form.get("store_key", ""))

    try:
        candidate_index = int(request.form.get("candidate_index", "-1"))
    except Exception:
        candidate_index = -1

    if not store_key:
        return redirect("/?message=No store selected")

    data = load_store_results_payload()
    stores = data.get("stores", {})
    store_data = stores.get(store_key)

    if not isinstance(store_data, dict):
        return redirect(f"/?message=No location data found for {store_key}")

    candidates = store_data.get("candidates", [])

    if not isinstance(candidates, list) or candidate_index < 0 or candidate_index >= len(candidates):
        return redirect(f"/?message=Invalid location choice for {store_key}")

    candidate = candidates[candidate_index]

    if not isinstance(candidate, dict):
        return redirect(f"/?message=Invalid location choice for {store_key}")

    candidate["name"] = request.form.get("candidate_name", "").strip() or candidate.get("name")
    candidate["exact_address"] = request.form.get("candidate_exact_address", "").strip() or candidate.get("exact_address")
    candidate["website"] = request.form.get("candidate_website", "").strip() or None
    candidate["place_url"] = request.form.get("candidate_place_url", "").strip() or None
    candidate["phone"] = request.form.get("candidate_phone", "").strip() or None

    candidate["lat"] = optional_float(request.form.get("candidate_lat"))
    candidate["lng"] = optional_float(request.form.get("candidate_lng"))
    candidate["distance_miles"] = optional_float(request.form.get("candidate_distance_miles"))

    candidates[candidate_index] = candidate
    store_data["candidates"] = candidates

    selected_place = str(store_data.get("place_url") or "")
    selected_website = str(store_data.get("website") or "")
    selected_address = clean_maps_prefix(store_data.get("exact_address"))

    edited_is_selected = (
        (candidate.get("place_url") and selected_place and candidate.get("place_url") == selected_place)
        or (candidate.get("website") and selected_website and candidate.get("website") == selected_website)
        or (clean_maps_prefix(candidate.get("exact_address")) and selected_address and clean_maps_prefix(candidate.get("exact_address")) == selected_address)
        or store_data.get("manual_choice_index") == candidate_index
    )

    if edited_is_selected:
        store_data.update({
            "selected_name": clean_maps_prefix(candidate.get("name")) or store_data.get("store_name") or store_key.title(),
            "exact_address": clean_maps_prefix(candidate.get("exact_address")),
            "lat": candidate.get("lat"),
            "lng": candidate.get("lng"),
            "website": candidate.get("website"),
            "place_url": candidate.get("place_url"),
            "phone": clean_maps_prefix(candidate.get("phone")),
            "distance_miles": candidate.get("distance_miles"),
            "manual_choice_index": candidate_index,
            "manual_choice_selected": True,
        })

        existing_update = store_data.get("website_home_store_update")
        if isinstance(existing_update, dict):
            existing_update["ok"] = False
            existing_update["message"] = "Location choice edited in app; rerun website selection before scraping."
            store_data["website_home_store_update"] = existing_update

    stores[store_key] = store_data
    data["stores"] = stores
    save_store_results_payload(data)

    label = load_all_stores().get(store_key, {}).get("label", store_key.title())
    return redirect(f"/?message={label} location choice edited")

@app.route("/select_store_location_choice", methods=["POST"])
def select_store_location_choice():
    store_key = normalize_store_key(request.form.get("store_key", ""))

    try:
        candidate_index = int(request.form.get("candidate_index", "-1"))
    except Exception:
        candidate_index = -1

    if not store_key:
        return redirect("/?message=No store selected")

    data = load_store_results_payload()
    stores = data.get("stores", {})
    store_data = stores.get(store_key)

    if not isinstance(store_data, dict):
        return redirect(f"/?message=No location data found for {store_key}")

    candidates = store_data.get("candidates", [])

    if not isinstance(candidates, list) or candidate_index < 0 or candidate_index >= len(candidates):
        return redirect(f"/?message=Invalid location choice for {store_key}")

    candidate = candidates[candidate_index]

    if not isinstance(candidate, dict):
        return redirect(f"/?message=Invalid location choice for {store_key}")

    selected_name = clean_maps_prefix(candidate.get("name")) or store_data.get("store_name") or store_key.title()
    exact_address = clean_maps_prefix(candidate.get("exact_address"))
    phone = clean_maps_prefix(candidate.get("phone"))

    store_data.update({
        "selected_name": selected_name,
        "exact_address": exact_address,
        "lat": candidate.get("lat"),
        "lng": candidate.get("lng"),
        "website": candidate.get("website"),
        "place_url": candidate.get("place_url"),
        "phone": phone,
        "distance_miles": candidate.get("distance_miles"),
        "manual_choice_index": candidate_index,
        "manual_choice_selected": True,
    })

    # The website may still be set to the previous pickup/home store.
    # Mark it as needing to be applied again by the scraper or update_home_stores.py.
    existing_update = store_data.get("website_home_store_update")
    if isinstance(existing_update, dict):
        existing_update["ok"] = False
        existing_update["message"] = "Location choice changed in app; rerun website selection before scraping."
        store_data["website_home_store_update"] = existing_update

    stores[store_key] = store_data
    data["stores"] = stores
    save_store_results_payload(data)

    label = load_all_stores().get(store_key, {}).get("label", store_key.title())
    return redirect(f"/?message={label} location selected")


@app.route("/delete_store", methods=["POST"])
def delete_store():
    store_key = normalize_store_key(request.form.get("store_key", ""))

    if not store_key:
        return redirect("/?message=No store selected")

    stores = load_all_stores()

    if store_key not in stores:
        return redirect("/?message=Store not found")

    label = stores[store_key].get("label", store_key.title())
    del stores[store_key]
    save_all_stores(stores)

    enabled_stores = [
        key for key in load_store_settings()
        if key != store_key
    ]
    save_store_settings(enabled_stores)

    state = load_item_state()

    for item_key in state:
        if isinstance(state[item_key], dict) and state[item_key].get("store") == store_key:
            state[item_key]["store"] = "unselected"

    save_item_state(state)

    return redirect(f"/?message=Store deleted: {label}")


@app.route("/save_store_settings", methods=["POST"])
def save_store_settings_route():
    stores = load_all_stores()

    # Persist exactly what is checked. If no boxes are checked, save an empty list.
    enabled_stores = [
        normalize_store_key(store_key)
        for store_key in request.form.getlist("enabled_stores")
        if normalize_store_key(store_key) in stores
    ]

    enabled_stores = save_store_settings(enabled_stores)

    state = load_item_state()

    for key in state:
        if isinstance(state[key], dict):
            selected_store = state[key].get("store")

            if selected_store and selected_store not in enabled_stores:
                state[key]["store"] = "unselected"

    save_item_state(state)

    return redirect("/?message=Store options saved")


@app.route("/reset_stores", methods=["POST"])
def reset_stores():
    state = load_item_state()

    for key in state:
        if isinstance(state[key], dict):
            state[key]["store"] = "unselected"

    save_item_state(state)

    return redirect("/?message=All store selections reset")


@app.route("/extract", methods=["POST"])
def extract():
    urls_text = request.form.get("urls", "")

    seen = set()
    urls = []

    for line in urls_text.replace(",", "\n").splitlines():
        raw = line.strip().strip(",")

        if not raw.startswith("http"):
            continue

        cleaned = clean_recipe_url(raw)

        if cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)

    if not urls:
        return redirect("/?message=No valid URLs")

    append_urls_to_logs(urls)

    URLS_FILE.write_text(
        "\n".join(urls),
        encoding="utf-8"
    )

    job_id = create_extract_job(urls)
    save_active_extract_job(job_id)

    threading.Thread(
        target=run_extractor_and_update_list,
        args=(urls, job_id),
        daemon=True
    ).start()

    return redirect(f"/?message=Extraction started&extract_job={job_id}")


@app.route("/extract_status/<job_id>")
def extract_status(job_id):
    job = get_extract_job(job_id)

    if not job:
        return {"ok": False, "error": "Job not found"}, 404

    job["ok"] = True
    return job


@app.route("/active_extract_status")
def active_extract_status():
    job_id = load_active_extract_job()

    if not job_id:
        return {"ok": True, "extract_job_id": "", "job": None}

    job = get_extract_job(job_id)

    return {
        "ok": True,
        "extract_job_id": job_id,
        "job": job,
    }


@app.route("/nearest_stores_status/<job_id>")
def nearest_stores_status(job_id):
    job = get_nearest_stores_job(job_id)

    if not job:
        return {"ok": False, "error": "Job not found"}, 404

    job["ok"] = True
    return job


@app.route("/active_nearest_stores_status")
def active_nearest_stores_status():
    job_id = load_active_nearest_stores_job()

    if not job_id:
        return {"ok": True, "nearest_job_id": "", "job": None}

    job = get_nearest_stores_job(job_id)

    return {
        "ok": True,
        "nearest_job_id": job_id,
        "job": job,
    }


@app.route("/save", methods=["POST"])
def save():
    items_text = request.form.get("items", "")

    items = [
        line.strip()
        for line in items_text.splitlines()
        if line.strip()
    ]

    items = remove_empty_sections_from_items(items)
    save_items(items)

    send_phone_message("Shopping list saved")

    return redirect("/?message=Shopping list saved")


@app.route("/sort", methods=["POST"])
def sort_list():
    raw_text, items = load_items()
    item_sources = load_item_sources()

    sorted_items = sort_items_with_sections(items, item_sources)
    sorted_items = remove_empty_sections_from_items(sorted_items)

    save_items(sorted_items)

    send_phone_message("Shopping list sorted")

    return redirect("/?message=Shopping list sorted")


@app.route("/remove_recipe", methods=["POST"])
def remove_recipe():
    url_to_remove = request.form.get("url", "").strip()

    if not url_to_remove:
        return redirect("/?message=No recipe URL selected")

    current_recipes = load_current_urls()

    remaining_recipes = [
        recipe for recipe in current_recipes
        if not urls_match(recipe["url"], url_to_remove)
    ]

    save_current_urls(remaining_recipes)

    sources = load_item_sources()
    cleaned_sources = {}
    removed_item_keys = []

    for item_key, source_list in sources.items():

        if isinstance(source_list, str):
            source_list = [
                {
                    "url": source_list,
                    "quantity": None,
                    "unit": None,
                    "original_text": None
                }
            ]

        remaining_sources = []

        for source in source_list:
            if isinstance(source, str):
                source_url = source
                source_obj = {
                    "url": source,
                    "quantity": None,
                    "unit": None,
                    "original_text": None
                }
            else:
                source_url = source.get("url", "")
                source_obj = source

            if not urls_match(source_url, url_to_remove):
                remaining_sources.append(source_obj)

        if remaining_sources:
            cleaned_sources[item_key] = remaining_sources
        else:
            removed_item_keys.append(normalize(item_key))

    save_item_sources(cleaned_sources)

    recipe_details = load_recipe_details()
    cleaned_url_to_remove = clean_recipe_url(url_to_remove)

    if cleaned_url_to_remove in recipe_details:
        del recipe_details[cleaned_url_to_remove]

    save_recipe_details(recipe_details)

    raw_text, current_items = load_items()

    items_to_remove_set = set(removed_item_keys)

    remaining_items = [
        item
        for item in current_items
        if is_section_header(item) or normalize(item) not in items_to_remove_set
    ]

    remaining_items = remove_empty_sections_from_items(remaining_items)

    save_items(remaining_items)

    removed_count = len(current_items) - len(remaining_items)

    send_phone_message(
        f"Removed recipe. Removed {removed_count} unused ingredients."
    )

    return redirect(
        f"/?message=Recipe removed. Removed {removed_count} unused ingredients."
    )



@app.route("/find_products", methods=["POST"])
def find_products():
    item = request.form.get("item", "").strip()

    if not item:
        return redirect("/?message=No item selected")

    if run_scraper is None and scrape_store_searches_parallel is None and scrape_all_stores is None:
        return redirect("/?message=store_product_scraper.py could not be imported")

    selected_store = get_selected_store_for_item(item)

    if not selected_store:
        return redirect(f"/?message=Select a store before grabbing products for {item}")

    enabled_stores = load_store_settings()
    job_id = create_bulk_product_job([item])
    save_active_bulk_job(job_id)

    threading.Thread(
        target=run_bulk_product_job,
        args=(job_id, enabled_stores),
        daemon=True
    ).start()

    return redirect(f"/?message=Grabbing products for {item}&bulk_job={job_id}")


@app.route("/choose_choice", methods=["POST"])
def choose_choice():
    item = request.form.get("item", "").strip()

    if not item:
        return redirect("/?message=No item selected")

    item_key = normalize(item)
    choices = load_product_choices()
    entry = choices.get(item_key, {})

    if isinstance(entry, dict) and isinstance(entry.get("products"), list) and entry.get("products"):
        return redirect(f"/?message=Choose an choice product&choose_item={item_key}")

    return redirect(f"/?message=No choices saved for {item}")


@app.route("/select_product", methods=["POST"])
def select_product():
    item = request.form.get("item", "").strip()
    product_json = request.form.get("product_json", "").strip()

    if not item or not product_json:
        return redirect("/?message=Missing product selection")

    try:
        product = json.loads(product_json)
    except Exception:
        return redirect("/?message=Invalid product selection")

    if not isinstance(product, dict):
        return redirect("/?message=Invalid product selection")

    append_selected_product_to_item_sources(item, product)

    item_key = normalize(item)
    choices = load_product_choices()

    if item_key in choices:
        choices[item_key]["selected_product"] = product
        choices[item_key]["selected_product_url"] = product.get("product_url")
        save_product_choices(choices)

    return redirect("/?message=Product selected and saved")



@app.route("/preview_grab_best_products", methods=["POST"])
def preview_grab_best_products():
    items = get_grabbable_product_items(skip_existing=True)

    if not items:
        return redirect("/?message=No ingredients with selected stores need product picks")

    return redirect("/?message=Review products before grabbing&bulk_preview=1")


@app.route("/start_grab_best_products", methods=["POST"])
def start_grab_best_products():
    if run_scraper is None:
        return redirect("/?message=store_product_scraper.py could not be imported")

    selected_items = [
        item.strip()
        for item in request.form.getlist("bulk_items")
        if item.strip()
    ]

    allowed_items = set(get_grabbable_product_items(skip_existing=True))
    items = [
        item for item in selected_items
        if item in allowed_items
    ]

    if not items:
        return redirect("/?message=No ingredients selected for product grabbing&bulk_preview=1")

    enabled_stores = load_store_settings()
    job_id = create_bulk_product_job(items)
    save_active_bulk_job(job_id)

    threading.Thread(
        target=run_bulk_product_job,
        args=(job_id, enabled_stores),
        daemon=True
    ).start()

    return redirect(f"/?message=Grabbing best products&bulk_job={job_id}")


@app.route("/active_bulk_product_status")
def active_bulk_product_status():
    job_id = load_active_bulk_job()

    if not job_id:
        return {"ok": True, "bulk_job_id": "", "job": None}

    job = get_bulk_product_job(job_id)

    return {
        "ok": True,
        "bulk_job_id": job_id,
        "job": job,
    }


@app.route("/bulk_product_status/<job_id>")
def bulk_product_status(job_id):
    job = get_bulk_product_job(job_id)

    if not job:
        return {"ok": False, "error": "Job not found"}, 404

    job["ok"] = True
    return job


@app.route("/cancel_bulk_product_grab/<job_id>", methods=["POST"])
def cancel_bulk_product_grab(job_id):
    def updater(job):
        job["cancel_requested"] = True

        if job.get("status") not in ["done", "cancelled", "error"]:
            job["status"] = "cancel_requested"
            job["active_item"] = "Cancelling after current ingredient..."

    job = update_bulk_product_job(job_id, updater)

    if not job:
        return {"ok": False, "error": "Job not found"}, 404

    clear_active_bulk_job(job_id)

    job["ok"] = True
    return job






@app.route("/bulk_select_product/<job_id>", methods=["POST"])
def bulk_select_product(job_id):
    data = request.get_json(force=True)
    item = str(data.get("item", "")).strip()
    product = data.get("product", {})

    if not item or not isinstance(product, dict):
        return {"ok": False, "error": "Invalid selection"}, 400

    append_selected_product_to_item_sources(item, product)

    item_key = normalize(item)
    choices = load_product_choices()

    if item_key in choices and isinstance(choices[item_key], dict):
        choices[item_key]["selected_product"] = product
        save_product_choices(choices)

    def updater(job):
        for entry in job.get("items", []):
            if entry.get("item") == item:
                entry["product_name"] = product.get("product_name")
                entry["product_cost"] = product.get("product_cost")
                entry["selected_product_url"] = product.get("product_url")
                entry["selected_product"] = product
                entry["selected_store"] = product.get("store") or entry.get("selected_store")
                entry["selected_store_label"] = product.get("product_location") or product.get("store") or entry.get("selected_store_label")
                entry["status"] = "done"
                break

        job["status"] = "review"
        job["active_item"] = "Review selected products"

    job = update_bulk_product_job(job_id, updater)

    if not job:
        return {"ok": False, "error": "Job not found"}, 404

    job["ok"] = True
    return job


@app.route("/finish_bulk_product_review/<job_id>", methods=["POST"])
def finish_bulk_product_review(job_id):
    job_snapshot = get_bulk_product_job(job_id)

    if job_snapshot:
        for entry in job_snapshot.get("items", []):
            selected_product = entry.get("selected_product")

            if entry.get("status") == "done" and isinstance(selected_product, dict):
                append_selected_product_to_item_sources(entry.get("item", ""), selected_product)

                item_key = normalize(entry.get("item", ""))
                choices = load_product_choices()

                if item_key in choices and isinstance(choices[item_key], dict):
                    choices[item_key]["selected_product"] = selected_product
                    choices[item_key]["selected_product_url"] = selected_product.get("product_url")
                    save_product_choices(choices)

    def updater(job):
        job["status"] = "done"
        job["active_item"] = "Complete"

    job = update_bulk_product_job(job_id, updater)

    if not job:
        return {"ok": False, "error": "Job not found"}, 404

    clear_active_bulk_job(job_id)

    job["ok"] = True
    return job

@app.route("/clear_product_pick", methods=["POST"])
def clear_product_pick():
    item = request.form.get("item", "").strip()

    if not item:
        return redirect("/?message=No item selected")

    removed = clear_selected_product_for_item(item)

    if removed:
        return redirect(f"/?message=Cleared product pick for {item}")

    return redirect(f"/?message=No product pick found for {item}")

@app.route("/clear_product_picks", methods=["POST"])
def clear_product_picks():
    removed = clear_selected_product_sources()
    return redirect(f"/?message=Cleared {removed} saved product picks")


@app.route("/clear", methods=["POST"])
def clear():
    with file_lock:
        SHOPPING_LIST_FILE.write_text("", encoding="utf-8")
        ITEM_SOURCES_FILE.write_text("{}", encoding="utf-8")
        CURRENT_URL_LOG_FILE.write_text("", encoding="utf-8")
        ITEM_STATE_FILE.write_text("{}", encoding="utf-8")
        RECIPE_DETAILS_FILE.write_text("{}", encoding="utf-8")
        PRODUCT_CHOICES_FILE.write_text("{}", encoding="utf-8")

    send_phone_message("Shopping list cleared")

    return redirect("/?message=Shopping list cleared")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False
    )
