import json
import os
import re
import html
import base64
import mimetypes
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

EXTRACTOR_FOLDER = Path(__file__).resolve().parent / "recipe-extractor"
OUTPUT_FOLDER = EXTRACTOR_FOLDER / "data" / "output"
RAW_FOLDER = EXTRACTOR_FOLDER / "data" / "raw"
LOG_FOLDER = EXTRACTOR_FOLDER / "data" / "logs"
UPLOAD_FOLDER = EXTRACTOR_FOLDER / "data" / "uploads"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
RAW_FOLDER.mkdir(parents=True, exist_ok=True)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

MODEL = os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini")
MAX_PAGE_TEXT_CHARS = 35000
OPENAI_FILE_INPUT_MIME_TYPES = {
    "application/pdf",
}
INGREDIENT_STORE_SECTIONS = {
    "produce": "PRODUCE",
    "beef": "MEAT & SEAFOOD",
    "chicken": "MEAT & SEAFOOD",
    "pork": "MEAT & SEAFOOD",
    "turkey": "MEAT & SEAFOOD",
    "fish": "MEAT & SEAFOOD",
    "shrimp": "MEAT & SEAFOOD",
    "salmon": "MEAT & SEAFOOD",
    "frozen": "FROZEN",
    "frozen peas": "FROZEN",
    "frozen raspberries": "FROZEN",
    "egg": "DAIRY & EGGS",
    "eggs": "DAIRY & EGGS",
    "yolk": "DAIRY & EGGS",
    "yolks": "DAIRY & EGGS",
    "milk": "DAIRY & EGGS",
    "butter": "DAIRY & EGGS",
    "yogurt": "DAIRY & EGGS",
    "cream": "DAIRY & EGGS",
    "cheese": "DAIRY & EGGS",
    "ricotta": "DAIRY & EGGS",
    "parmesan": "DAIRY & EGGS",
    "asparagus": "PRODUCE",
    "lemon": "PRODUCE",
    "garlic": "PRODUCE",
    "onion": "PRODUCE",
    "basil": "PRODUCE",
    "flour": "BAKING",
    "sugar": "BAKING",
    "confectioners sugar": "BAKING",
    "confectioners' sugar": "BAKING",
    "powdered sugar": "BAKING",
    "yeast": "BAKING",
    "baking powder": "BAKING",
    "baking soda": "BAKING",
    "chocolate chips": "BAKING",
    "chocolate": "BAKING",
    "cocoa powder": "BAKING",
    "dutch-processed cocoa powder": "BAKING",
    "cocoa butter": "BAKING",
    "corn syrup": "BAKING",
    "vanilla extract": "BAKING",
    "salt": "SPICES & SEASONINGS",
    "pepper": "SPICES & SEASONINGS",
    "cinnamon": "SPICES & SEASONINGS",
    "nutmeg": "SPICES & SEASONINGS",
    "paprika": "SPICES & SEASONINGS",
    "cumin": "SPICES & SEASONINGS",
    "oil": "OILS & VINEGARS",
    "vinegar": "OILS & VINEGARS",
    "clarified butter": "DAIRY & EGGS",
    "pasta": "PASTA, RICE & GRAINS",
    "pasta dough": "PASTA, RICE & GRAINS",
    "fresh pasta dough": "PASTA, RICE & GRAINS",
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
FRACTION_CHARS = "\u00bc\u00bd\u00be\u2150\u2151\u2152\u2153\u2154\u2155\u2156\u2157\u2158\u2159\u215a\u215b\u215c\u215d\u215e"
EQUIPMENT_INFERENCE_RULES = [
    ("oven", "appliance", [r"\bpreheat\b", r"\boven\b", r"\bbake\b"]),
    ("muffin tin", "cookware", [r"\bmuffin tins?\b", r"\bmuffin pans?\b", r"\bmuffin cups?\b"]),
    ("baking sheet", "cookware", [r"\bbaking sheets?\b", r"\bsheet pans?\b"]),
    ("mixing bowl", "prep", [r"\blarge bowl\b", r"\bmedium bowl\b", r"\bmixing bowl\b", r"\bin a bowl\b"]),
    ("whisk", "utensil", [r"\bwhisk\b"]),
    ("spatula", "utensil", [r"\bfold\b", r"\bspatula\b"]),
    ("cookie scoop", "utensil", [r"\bcookie scoop\b", r"\bscoop batter\b"]),
    ("wire rack", "prep", [r"\bwire rack\b"]),
    ("pot", "cookware", [r"\bboil\b", r"\bpot\b", r"\bpasta water\b"]),
    ("saucepan", "cookware", [r"\bsaucepan\b"]),
    ("skillet", "cookware", [r"\bskillet\b", r"\bfrying pan\b"]),
    ("knife", "prep", [r"\bcut\b", r"\bchop\b", r"\bslice\b", r"\bmince\b"]),
    ("cutting board", "prep", [r"\bcut\b", r"\bchop\b", r"\bslice\b", r"\bmince\b"]),
    ("rolling pin", "prep", [r"\broll(?:ed|ing)?\b", r"\brolling pin\b"]),
    ("pasta machine", "prep", [r"\bpasta machine\b", r"\bpasta roller\b", r"\bsetting\b"]),
    ("ravioli cutter", "prep", [r"\bravioli cutter\b", r"\bcut.*ravioli\b"]),
]
EQUIPMENT_PATTERNS_BY_NAME = {
    name: patterns
    for name, _category, patterns in EQUIPMENT_INFERENCE_RULES
}

client = None


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45)

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

        instructions = build_structured_instructions(recipe.get("recipeInstructions", []))
        equipment = infer_equipment_from_instructions(instructions)
        add_equipment_used_to_instructions(instructions, equipment)

        json_data = {
            "source_url": recipe_url,
            "recipe_title": recipe.get("name"),
            "servings": normalize_servings(recipe.get("recipeYield")),
            "ingredients": ingredients,
            "equipment": equipment,
            "instructions": instructions,
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
        parsed = parse_structured_ingredient_line(original_text)
        ingredient = parsed["ingredient"]
        key = normalize_ingredient_key(ingredient)

        if not ingredient or key in seen:
            continue

        store_section = classify_store_section(ingredient)
        ingredient_rows.append({
            "section": None,
            "original_text": original_text,
            "quantity": parsed["quantity"],
            "unit": parsed["unit"],
            "ingredient": ingredient,
            "preparation": parsed["preparation"],
            "optional": "optional" in original_text.lower(),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER[store_section],
        })
        seen.add(key)

    return ingredient_rows


def parse_structured_ingredient_line(original_text):
    text = clean_recipe_text(original_text)
    preparation = extract_preparation(text)
    text_without_prep = remove_preparation_text(text, preparation)
    quantity, unit, remainder = split_quantity_unit(text_without_prep)
    ingredient = normalize_ingredient_for_shopping_list(remainder or text_without_prep)

    return {
        "quantity": quantity,
        "unit": unit,
        "ingredient": ingredient,
        "preparation": preparation,
    }


def split_quantity_unit(text):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = re.sub(r"\s*[-–—]\s*", "-", text)

    fraction_pattern = f"[{FRACTION_CHARS}]"
    quantity_value_pattern = rf"(?:\d+\s+\d+/\d+|\d+(?:[./]\d+)?|{fraction_pattern})"
    quantity_pattern = rf"{quantity_value_pattern}(?:\s*(?:-|to)\s*{quantity_value_pattern})?"
    unit_pattern = (
        r"cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?"
    )

    match = re.match(
        rf"^(?P<quantity>{quantity_pattern})(?:\s+(?P<unit>{unit_pattern}))?\s+(?P<ingredient>.+)$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        unit_first_match = re.match(
            rf"^(?P<unit>{unit_pattern})\s+(?P<ingredient>.+)$",
            text,
            flags=re.IGNORECASE,
        )

        if unit_first_match:
            return (
                "1",
                unit_first_match.group("unit").strip(),
                unit_first_match.group("ingredient").strip(),
            )

    if not match:
        return None, None, text

    unit = match.group("unit")

    return (
        match.group("quantity").strip(),
        unit.strip() if unit else None,
        match.group("ingredient").strip(),
    )


def remove_preparation_text(text, preparation):
    if not preparation:
        return text

    text = re.sub(r"\([^)]*\)", " ", text)

    if "," in text:
        text = text.split(",", 1)[0]

    for phrase in str(preparation or "").split(","):
        phrase = phrase.strip()

        if phrase:
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.IGNORECASE)

    return re.sub(r"\s+", " ", text).strip()


