import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from werkzeug.utils import secure_filename

from PushShoppingList.services.storage_service import scoped_package_path


# AI Pantry storage is intentionally local-file based for the MVP.
PANTRY_INVENTORY_FILE = scoped_package_path("pantry_inventory.json")
PANTRY_RECEIPT_HISTORY_FILE = scoped_package_path("pantry_receipt_history.json")
PANTRY_RECEIPT_UPLOAD_DIR = scoped_package_path("pantry_receipts")

DEFAULT_CONFIDENCE_BY_SOURCE = {
    "shopping_list": 0.90,
    "receipt": 0.85,
    "manual": 0.75,
    "photo": 0.60,
    "barcode": 0.95,
}

SOURCE_VALUES = set(DEFAULT_CONFIDENCE_BY_SOURCE.keys())
RECEIPT_SKIP_WORDS = {
    "total",
    "subtotal",
    "tax",
    "visa",
    "mastercard",
    "amex",
    "discover",
    "debit",
    "credit",
    "cash",
    "change",
    "balance",
    "approval",
    "auth",
    "card",
    "tender",
    "receipt",
}

BRAND_AND_STORE_WORDS = {
    "aldi",
    "kroger",
    "walmart",
    "meijer",
    "target",
    "costco",
    "great",
    "value",
    "market",
    "pantry",
    "private",
    "selection",
    "good",
    "gather",
    "simply",
    "nature",
    "organic",
}

VARIANT_NORMALIZATION = {
    "diced tomatoes": "tomato",
    "canned tomatoes": "tomato",
    "crushed tomatoes": "tomato",
    "tomatoes": "tomato",
    "whole milk": "milk",
    "jasmine rice": "rice",
    "brown rice": "rice",
    "white rice": "rice",
    "eggs": "egg",
}


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_pantry_inventory():
    if not PANTRY_INVENTORY_FILE.exists():
        return {"items": []}

    try:
        payload = json.loads(PANTRY_INVENTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}

    if not isinstance(payload, dict):
        return {"items": []}

    return {
        "items": [
            normalize_pantry_item(item)
            for item in payload.get("items", [])
            if isinstance(item, dict)
        ],
    }


def save_pantry_inventory(payload):
    normalized = {
        "items": [
            normalize_pantry_item(item)
            for item in payload.get("items", [])
            if isinstance(item, dict)
        ],
    }
    PANTRY_INVENTORY_FILE.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return normalized


def normalize_pantry_item(item):
    timestamp = str(item.get("date_added") or now_iso())
    source = clean_source(item.get("source"))
    ingredient_name = str(item.get("ingredient_name") or item.get("product_name") or "").strip()
    normalized_name = normalize_ingredient_name(item.get("normalized_name") or ingredient_name)

    return {
        "id": str(item.get("id") or uuid.uuid4().hex),
        "ingredient_name": ingredient_name,
        "normalized_name": normalized_name,
        "product_name": str(item.get("product_name") or "").strip(),
        "store": str(item.get("store") or "").strip(),
        "quantity": parse_quantity(item.get("quantity"), default=1),
        "unit": str(item.get("unit") or "").strip(),
        "category": str(item.get("category") or "").strip(),
        "source": source,
        "confidence": clamp_confidence(item.get("confidence"), DEFAULT_CONFIDENCE_BY_SOURCE[source]),
        "date_added": timestamp,
        "last_updated": str(item.get("last_updated") or timestamp),
        "notes": str(item.get("notes") or "").strip(),
    }


def clean_source(source):
    source = str(source or "manual").strip().lower()
    return source if source in SOURCE_VALUES else "manual"


def parse_quantity(value, default=1):
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return default

    if quantity.is_integer():
        return int(quantity)

    return quantity


def clamp_confidence(value, default=0.0):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default

    return max(0.0, min(1.0, round(confidence, 2)))


