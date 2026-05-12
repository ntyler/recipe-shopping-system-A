import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

OUTPUT_FOLDER = PROJECT_DIR / "recipe-extractor" / "data" / "output"
RAW_FOLDER = PROJECT_DIR / "recipe-extractor" / "data" / "raw"
LOG_FOLDER = PROJECT_DIR / "recipe-extractor" / "data" / "logs"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
RAW_FOLDER.mkdir(parents=True, exist_ok=True)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)

MODEL = "gpt-4o-mini"
MAX_PAGE_TEXT_CHARS = 35000
REQUEST_DELAY_SECONDS = 1

client = None


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    return client


def safe_filename(text):
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"www\.", "", text)
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_")[:120] or "recipe"


def clean_json_response(text):
    text = str(text or "").strip()
    text = text.replace("```json", "")
    text = text.replace("```", "")
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = text.replace("\r\n", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    return text.strip()


def fetch_recipe_page_text(recipe_url):
    print(f"Fetching recipe page: {recipe_url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(recipe_url, headers=headers, timeout=30)
    response.raise_for_status()

    html_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_HTML.html"
    html_path.write_text(response.text, encoding="utf-8")

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    page_text = soup.get_text(" ", strip=True)
    page_text = re.sub(r"\s+", " ", page_text).strip()

    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    raw_page_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_TEXT.txt"
    raw_page_path.write_text(page_text, encoding="utf-8")

    print(f"Loaded webpage text: {len(page_text)} characters")

    return page_text


# =========================================================
# PROMPT
# =========================================================
def build_prompt(recipe_url, page_text):
    return f"""
Extract the recipe information from this web page:

{recipe_url}

WEBPAGE TEXT:
{page_text}

Return ONLY valid JSON.

STRICT RULES:
- Do not include markdown.
- Do not include explanations.
- The final response must be valid JSON parsable by Python json.loads().
- Do not use trailing commas.
- Do not use smart quotes.
- Do not use comments.
- All string values must be wrapped in double quotes.
- Arrays and objects must have commas between every item.
- Use null if a value is missing or unknown.
- Preserve wording from the recipe when possible.
- Escape all newline characters inside JSON strings as \\n.
- Do NOT include raw line breaks inside JSON string values. Replace them with spaces.

========================
INGREDIENT RULES
========================
- Split into: quantity, unit, ingredient, preparation when possible.
- Preserve original_text exactly.
- The ingredient field must be the unique grocery item name only.
- Do NOT include quantity, unit, package size, metric conversion, or preparation in the ingredient field.
- Examples:
  - "1 egg" -> ingredient "egg"
  - "125 g all-purpose flour" -> ingredient "all-purpose flour"
  - "4 Tablespoons unsalted butter, melted" -> ingredient "unsalted butter", preparation "melted"
  - "1 teaspoon vanilla extract" -> ingredient "vanilla extract"
- If the same grocery item appears more than once because the page lists both US and metric measurements, keep only one ingredient object for that grocery item.
- Assign store_section and store_section_order.
- Do NOT add ingredients that are not in the recipe.

STORE SECTIONS:
PRODUCE, DAIRY, DRY GOODS, CANNED, BEVERAGES, SPICES, OILS, BAKERY, MISC

ORDER:
PRODUCE = 1
DAIRY = 2
DRY GOODS = 3
CANNED = 4
BEVERAGES = 5
SPICES = 6
OILS = 7
BAKERY = 8
MISC = 9

========================
EQUIPMENT RULES
========================
- Extract ALL equipment/tools required to complete the recipe.
- You MUST infer equipment from the instructions when not explicitly listed.

- Common inference examples:
  - "preheat oven" = oven
  - "bake on a sheet pan" = baking sheet
  - "cook in a skillet" = skillet
  - "boil water" = pot
  - "mix in a bowl" = mixing bowl
  - "whisk together" = whisk
  - "cut/chop" = knife, cutting board

- Include cooking tools, prep tools, cookware, and appliances.
- Use simple lowercase names.
- Remove duplicates.
- Do NOT include ingredients as equipment.
- If absolutely no equipment can be inferred, return an empty list [].
- Only include equipment that is actually used in the instructions.
- Always assign category using one of these exact values only: cookware, utensil, appliance, prep.
- Category mapping rules:
  - appliance: oven, microwave, stovetop, blender
  - cookware: skillet, pot, saucepan, baking sheet, dutch oven
  - utensil: whisk, spoon, spatula, tongs
  - prep: knife, cutting board, peeler, grater, mixing bowl

========================
COOKING INSTRUCTION RULES
========================
- Extract ONLY the actual cooking/preparation directions.
- Do NOT include intro text, serving suggestions, storage tips, FAQs, nutrition notes, comments, ads, or unrelated article text.
- Preserve the recipe's step order exactly.
- Each instruction must be one complete action step.
- Do NOT summarize the whole recipe into one paragraph.
- Do NOT invent missing steps.
- If the page has numbered instructions, use those numbers.
- If unnumbered, assign step_number in order starting at 1.
- Keep temperatures, times, pan sizes, ingredient amounts, and doneness cues exactly when present.
- Include prep steps such as chopping, boiling, draining, mixing, resting, baking, cooling, and serving only when they are part of the recipe directions.
- If instructions are split into sections such as "Make the sauce", "Cook the pasta", or "Assemble", preserve that section name.
- If no cooking instructions are found, return an empty list [].
- For each step, include "equipment_used" as a list of equipment names used in that step.

========================
NUTRITION RULES
========================
- Extract nutritional information ONLY if it appears on the recipe page.
- Do NOT calculate, estimate, or invent nutrition values.
- Preserve the displayed value and unit when possible.
- Use null when a value is missing or unknown.
- If the page lists nutrition per serving, set serving_basis to "per serving".
- If the page lists nutrition for the full recipe, set serving_basis to "full recipe".
- If the serving basis is unclear, set serving_basis to null.
- Keep units inside value strings, such as "331 kcal", "15 g", "400 mg", or "20%".
- Put any nutrition item that does not fit the common fields into other.
- If no nutrition information is found, return nutrition with all fields as null and other as [].

========================
FINAL OUTPUT FORMAT
========================
{{
  "source_url": "{recipe_url}",
  "recipe_title": null,
  "servings": null,
  "ingredients": [
    {{
      "section": null,
      "original_text": null,
      "quantity": null,
      "unit": null,
      "ingredient": null,
      "preparation": null,
      "optional": false,
      "store_section": null,
      "store_section_order": null
    }}
  ],
  "equipment": [
    {{
      "name": null,
      "category": null
    }}
  ],
  "instructions": [
    {{
      "section": null,
      "step_number": null,
      "instruction": null,
      "temperature": null,
      "time": null,
      "equipment_used": []
    }}
  ],
  "nutrition": {{
    "serving_basis": null,
    "calories": null,
    "carbohydrates": null,
    "protein": null,
    "fat": null,
    "saturated_fat": null,
    "polyunsaturated_fat": null,
    "monounsaturated_fat": null,
    "trans_fat": null,
    "cholesterol": null,
    "sodium": null,
    "potassium": null,
    "fiber": null,
    "sugar": null,
    "vitamin_a": null,
    "vitamin_c": null,
    "calcium": null,
    "iron": null,
    "other": [
      {{
        "name": null,
        "value": null
      }}
    ]
  }}
}}
"""


def send_prompt_to_openai(prompt_text):
    response = get_openai_client().chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You extract recipe ingredients and return only valid JSON.",
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    return response.choices[0].message.content


def save_json_response(recipe_url, response_text):
    cleaned = clean_json_response(response_text)

    base_name = safe_filename(recipe_url)
    json_path = OUTPUT_FOLDER / f"{base_name}.json"
    raw_path = RAW_FOLDER / f"{base_name}_RAW.txt"

    try:
        json_data = json.loads(cleaned)

        json_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"Saved JSON: {json_path}")

        return True, json_data

    except json.JSONDecodeError as exc:
        raw_path.write_text(response_text, encoding="utf-8")

        print(f"Invalid JSON. Saved raw response: {raw_path}")
        print(f"JSON error: {exc}")

        return False, None


def extract_ingredients_from_result(json_data):
    ingredients = []
    seen = set()

    for item in json_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        value = normalize_ingredient_for_shopping_list(
            item.get("ingredient") or item.get("original_text")
        )

        key = normalize_ingredient_key(value)

        if value and key not in seen:
            ingredients.append(str(value).strip())
            seen.add(key)

    return ingredients


def normalize_ingredient_key(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def normalize_ingredient_for_shopping_list(text):
    value = str(text or "").strip()

    if not value:
        return ""

    value = (
        value.replace("Â", "")
        .replace("Ľ", "¼")
        .replace("˝", "½")
        .replace("ľ", "¾")
        .replace("â…›", "⅛")
    )
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.split(",", 1)[0].strip()

    quantity_pattern = r"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])+"
    unit_pattern = (
        r"(?:cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?)"
    )

    value = re.sub(
        rf"^{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\b\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"^{quantity_pattern}\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"^{unit_pattern}\b\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return re.sub(r"\s+", " ", value).strip()


def extract_recipe_from_url(recipe_url):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {
            "ok": False,
            "error": "Missing recipe URL.",
            "ingredients": [],
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
            "ingredients": [],
        }

    try:
        print("\n==================================================")
        print("Recipe 1/1")
        print(recipe_url)
        print("==================================================")

        page_text = fetch_recipe_page_text(recipe_url)

        if not page_text:
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "No page text found.",
                "ingredients": [],
            }

        prompt_text = build_prompt(recipe_url, page_text)

        print("Sending to OpenAI API...")
        response_text = send_prompt_to_openai(prompt_text)

        raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_API_RESPONSE.txt"
        raw_api_path.write_text(response_text, encoding="utf-8")

        success, json_data = save_json_response(recipe_url, response_text)

        if not success or not json_data:
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "Invalid JSON returned by OpenAI.",
                "ingredients": [],
            }

        time.sleep(REQUEST_DELAY_SECONDS)

        ingredients = extract_ingredients_from_result(json_data)

        return {
            "ok": True,
            "source_url": recipe_url,
            "recipe_title": json_data.get("recipe_title"),
            "servings": json_data.get("servings"),
            "ingredients": ingredients,
            "equipment": json_data.get("equipment", []),
            "instructions": json_data.get("instructions", []),
            "nutrition": json_data.get("nutrition", {}),
            "raw": json_data,
        }

    except Exception as exc:
        return {
            "ok": False,
            "source_url": recipe_url,
            "error": str(exc),
            "ingredients": [],
        }