def classify_store_section(ingredient):
    normalized = normalize_ingredient_key(ingredient)
    normalized = normalized.replace("*", "")

    priority_keywords = (
        ("fresh pasta dough", "PASTA, RICE & GRAINS"),
        ("pasta dough", "PASTA, RICE & GRAINS"),
        ("cocoa butter", "BAKING"),
        ("cocoa powder", "BAKING"),
        ("dutch-processed cocoa powder", "BAKING"),
        ("semisweet chocolate", "BAKING"),
        ("chocolate", "BAKING"),
        ("corn syrup", "BAKING"),
        ("confectioners' sugar", "BAKING"),
        ("confectioners sugar", "BAKING"),
        ("powdered sugar", "BAKING"),
        ("salt and pepper", "SPICES & SEASONINGS"),
        ("tomato sauce", "SAUCES & CONDIMENTS"),
        ("clarified butter", "DAIRY & EGGS"),
        ("yolk", "DAIRY & EGGS"),
    )

    for keyword, section in priority_keywords:
        if keyword in normalized:
            return section

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
    text = clean_recipe_text(original_text)
    usage_modifiers = [
        "to taste",
        "as desired",
        "for garnish",
        "for garnishing",
        "for serving",
    ]
    lowered = text.lower()
    matched_modifiers = [
        modifier
        for modifier in usage_modifiers
        if re.search(rf"\b{re.escape(modifier)}\b", lowered)
    ]

    parenthetical_matches = [
        match.strip()
        for match in re.findall(r"\(([^)]*)\)", text)
        if match.strip() and not re.search(r"\d", match)
    ]

    preparation_parts = []
    preparation_parts.extend(matched_modifiers)
    preparation_parts.extend(parenthetical_matches)

    if "," in text:
        comma_tail = text.split(",", 1)[1].strip()

        if not comma_tail.lower().startswith("or "):
            preparation_parts.append(comma_tail)

    if preparation_parts:
        return clean_preparation_text(", ".join(preparation_parts))

    return None


