import json
import os
import re
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
INGREDIENT_STORE_SECTIONS = {
    "produce": "PRODUCE",
    "beef": "MEAT & SEAFOOD",
    "chicken": "MEAT & SEAFOOD",
    "pork": "MEAT & SEAFOOD",
    "turkey": "MEAT & SEAFOOD",
    "fish": "MEAT & SEAFOOD",
    "shrimp": "MEAT & SEAFOOD",
    "salmon": "MEAT & SEAFOOD",
    "egg": "DAIRY & EGGS",
    "milk": "DAIRY & EGGS",
    "butter": "DAIRY & EGGS",
    "yogurt": "DAIRY & EGGS",
    "cream": "DAIRY & EGGS",
    "cheese": "DAIRY & EGGS",
    "ricotta": "DAIRY & EGGS",
    "parmesan": "DAIRY & EGGS",
    "flour": "BAKING",
    "sugar": "BAKING",
    "yeast": "BAKING",
    "baking powder": "BAKING",
    "baking soda": "BAKING",
    "chocolate chips": "BAKING",
    "vanilla extract": "BAKING",
    "salt": "SPICES & SEASONINGS",
    "pepper": "SPICES & SEASONINGS",
    "cinnamon": "SPICES & SEASONINGS",
    "nutmeg": "SPICES & SEASONINGS",
    "paprika": "SPICES & SEASONINGS",
    "cumin": "SPICES & SEASONINGS",
    "oil": "OILS & VINEGARS",
    "vinegar": "OILS & VINEGARS",
    "pasta": "PASTA, RICE & GRAINS",
    "rice": "PASTA, RICE & GRAINS",
    "oats": "PASTA, RICE & GRAINS",
    "quinoa": "PASTA, RICE & GRAINS",
    "breadcrumbs": "PASTA, RICE & GRAINS",
    "sauce": "SAUCES & CONDIMENTS",
    "ketchup": "SAUCES & CONDIMENTS",
    "mustard": "SAUCES & CONDIMENTS",
}
STORE_SECTION_ORDER = {
    "PRODUCE": 1,
    "MEAT & SEAFOOD": 2,
    "DAIRY & EGGS": 3,
    "FROZEN": 4,
    "DRY GOODS": 5,
    "PASTA, RICE & GRAINS": 6,
    "BAKING": 7,
    "CANNED": 8,
    "SAUCES & CONDIMENTS": 9,
    "SNACKS": 10,
    "BEVERAGES": 11,
    "SPICES & SEASONINGS": 12,
    "OILS & VINEGARS": 13,
    "BAKERY": 14,
    "DELI": 15,
    "HOUSEHOLD": 16,
    "PERSONAL CARE": 17,
    "PET SUPPLIES": 18,
    "MISC": 19,
}

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


def extract_recipe_from_structured_data(recipe_url, html_text):
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(tag.get_text(strip=True))
        except Exception:
            continue

        recipe = find_recipe_node(payload)

        if not recipe:
            continue

        ingredients = build_structured_ingredients(recipe.get("recipeIngredient", []))

        if not ingredients:
            continue

        json_data = {
            "source_url": recipe_url,
            "recipe_title": recipe.get("name"),
            "servings": normalize_servings(recipe.get("recipeYield")),
            "ingredients": ingredients,
            "equipment": [],
            "instructions": build_structured_instructions(recipe.get("recipeInstructions", [])),
            "nutrition": build_structured_nutrition(recipe.get("nutrition", {})),
        }

        return json_data

    return None


def find_recipe_node(payload):
    if isinstance(payload, dict):
        if node_has_recipe_type(payload):
            return payload

        graph = payload.get("@graph", [])

        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, dict) and node_has_recipe_type(node):
                    return node

    if isinstance(payload, list):
        for node in payload:
            recipe = find_recipe_node(node)

            if recipe:
                return recipe

    return None