def normalize_ingredient_name(name):
    text = str(name or "").lower().strip()
    text = re.sub(r"[$]\d+(?:\.\d{2})?", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:x|ct|count|oz|lb|lbs|g|kg|ml|l|pk|pkg)?\b", " ", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    text = " ".join(text.split())

    for phrase, replacement in sorted(VARIANT_NORMALIZATION.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in text:
            return replacement

    words = [word for word in text.split() if word not in BRAND_AND_STORE_WORDS]
    text = " ".join(words).strip()

    if text.endswith("ies") and len(text) > 4:
        text = f"{text[:-3]}y"
    elif text.endswith("es") and len(text) > 3:
        text = text[:-2]
    elif text.endswith("s") and len(text) > 3:
        text = text[:-1]

    return text


def add_or_increment_pantry_item(item):
    payload = load_pantry_inventory()
    incoming = normalize_pantry_item({
        **item,
        "normalized_name": normalize_ingredient_name(
            item.get("normalized_name")
            or item.get("ingredient_name")
            or item.get("product_name")
        ),
    })
    timestamp = now_iso()

    for existing in payload["items"]:
        if existing.get("normalized_name") == incoming["normalized_name"]:
            existing["quantity"] = parse_quantity(existing.get("quantity"), default=0) + parse_quantity(
                incoming.get("quantity"),
                default=1,
            )
            if incoming.get("product_name"):
                existing["product_name"] = incoming["product_name"]
            if incoming.get("store"):
                existing["store"] = incoming["store"]
            if incoming.get("unit"):
                existing["unit"] = incoming["unit"]
            if incoming.get("category"):
                existing["category"] = incoming["category"]
            existing["source"] = incoming["source"]
            existing["confidence"] = max(existing.get("confidence", 0.0), incoming["confidence"])
            existing["last_updated"] = timestamp
            existing["notes"] = incoming.get("notes") or existing.get("notes", "")
            save_pantry_inventory(payload)
            return {"item": existing, "created": False}

    incoming["date_added"] = timestamp
    incoming["last_updated"] = timestamp
    payload["items"].append(incoming)
    save_pantry_inventory(payload)
    return {"item": incoming, "created": True}


def update_pantry_item(item_id, updates):
    payload = load_pantry_inventory()

    for item in payload["items"]:
        if item.get("id") != item_id:
            continue

        for field in ["quantity", "unit", "category", "notes"]:
            if field in updates:
                item[field] = parse_quantity(updates[field]) if field == "quantity" else str(updates[field] or "").strip()

        item["last_updated"] = now_iso()
        save_pantry_inventory(payload)
        return {"ok": True, "item": item}

    return {"ok": False, "error": "Pantry item was not found."}


def delete_pantry_item(item_id):
    payload = load_pantry_inventory()
    before_count = len(payload["items"])
    payload["items"] = [item for item in payload["items"] if item.get("id") != item_id]
    save_pantry_inventory(payload)
    return {"ok": len(payload["items"]) != before_count}


def confidence_label(confidence):
    confidence = clamp_confidence(confidence)

    if confidence >= 0.85:
        return "High"
    if confidence >= 0.60:
        return "Medium"
    return "Low"


def pantry_items_for_view():
    items = sorted(
        load_pantry_inventory()["items"],
        key=lambda item: (item.get("ingredient_name") or item.get("product_name") or "").lower(),
    )

    for item in items:
        item["confidence_label"] = confidence_label(item.get("confidence"))

    return items


def parse_receipt_text(receipt_text):
    candidates = []

    for raw_line in str(receipt_text or "").splitlines():
        line = raw_line.strip()
        if not line or should_skip_receipt_line(line):
            continue

        product_name = clean_receipt_product_name(line)
        normalized_name = normalize_ingredient_name(product_name)

        if not normalized_name:
            continue

        candidates.append({
            "raw_line": line,
            "product_name": product_name,
            "normalized_name": normalized_name,
            "quantity": receipt_line_quantity(line),
            "confidence": receipt_line_confidence(product_name),
            "needs_review": True,
        })

    return candidates


def should_skip_receipt_line(line):
    lowered = line.lower()

    if len(re.sub(r"[^a-z]", "", lowered)) < 2:
        return True

    return any(word in lowered for word in RECEIPT_SKIP_WORDS)


def clean_receipt_product_name(line):
    text = re.sub(r"[$]\s*\d+(?:\.\d{2})?", " ", line)
    text = re.sub(r"\b\d{5,}\b", " ", text)
    text = re.sub(r"^\s*\d+\s*[xX]\s*", " ", text)
    text = re.sub(r"[^A-Za-z\s]", " ", text)
    return " ".join(text.split()).title()


def receipt_line_quantity(line):
    match = re.search(r"^\s*(\d+)\s*[xX]\b", line)
    return int(match.group(1)) if match else 1


def receipt_line_confidence(product_name):
    word_count = len(str(product_name or "").split())
    if word_count >= 2:
        return 0.85
    return 0.72


def save_receipt_upload(upload=None, pasted_text=""):
    receipt_id = uuid.uuid4().hex
    timestamp = now_iso()
    stored_path = ""
    receipt_text = str(pasted_text or "").strip()

    if upload and getattr(upload, "filename", ""):
        PANTRY_RECEIPT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(upload.filename or "")
        stored_name = f"{receipt_id}_{filename}"
        upload.save(PANTRY_RECEIPT_UPLOAD_DIR / stored_name)
        stored_path = f"pantry_receipts/{stored_name}"

        if not receipt_text:
            receipt_text = extract_receipt_text_from_file(PANTRY_RECEIPT_UPLOAD_DIR / stored_name)

    candidates = parse_receipt_text(receipt_text)
    record = {
        "receipt_id": receipt_id,
        "created_at": timestamp,
        "stored_path": stored_path,
        "pasted_text": receipt_text if not stored_path else "",
        "text_excerpt": receipt_text[:500],
        "candidate_count": len(candidates),
        "status": "pending",
    }
    append_receipt_history(record)
    return {
        "receipt_id": receipt_id,
        "receipt_text": receipt_text,
        "candidates": candidates,
        "record": record,
    }


def extract_receipt_text_from_file(path):
    path = Path(path)
    extension = path.suffix.lower()

    if extension in {".txt", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if extension == ".pdf":
        return extract_pdf_text(path)

    return ""


def extract_pdf_text(path):
    try:
        from PyPDF2 import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def load_receipt_history():
    if not PANTRY_RECEIPT_HISTORY_FILE.exists():
        return {"receipts": []}

    try:
        payload = json.loads(PANTRY_RECEIPT_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"receipts": []}

    if not isinstance(payload, dict):
        return {"receipts": []}

    return {
        "receipts": [
            receipt
            for receipt in payload.get("receipts", [])
            if isinstance(receipt, dict) and receipt.get("receipt_id")
        ],
    }


def append_receipt_history(record):
    payload = load_receipt_history()
    payload["receipts"].append(record)
    save_receipt_history(payload)
    return record


def update_receipt_history_status(receipt_id, status, added_count=0):
    payload = load_receipt_history()

    for receipt in payload["receipts"]:
        if receipt.get("receipt_id") == receipt_id:
            receipt["status"] = status
            receipt["added_count"] = added_count
            receipt["last_updated"] = now_iso()
            break

    save_receipt_history(payload)


def save_receipt_history(payload):
    PANTRY_RECEIPT_HISTORY_FILE.write_text(
        json.dumps({"receipts": payload.get("receipts", [])}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def receipt_history_for_view(limit=8):
    receipts = load_receipt_history()["receipts"]
    return sorted(receipts, key=lambda receipt: receipt.get("created_at", ""), reverse=True)[:limit]


def match_recipe_to_pantry(recipe, pantry_items):
    ingredients = recipe_ingredients_for_matching(recipe)
    pantry_names = {
        item.get("normalized_name") or normalize_ingredient_name(item.get("ingredient_name"))
        for item in pantry_items
    }
    pantry_names.discard("")
    matched = []
    missing = []

    for ingredient in ingredients:
        candidate_names = [
            normalize_ingredient_name(ingredient.get("name")),
            normalize_ingredient_name(ingredient.get("purchasable_item")),
            normalize_ingredient_name(ingredient.get("purchase_group")),
        ]
        is_match = any(candidate and candidate in pantry_names for candidate in candidate_names)

        if is_match:
            matched.append(ingredient)
        else:
            missing.append(ingredient)

    total = len(ingredients)
    match_percentage = round((len(matched) / total) * 100) if total else 0

    return {
        "recipe": recipe,
        "recipe_title": recipe.get("name") or "Recipe",
        "recipe_url": recipe.get("url", ""),
        "matched_ingredients": matched,
        "missing_ingredients": missing,
        "matched_count": len(matched),
        "missing_count": len(missing),
        "total_count": total,
        "match_percentage": match_percentage,
        "status": missing_status(len(missing)),
        "sort_key": pantry_recipe_sort_key(len(missing), match_percentage),
    }


def recipe_ingredients_for_matching(recipe):
    ingredients = []

    for section in recipe.get("sections", []) or []:
        for item in section.get("items", []) if isinstance(section, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("display_name") or "").strip()
            if not name:
                continue
            ingredients.append({
                "name": name,
                "display_name": item.get("display_name") or name,
                "purchasable_item": item.get("purchasable_item") or "",
                "purchase_group": item.get("purchase_group") or "",
            })

    return ingredients


def missing_status(missing_count):
    if missing_count <= 0:
        return "Can make now"
    if missing_count == 1:
        return "Missing 1 item"
    if missing_count == 2:
        return "Missing 2 items"
    return "Missing several items"


def pantry_recipe_sort_key(missing_count, match_percentage):
    if missing_count <= 0:
        rank = 0
    elif missing_count == 1:
        rank = 1
    elif missing_count == 2:
        rank = 2
    else:
        rank = 3

    return (rank, -match_percentage)


def pantry_recipe_matches_for_view(recipe_rows, pantry_items):
    matches = [
        match_recipe_to_pantry(recipe, pantry_items)
        for recipe in recipe_rows
    ]
    return sorted(matches, key=lambda match: match["sort_key"])