def clean_preparation_text(text):
    value = clean_recipe_text(text).lower()
    replacements = {
        "mleted": "melted",
    }

    for bad_value, good_value in replacements.items():
        value = value.replace(bad_value, good_value)

    parts = []
    seen = set()

    for part in value.split(","):
        part = part.strip()

        if part and part not in seen:
            parts.append(part)
            seen.add(part)

    return ", ".join(parts).strip() or None


def clean_recipe_text(text):
    value = html.unescape(str(text or ""))
    replacements = {
        "Â¼": "¼",
        "Â½": "½",
        "Â¾": "¾",
        "â…": "⅐",
        "â…‘": "⅑",
        "â…’": "⅒",
        "â…“": "⅓",
        "â…”": "⅔",
        "â…•": "⅕",
        "â…–": "⅖",
        "â…—": "⅗",
        "â…˜": "⅘",
        "â…™": "⅙",
        "â…š": "⅚",
        "â…›": "⅛",
        "â…œ": "⅜",
        "â…": "⅝",
        "â…ž": "⅞",
    }

    for bad_value, good_value in replacements.items():
        value = value.replace(bad_value, good_value)

    return re.sub(r"\s+", " ", value).strip()


def build_structured_instructions(raw_instructions):
    flattened = flatten_instruction_nodes(raw_instructions)
    instructions = []

    for index, instruction in enumerate(flattened, start=1):
        instruction = clean_recipe_text(instruction)

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


def infer_equipment_from_instructions(instructions):
    inferred = {}

    for step in instructions or []:
        instruction = step.get("instruction", "") if isinstance(step, dict) else str(step or "")
        for equipment_name, category, patterns in EQUIPMENT_INFERENCE_RULES:
            if any(re.search(pattern, instruction, flags=re.IGNORECASE) for pattern in patterns):
                inferred[equipment_name] = {
                    "name": equipment_name,
                    "category": category,
                }

    return [
        inferred[name]
        for name in sorted(inferred)
    ]


def add_equipment_used_to_instructions(instructions, equipment):
    equipment_names = [item["name"] for item in equipment if isinstance(item, dict)]

    for step in instructions or []:
        if not isinstance(step, dict):
            continue

        instruction = step.get("instruction", "")
        used = []

        for equipment_name in equipment_names:
            patterns = EQUIPMENT_PATTERNS_BY_NAME.get(equipment_name, [])
            if any(re.search(pattern, instruction, flags=re.IGNORECASE) for pattern in patterns):
                used.append(equipment_name)

        step["equipment_used"] = used


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