def node_has_recipe_type(node):
    node_type = node.get("@type")

    if isinstance(node_type, list):
        return "Recipe" in node_type

    return node_type == "Recipe"


def normalize_servings(recipe_yield):
    if isinstance(recipe_yield, list):
        return recipe_yield[0] if recipe_yield else None

    return recipe_yield


def build_structured_ingredients(raw_ingredients):
    ingredient_rows = []
    seen = set()

    for original_text in raw_ingredients or []:
        original_text = str(original_text or "").strip()
        ingredient = normalize_ingredient_for_shopping_list(original_text)
        key = normalize_ingredient_key(ingredient)

        if not ingredient or key in seen:
            continue

        store_section = classify_store_section(ingredient)
        ingredient_rows.append({
            "section": None,
            "original_text": original_text,
            "quantity": None,
            "unit": None,
            "ingredient": ingredient,
            "preparation": extract_preparation(original_text),
            "optional": "optional" in original_text.lower(),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER[store_section],
        })
        seen.add(key)

    return ingredient_rows


def classify_store_section(ingredient):
    normalized = normalize_ingredient_key(ingredient)

    for keyword, section in INGREDIENT_STORE_SECTIONS.items():
        if keyword in normalized:
            return section

    produce_words = (
        "basil",
        "lemon",
        "zest",
        "onion",
        "garlic",
        "tomato",
        "spinach",
        "parsley",
        "cilantro",
    )

    if any(word in normalized for word in produce_words):
        return "PRODUCE"

    return "MISC"


def extract_preparation(original_text):
    if "," in original_text:
        return original_text.split(",", 1)[1].strip() or None

    return None


def build_structured_instructions(raw_instructions):
    flattened = flatten_instruction_nodes(raw_instructions)
    instructions = []

    for index, instruction in enumerate(flattened, start=1):
        instruction = str(instruction or "").strip()

        if instruction:
            instructions.append({
                "section": None,
                "step_number": index,
                "instruction": instruction,
                "temperature": None,
                "time": None,
                "equipment_used": [],
            })

    return instructions


def flatten_instruction_nodes(raw_instructions):
    if isinstance(raw_instructions, str):
        return [raw_instructions]

    if not isinstance(raw_instructions, list):
        return []

    instructions = []

    for item in raw_instructions:
        if isinstance(item, str):
            instructions.append(item)
        elif isinstance(item, dict):
            if item.get("@type") == "HowToSection":
                instructions.extend(flatten_instruction_nodes(item.get("itemListElement", [])))
            else:
                text = item.get("text") or item.get("name")
                if text:
                    instructions.append(text)

    return instructions


def build_structured_nutrition(nutrition):
    nutrition = nutrition or {}

    return {
        "serving_basis": "per serving" if nutrition.get("servingSize") else None,
        "calories": nutrition.get("calories"),
        "carbohydrates": nutrition.get("carbohydrateContent"),
        "protein": nutrition.get("proteinContent"),
        "fat": nutrition.get("fatContent"),
        "saturated_fat": nutrition.get("saturatedFatContent"),
        "polyunsaturated_fat": nutrition.get("polyunsaturatedFatContent"),
        "monounsaturated_fat": nutrition.get("monounsaturatedFatContent"),
        "trans_fat": nutrition.get("transFatContent"),
        "cholesterol": nutrition.get("cholesterolContent"),
        "sodium": nutrition.get("sodiumContent"),
        "potassium": nutrition.get("potassiumContent"),
        "fiber": nutrition.get("fiberContent"),
        "sugar": nutrition.get("sugarContent"),
        "vitamin_a": nutrition.get("vitaminAContent"),
        "vitamin_c": nutrition.get("vitaminCContent"),
        "calcium": nutrition.get("calciumContent"),
        "iron": nutrition.get("ironContent"),
        "other": [],
    }


def fetch_recipe_page(recipe_url):
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

    return response.text, page_text