def fetch_recipe_page(recipe_url, progress_callback=None):
    print(f"Fetching recipe page: {recipe_url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }

    html_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_HTML.html"

    try:
        response = requests.get(recipe_url, headers=headers, timeout=(8, 15))
        response.raise_for_status()
        html_text = response.text
        html_path.write_text(html_text, encoding="utf-8")
    except Exception as exc:
        if is_forbidden_response(exc) and os.getenv("DISABLE_BROWSER_RECIPE_FETCH") != "1":
            if progress_callback:
                progress_callback(
                    "website blocked direct download - trying browser fetch...",
                    "The site returned 403, so Chrome is opening the page to grab the HTML.",
                )

            try:
                html_text = fetch_recipe_page_with_browser(recipe_url)
                html_path.write_text(html_text, encoding="utf-8")
            except Exception as browser_exc:
                if html_path.exists() and os.getenv("DISABLE_RECIPE_HTML_CACHE_FALLBACK") != "1":
                    print(f"Browser fetch failed; using cached HTML: {html_path}")
                    html_text = html_path.read_text(encoding="utf-8")
                else:
                    raise RuntimeError(
                        "Website blocked automated download with 403 Forbidden, "
                        f"and browser fallback failed: {browser_exc}"
                    ) from browser_exc
        elif html_path.exists() and os.getenv("DISABLE_RECIPE_HTML_CACHE_FALLBACK") != "1":
            print(f"Live fetch failed; using cached HTML: {html_path}")
            html_text = html_path.read_text(encoding="utf-8")
        else:
            raise

    if progress_callback:
        progress_callback(
            "HTML downloaded - reading recipe card data...",
            "Reading structured recipe data from the webpage HTML.",
        )

    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    page_text = soup.get_text(" ", strip=True)
    page_text = re.sub(r"\s+", " ", page_text).strip()

    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    raw_page_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_TEXT.txt"
    raw_page_path.write_text(page_text, encoding="utf-8")

    print(f"Loaded webpage text: {len(page_text)} characters")

    return html_text, page_text


def is_forbidden_response(exc):
    response = getattr(exc, "response", None)
    return response is not None and response.status_code == 403


def fetch_recipe_page_with_browser(recipe_url):
    driver = None

    try:
        try:
            import undetected_chromedriver as uc

            options = uc.ChromeOptions()
            options.page_load_strategy = "eager"
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1365,900")
            driver = uc.Chrome(options=options, use_subprocess=True)
        except Exception:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            options = Options()
            options.page_load_strategy = "eager"
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1365,900")
            driver = webdriver.Chrome(options=options)

        driver.set_page_load_timeout(18)

        try:
            driver.get(recipe_url)
        except Exception:
            html_text = driver.page_source or ""

            if len(html_text) > 1000:
                print("Browser fetch timed out after partial page load; using current HTML.")
                return html_text

            raise

        return driver.page_source or ""
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


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
- ALWAYS split ingredients into: quantity, unit, ingredient, preparation.
- quantity and unit should only be null when truly absent from the recipe text.
- Preserve original_text exactly.
- Before returning JSON, re-read every original_text and verify quantity, unit, ingredient, and preparation are split correctly.
- If original_text starts with a number, fraction, mixed fraction, or range, quantity must not be null.
- If original_text has a measurement word immediately after the quantity, unit must not be null.
- If original_text has text after a comma or a non-metric parenthetical such as "(melted)", "(chopped)", "(divided)", or "(room temperature)", preparation must not be null.
- The ingredient field must be the unique grocery item name only.
- Do NOT include quantity, unit, package size, metric conversion, or preparation in the ingredient field.
- Do NOT include words like "divided", "chopped", "melted", "shredded", "to taste", "as desired", "for garnish", or "optional" in the ingredient field.
- Put preparation words in preparation.
- If an ingredient is optional, set optional = true.
- "pinch" and "pinches" are measurement units. Put them in unit, not ingredient.

- Preserve recipe usage modifiers in preparation:
  - "divided"
  - "room temperature"
  - "softened"
  - "cold"
  - "drained"
  - "rinsed"
  - "to taste"
  - "as desired"
  - "for garnish"

INGREDIENT CONFIDENCE RULES:
- Only extract ingredients that are explicitly present in the recipe.
- Do NOT infer missing ingredients from general cooking knowledge.
- Do NOT add water, oil, salt, or pepper unless explicitly mentioned.
- If uncertain whether something is an ingredient or instruction text, exclude it.

IMPORTANT QUANTITY EXTRACTION RULES:
- ALWAYS attempt to extract quantity and unit.
- Do this for EVERY ingredient object, using original_text as the source of truth.
- If ingredient quantities appear anywhere in the page, including ingredient lists, instruction steps, notes, fillings, sauces, dough sections, headings, or recipe cards, extract them.
- NEVER discard quantities when they are present.
- Preserve fractional values exactly as strings.
- Preserve ranges exactly as strings.
- Preserve package sizes.

ALTERNATIVE INGREDIENT RULES:
- If one ingredient line gives a choice using "or", keep it as ONE ingredient object when the alternatives are substitutes for each other.
- Do NOT put the second alternative's quantity or unit inside the ingredient name.
- The ingredient field should contain only the alternative grocery item names joined by " OR ".
- If the alternatives have different quantities or units, put the complete quantity choices in quantity and set unit to null.
- Preserve the full original line in original_text.
- Assign the store_section for the best primary grocery placement.

Examples:
- "1 egg"
  -> quantity = "1"
  -> unit = null
  -> ingredient = "egg"

- "125 g all-purpose flour"
  -> quantity = "125"
  -> unit = "g"
  -> ingredient = "all-purpose flour"

- "4 Tablespoons unsalted butter, melted"
  -> quantity = "4"
  -> unit = "Tablespoons"
  -> ingredient = "unsalted butter"
  -> preparation = "melted"

- "1 teaspoon vanilla extract"
  -> quantity = "1"
  -> unit = "teaspoon"
  -> ingredient = "vanilla extract"

- "salt and pepper to taste"
  -> quantity = null
  -> unit = null
  -> ingredient = "salt"
  -> preparation = "to taste"

- "Pinch ground nutmeg"
  -> quantity = "1"
  -> unit = "Pinch"
  -> ingredient = "ground nutmeg"
  -> preparation = null

- "Salt and pepper to taste (as desired)"
  -> quantity = null
  -> unit = null
  -> ingredient = "Salt and pepper"
  -> preparation = "to taste, as desired"

- "Parmesan and/or basil, for garnish"
  -> quantity = null
  -> unit = null
  -> ingredient = "Parmesan and/or basil"
  -> preparation = "for garnish"

- "Homemade Tomato Sauce, or sauce as desired, for serving"
  -> quantity = null
  -> unit = null
  -> ingredient = "Homemade Tomato Sauce"
  -> preparation = "or sauce as desired, for serving"

- "2 ounces cocoa butter or 1/4 cup vegetable oil"
  -> quantity = "2 ounces OR 1/4 cup"
  -> unit = null
  -> ingredient = "cocoa butter OR vegetable oil"
  -> preparation = null

- "1 cup butter or coconut oil, melted"
  -> quantity = "1"
  -> unit = "cup"
  -> ingredient = "butter OR coconut oil"
  -> preparation = "melted"

- If the webpage only contains instructions and no formal ingredient list:
  - infer ingredients from cooking steps
  - still extract quantities whenever they appear in the instructions

- If the same grocery item appears more than once because the page lists both US and metric measurements, keep only one ingredient object for that grocery item.
- Assign store_section and store_section_order.
- Use the grocery section that best matches the ingredient's real grocery store placement.
- Do NOT add ingredients that are not in the recipe.
- Combine duplicate ingredients when they clearly refer to the same grocery item.
- Keep the most complete quantity and preparation information.
- Do NOT create separate entries for metric conversions of the same ingredient.

- Convert unicode fractions into standard fraction strings:
  - "½" -> "1/2"
  - "¼" -> "1/4"
  - "¾" -> "3/4"

- Preserve mixed fractions exactly:
  - "1 1/2"
  - "2 3/4"

- Preserve quantity ranges exactly:
  - "2-4"
  - "3 to 5"

- If multiple units are shown for the same ingredient:
  - prefer the primary US measurement
  - ignore duplicate metric conversions when they refer to the same ingredient

FINAL INGREDIENT VALIDATION CHECK:
- For every item in ingredients:
  - Check original_text again.
  - If original_text = "1 egg", output quantity "1", unit null, ingredient "egg".
  - If original_text = "¼ cup plain yogurt", output quantity "1/4", unit "cup", ingredient "plain yogurt".
  - If original_text = "4 Tablespoons unsalted butter, melted", output quantity "4", unit "Tablespoons", ingredient "unsalted butter", preparation "melted".
  - If original_text = "4 Tablespoons unsalted butter (melted)", output quantity "4", unit "Tablespoons", ingredient "unsalted butter", preparation "melted".
  - If original_text = "2 ounces cocoa butter or 1/4 cup vegetable oil", output quantity "2 ounces OR 1/4 cup", unit null, ingredient "cocoa butter OR vegetable oil".
  - If any of these fields can be read from original_text, do not leave them null.

NORMALIZATION RULES:
- Singularize grocery ingredient names when appropriate.
  - "eggs" -> "egg"
  - "lemons" -> "lemon"
  - "limes" -> "lime"
  - "onions" -> "onion"
  - "tomatoes" -> "tomato"
  - "potatoes" -> "potato"
  - "carrots" -> "carrot"
- Apply singularization before duplicate detection so singular and plural forms do not both appear.

- Preserve branded or compound ingredient names exactly:
  - "cream of mushroom soup"
  - "soy sauce"
  - "olive oil"

- Do NOT over-normalize ingredient names.

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
- Before returning JSON, re-read every instruction and verify equipment includes all tools implied by the steps.
- Do not leave equipment empty when the instructions mention baking, boiling, mixing, whisking, cutting, rolling, draining, or cooling.

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

INSTRUCTION DEDUPE RULES:
- Remove duplicate instruction steps.
- Prefer the cleanest and most complete version of repeated instructions.
- Preserve original recipe order.

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


def send_image_prompt_to_openai(prompt_text, image_path, mime_type):
    image_bytes = image_path.read_bytes()
    image_data = base64.b64encode(image_bytes).decode("ascii")

    response = get_openai_client().chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You extract recipe ingredients from recipe photos and documents and return only valid JSON.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}",
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    return response.choices[0].message.content


def send_file_prompt_to_openai(prompt_text, file_path, mime_type, filename):
    file_bytes = file_path.read_bytes()
    file_data = base64.b64encode(file_bytes).decode("ascii")

    response = get_openai_client().chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You extract recipe ingredients from recipe photos and documents and return only valid JSON.",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": f"data:{mime_type};base64,{file_data}",
                        },
                    },
                    {"type": "text", "text": prompt_text},
                ],
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
        normalize_extracted_ingredient_fields(json_data)
        normalize_extracted_equipment_fields(json_data)

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


def normalize_extracted_ingredient_fields(json_data):
    for item in json_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        original_text = item.get("original_text") or ""

        if not original_text:
            continue

        parsed = parse_structured_ingredient_line(original_text)

        if parsed["quantity"] and not item.get("quantity"):
            item["quantity"] = parsed["quantity"]

        if parsed["unit"] and not item.get("unit"):
            item["unit"] = parsed["unit"]

        if parsed["preparation"] and not item.get("preparation"):
            item["preparation"] = parsed["preparation"]

        if parsed["ingredient"]:
            current_ingredient = normalize_ingredient_for_shopping_list(
                item.get("ingredient") or original_text
            )

            if not current_ingredient or current_ingredient == normalize_ingredient_for_shopping_list(original_text):
                item["ingredient"] = parsed["ingredient"]