def fetch_recipe_page_text(recipe_url):
    _, page_text = fetch_recipe_page(recipe_url)
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
- Use the grocery section that best matches the ingredient's real grocery store placement.
- Do NOT add ingredients that are not in the recipe.

CLASSIFICATION GUIDANCE:
- Eggs, milk, butter, yogurt, cream, cheese, and sour cream go in DAIRY & EGGS.
- Flour, sugar, brown sugar, powdered sugar, baking powder, baking soda, cocoa powder, chocolate chips, vanilla extract, and yeast go in BAKING.
- Salt, kosher salt, sea salt, black pepper, cinnamon, paprika, cumin, chili powder, garlic powder, onion powder, oregano, thyme, basil, and spice blends go in SPICES & SEASONINGS.
- Olive oil, vegetable oil, avocado oil, sesame oil, coconut oil, cooking spray, and vinegars go in OILS & VINEGARS.
- Pasta, noodles, rice, oats, quinoa, breadcrumbs, stuffing mix, and grains go in PASTA, RICE & GRAINS.
- Ketchup, mustard, mayonnaise, salsa, soy sauce, hot sauce, barbecue sauce, salad dressing, and marinades go in SAUCES & CONDIMENTS.
- Bread, buns, tortillas, bagels, rolls, croissants, and pastries go in BAKERY.
- Chips, crackers, popcorn, pretzels, granola bars, and cookies go in SNACKS.
- Frozen vegetables, frozen fruit, ice cream, frozen pizza, and frozen meals go in FROZEN.
- Fresh fruits, vegetables, herbs, and refrigerated produce go in PRODUCE.

STORE SECTIONS:
PRODUCE, MEAT & SEAFOOD, DAIRY & EGGS, FROZEN, DRY GOODS, PASTA, RICE & GRAINS, BAKING, CANNED, SAUCES & CONDIMENTS, SNACKS, BEVERAGES, SPICES & SEASONINGS, OILS & VINEGARS, BAKERY, DELI, HOUSEHOLD, PERSONAL CARE, PET SUPPLIES, MISC

ORDER:
PRODUCE = 1
MEAT & SEAFOOD = 2
DAIRY & EGGS = 3
FROZEN = 4
DRY GOODS = 5
PASTA, RICE & GRAINS = 6
BAKING = 7
CANNED = 8
SAUCES & CONDIMENTS = 9
SNACKS = 10
BEVERAGES = 11
SPICES & SEASONINGS = 12
OILS & VINEGARS = 13
BAKERY = 14
DELI = 15
HOUSEHOLD = 16
PERSONAL CARE = 17
PET SUPPLIES = 18
MISC = 19

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

    try:
        print("\n==================================================")
        print("Recipe 1/1")
        print(recipe_url)
        print("==================================================")

        html_text, page_text = fetch_recipe_page(recipe_url)

        if not page_text:
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "No page text found.",
                "ingredients": [],
            }

        structured_json_data = extract_recipe_from_structured_data(recipe_url, html_text)

        if structured_json_data:
            json_path = OUTPUT_FOLDER / f"{safe_filename(recipe_url)}.json"
            json_path.write_text(
                json.dumps(structured_json_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            ingredients = extract_ingredients_from_result(structured_json_data)

            return {
                "ok": True,
                "source_url": recipe_url,
                "recipe_title": structured_json_data.get("recipe_title"),
                "servings": structured_json_data.get("servings"),
                "ingredients": ingredients,
                "equipment": structured_json_data.get("equipment", []),
                "instructions": structured_json_data.get("instructions", []),
                "nutrition": structured_json_data.get("nutrition", {}),
                "raw": structured_json_data,
                "extraction_method": "structured_data",
            }

        if not os.getenv("OPENAI_API_KEY"):
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "Missing OPENAI_API_KEY environment variable.",
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
            "extraction_method": "openai",
        }

    except Exception as exc:
        return {
            "ok": False,
            "source_url": recipe_url,
            "error": str(exc),
            "ingredients": [],
        }