def normalize_extracted_equipment_fields(json_data):
    instructions = json_data.get("instructions", [])

    if not isinstance(instructions, list):
        return

    existing_equipment = json_data.get("equipment", [])

    if not existing_equipment:
        json_data["equipment"] = infer_equipment_from_instructions(instructions)

    add_equipment_used_to_instructions(instructions, json_data.get("equipment", []))


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


def structured_recipe_data_is_usable(json_data):
    if not isinstance(json_data, dict):
        return False

    return bool(json_data.get("ingredients")) and bool(json_data.get("instructions"))


def save_extracted_recipe_json(recipe_url, json_data):
    json_path = OUTPUT_FOLDER / f"{safe_filename(recipe_url)}.json"
    json_path.write_text(
        json.dumps(json_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


def extract_recipe_from_upload(file_storage):
    filename = Path(file_storage.filename or "uploaded-recipe").name
    safe_name = f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    upload_path = UPLOAD_FOLDER / safe_name
    file_storage.save(upload_path)

    recipe_url = f"uploaded://{safe_name}"
    mime_type = (
        file_storage.mimetype
        or mimetypes.guess_type(str(upload_path))[0]
        or "application/octet-stream"
    )
    mime_type = normalize_upload_mime_type(mime_type, filename, upload_path)
    page_text = ""

    try:
        if mime_type.startswith("image/"):
            prompt_text = build_upload_prompt(recipe_url, filename)
            response_text = send_image_prompt_to_openai(prompt_text, upload_path, mime_type)
        elif mime_type.startswith("text/") or upload_path.suffix.lower() in {".txt", ".md"}:
            page_text = upload_path.read_text(encoding="utf-8", errors="ignore")
            prompt_text = build_prompt(recipe_url, page_text[:MAX_PAGE_TEXT_CHARS])
            response_text = send_prompt_to_openai(prompt_text)
        elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
            prompt_text = build_upload_prompt(recipe_url, filename)
            response_text = send_file_prompt_to_openai(prompt_text, upload_path, mime_type, filename)
        else:
            page_text = extract_text_from_generic_document(upload_path)

            if not page_text.strip():
                return {
                    "ok": False,
                    "error": "No readable recipe text was found in that file. Try a photo, PDF, Word document, or text-based recipe file.",
                }

            prompt_text = build_prompt(recipe_url, page_text[:MAX_PAGE_TEXT_CHARS])
            response_text = send_prompt_to_openai(prompt_text)

        ok, json_data = save_json_response(recipe_url, response_text)

        if not ok or not json_data:
            return {
                "ok": False,
                "error": "The uploaded recipe could not be parsed into recipe JSON.",
            }

        json_data["source_url"] = recipe_url
        title = determine_upload_recipe_title(
            recipe_url,
            upload_path,
            mime_type,
            filename,
            page_text,
        )
        if title:
            json_data["recipe_title"] = title
        merge_missing_upload_ingredients(
            recipe_url,
            json_data,
            upload_path,
            mime_type,
            filename,
            page_text,
        )
        save_extracted_recipe_json(recipe_url, json_data)

        return build_extract_result(recipe_url, json_data, "upload")
    except Exception as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_UPLOAD_ERROR.txt"
        raw_error_path.write_text(str(exc), encoding="utf-8")

        return {
            "ok": False,
            "error": f"Upload extraction failed: {exc}",
        }


def upload_can_use_openai_file_input(mime_type, filename, upload_path):
    suffix = Path(filename or upload_path.name).suffix.lower()

    if mime_type in OPENAI_FILE_INPUT_MIME_TYPES:
        return True

    return suffix == ".pdf"


def normalize_upload_mime_type(mime_type, filename, upload_path):
    guessed_type = mimetypes.guess_type(filename or str(upload_path))[0]

    if not mime_type or mime_type == "application/octet-stream":
        return guessed_type or "application/octet-stream"

    return mime_type


def build_upload_prompt(recipe_url, filename):
    return build_prompt(
        recipe_url,
        f"""
This recipe was uploaded as an image or document named {filename}.

Read the visible recipe content from the uploaded file. Extract the recipe title, servings,
ingredients, equipment, instructions, and nutrition if visible.

If the upload is a grocery package, handwritten note, printed recipe card, cookbook page,
screenshot, or recipe photo, use only the visible text. Do not invent hidden ingredients.
""",
    )


def determine_upload_recipe_title(recipe_url, upload_path, mime_type, filename, page_text=""):
    prompt_text = build_upload_title_prompt(recipe_url, filename)

    try:
        if mime_type.startswith("image/"):
            response_text = send_image_prompt_to_openai(prompt_text, upload_path, mime_type)
        elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
            response_text = send_file_prompt_to_openai(prompt_text, upload_path, mime_type, filename)
        elif page_text.strip():
            response_text = send_prompt_to_openai(
                build_upload_title_prompt(recipe_url, filename, page_text[:MAX_PAGE_TEXT_CHARS])
            )
        else:
            return ""

        data = json.loads(clean_json_response(response_text))
    except Exception as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_TITLE_ERROR.txt"
        raw_error_path.write_text(str(exc), encoding="utf-8")
        return ""

    return normalize_recipe_title(data.get("recipe_title") or data.get("title") or "")


def build_upload_title_prompt(recipe_url, filename, page_text=""):
    visible_text = f"\nReadable text:\n{page_text}\n" if page_text else ""

    return f"""
This recipe was uploaded as {filename}.

Read the entire uploaded document and determine the primary recipe title/name.

Rules:
- Use the title printed in the document when one is visible.
- Do not use the upload filename, random id, URL, or file extension as the title.
- If the document contains multiple recipes, choose the title that best matches the main ingredient list and instructions being extracted.
- Return null if no recipe title is visible or strongly implied.
{visible_text}
Return ONLY valid JSON in this shape:
{{
  "recipe_title": "Recipe title or null"
}}
"""


def normalize_recipe_title(value):
    title = re.sub(r"\s+", " ", str(value or "").strip())

    if not title or title.lower() in {"none", "null", "unknown", "untitled"}:
        return ""

    return title


def merge_missing_upload_ingredients(recipe_url, json_data, upload_path, mime_type, filename, page_text=""):
    raw_lines = audit_upload_ingredient_lines(
        recipe_url,
        upload_path,
        mime_type,
        filename,
        page_text,
    )

    if not raw_lines:
        return

    existing_keys = {
        normalize_ingredient_key(normalize_ingredient_for_shopping_list(
            item.get("ingredient") or item.get("original_text") or ""
        ))
        for item in json_data.get("ingredients", [])
        if isinstance(item, dict)
    }
    existing_original_keys = {
        normalize_ingredient_key(normalize_ingredient_for_shopping_list(
            item.get("original_text") or item.get("ingredient") or ""
        ))
        for item in json_data.get("ingredients", [])
        if isinstance(item, dict)
    }
    all_existing_keys = existing_keys | existing_original_keys
    missing_rows = []

    for row in build_structured_ingredients(raw_lines):
        key = normalize_ingredient_key(
            normalize_ingredient_for_shopping_list(row.get("ingredient") or row.get("original_text") or "")
        )

        if not key or ingredient_key_matches_existing(key, all_existing_keys):
            continue

        missing_rows.append(row)
        all_existing_keys.add(key)

    if missing_rows:
        json_data.setdefault("ingredients", []).extend(missing_rows)
        normalize_extracted_ingredient_fields(json_data)


def ingredient_key_matches_existing(candidate_key, existing_keys):
    if candidate_key in existing_keys:
        return True

    for existing_key in existing_keys:
        if candidate_key in alternative_ingredient_key_parts(existing_key):
            return True

        if existing_key in alternative_ingredient_key_parts(candidate_key):
            return True

    return False


def alternative_ingredient_key_parts(key):
    return {
        normalize_ingredient_key(part)
        for part in re.split(r"\s+or\s+", str(key or ""), flags=re.IGNORECASE)
        if normalize_ingredient_key(part)
    }


def audit_upload_ingredient_lines(recipe_url, upload_path, mime_type, filename, page_text=""):
    prompt_text = build_upload_ingredient_audit_prompt(recipe_url, filename)

    try:
        if mime_type.startswith("image/"):
            response_text = send_image_prompt_to_openai(prompt_text, upload_path, mime_type)
        elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
            response_text = send_file_prompt_to_openai(prompt_text, upload_path, mime_type, filename)
        elif page_text.strip():
            response_text = send_prompt_to_openai(
                build_upload_ingredient_audit_prompt(recipe_url, filename, page_text[:MAX_PAGE_TEXT_CHARS])
            )
        else:
            return []

        data = json.loads(clean_json_response(response_text))
    except Exception as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_INGREDIENT_AUDIT_ERROR.txt"
        raw_error_path.write_text(str(exc), encoding="utf-8")
        return []

    ingredients = data.get("ingredients", [])

    if not isinstance(ingredients, list):
        return []

    return [
        str(item or "").strip()
        for item in ingredients
        if str(item or "").strip()
    ]


def build_upload_ingredient_audit_prompt(recipe_url, filename, page_text=""):
    visible_text = f"\nReadable text:\n{page_text}\n" if page_text else ""

    return f"""
This recipe was uploaded as {filename}.

Audit the uploaded recipe for visible ingredient lines only. Return every visible ingredient line exactly as written,
including ingredients that may need food-rule review such as corn syrup, food dyes, preservatives, or artificial ingredients.

Do not skip ingredients because they are unhealthy, optional, repeated, unusual, or visually separated from the main list.
Do not infer ingredients from instructions. Use only visible ingredient list lines.
{visible_text}
Return ONLY valid JSON in this shape:
{{
  "ingredients": [
    "1 cup Corn syrup"
  ]
}}
"""


def extract_text_from_pdf(upload_path):
    try:
        from PyPDF2 import PdfReader
    except Exception as exc:
        raise RuntimeError("PDF support requires PyPDF2 to be installed.") from exc

    reader = PdfReader(str(upload_path))
    page_text = []

    for page in reader.pages:
        page_text.append(page.extract_text() or "")

    return "\n".join(page_text)


def extract_text_from_generic_document(upload_path):
    suffix = upload_path.suffix.lower()

    if suffix == ".docx":
        return extract_text_from_docx(upload_path)

    text = upload_path.read_text(encoding="utf-8", errors="ignore")

    if suffix in {".html", ".htm"}:
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text("\n")

    if suffix == ".rtf":
        text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
        text = re.sub(r"[{}]", " ", text)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)

    return text


def extract_text_from_docx(upload_path):
    try:
        with zipfile.ZipFile(upload_path) as archive:
            xml_text = archive.read("word/document.xml")
    except Exception as exc:
        raise RuntimeError("Could not read text from that Word document.") from exc

    root = ET.fromstring(xml_text)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []

    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(
            node.text or ""
            for node in paragraph.findall(".//w:t", namespace)
        ).strip()

        if text:
            paragraphs.append(text)

    return "\n".join(paragraphs)


def build_extract_result(recipe_url, json_data, extraction_method):
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
        "extraction_method": extraction_method,
    }


def normalize_ingredient_key(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def normalize_ingredient_for_shopping_list(text):
    value = clean_recipe_text(text)

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

    alternative_value = normalize_alternative_shopping_ingredient(value)
    if alternative_value:
        return alternative_value

    value = value.split(",", 1)[0].strip()

    alternative_value = normalize_alternative_shopping_ingredient(value)
    if alternative_value:
        return alternative_value

    quantity_pattern = rf"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[{FRACTION_CHARS}])+"
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

    value = re.sub(r"\s+", " ", value).strip()
    value = canonicalize_shopping_ingredient(value)
    return singularize_shopping_ingredient(value)


def canonicalize_shopping_ingredient(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    value = re.sub(r"^of\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:bunch|bunches)\s+(?=\w)", "", value, flags=re.IGNORECASE)
    return value.strip()


def singularize_shopping_ingredient(value):
    normalized = normalize_ingredient_key(value)
    singular_names = {
        "eggs": "egg",
        "lemons": "lemon",
        "limes": "lime",
        "onions": "onion",
        "tomatoes": "tomato",
        "potatoes": "potato",
        "carrots": "carrot",
        "cloves": "clove",
    }

    return singular_names.get(normalized, value)


def normalize_alternative_shopping_ingredient(value):
    value = re.sub(r",\s+or\s+", " or ", str(value or "").strip(), flags=re.IGNORECASE)
    quantity_pattern = rf"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[{FRACTION_CHARS}])+"
    unit_pattern = (
        r"(?:cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?)"
    )
    match = re.match(
        rf"^(?:{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\s+)?"
        rf"(?P<first>.+?)\s+or\s+"
        rf"(?:{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\s+)?"
        rf"(?P<second>.+)$",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    first = strip_leading_amount(match.group("first"))
    second = strip_leading_amount(match.group("second"))

    if not first or not second:
        return ""

    return f"{first} OR {second}"


def strip_leading_amount(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    quantity_pattern = rf"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[{FRACTION_CHARS}])+"
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

    return value.strip()


def extract_recipe_from_url(recipe_url, progress_callback=None):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {
            "ok": False,
            "error": "Missing recipe URL.",
            "ingredients": [],
        }

    try:
        def report(message, summary=None):
            if progress_callback:
                progress_callback(message, summary)

        print("\n==================================================")
        print("Recipe 1/1")
        print(recipe_url)
        print("==================================================")

        report(
            "downloading webpage HTML...",
            "Opening the recipe URL and saving the page HTML.",
        )
        html_text, page_text = fetch_recipe_page(recipe_url, progress_callback=report)

        if not page_text:
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "No page text found.",
                "ingredients": [],
            }

        structured_json_data = extract_recipe_from_structured_data(recipe_url, html_text)

        force_openai = os.getenv("FORCE_OPENAI_RECIPE_EXTRACTION") == "1"

        if structured_recipe_data_is_usable(structured_json_data) and not force_openai:
            normalize_extracted_ingredient_fields(structured_json_data)
            normalize_extracted_equipment_fields(structured_json_data)
            save_extracted_recipe_json(recipe_url, structured_json_data)
            print("Structured recipe data found; using recipe card for fast extraction.")
            report(
                "recipe card found - extracted without OpenAI API fallback.",
                "Recipe-card HTML was enough to extract ingredients and instructions.",
            )
            return build_extract_result(recipe_url, structured_json_data, "structured_data")

        if structured_json_data:
            print("Structured recipe data found, but API extraction was forced.")

        if not os.getenv("OPENAI_API_KEY"):
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "Missing OPENAI_API_KEY environment variable.",
                "ingredients": [],
            }

        prompt_text = build_prompt(recipe_url, page_text)

        print("Sending to OpenAI API...")
        report(
            "sending webpage content to OpenAI API...",
            "No complete recipe card was found, so OpenAI is extracting from the page content.",
        )
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
