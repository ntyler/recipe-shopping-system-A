import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


# =========================================================
# PROJECT PATHS
# =========================================================
BASE_DIR = Path(__file__).resolve().parent

URLS_FILE = BASE_DIR / "urls.txt"
OUTPUT_FOLDER = BASE_DIR / "data" / "output"
RAW_FOLDER = BASE_DIR / "data" / "raw"
LOG_FOLDER = BASE_DIR / "data" / "logs"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
RAW_FOLDER.mkdir(parents=True, exist_ok=True)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)


# =========================================================
# CONFIG
# =========================================================
MODEL = "gpt-4o-mini"
MAX_PAGE_TEXT_CHARS = 35000
REQUEST_DELAY_SECONDS = 1

client = OpenAI()


# =========================================================
# LOAD URLS
# =========================================================
def load_recipe_urls(input_urls=None):
    if input_urls:
        return [u.strip() for u in input_urls if u.strip()]

    if not URLS_FILE.exists():
        URLS_FILE.write_text(
            "https://www.forkinthekitchen.com/homemade-cheese-ravioli/\n",
            encoding="utf-8"
        )
        print(f"Created urls.txt here: {URLS_FILE}")
        return []

    urls = []

    for line in URLS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        urls.append(line)

    return urls


# =========================================================
# HELPERS
# =========================================================
def safe_filename(text):
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"www\.", "", text)
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_")[:120]


def clean_json_response(text):
    text = text.strip()
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


# =========================================================
# WEBPAGE LOADER
# =========================================================
def fetch_recipe_page_text(recipe_url):
    try:
        print(f"🌐 Fetching recipe page: {recipe_url}")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            )
        }

        response = requests.get(recipe_url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        page_text = soup.get_text(" ", strip=True)
        page_text = re.sub(r"\s+", " ", page_text).strip()

        if len(page_text) > MAX_PAGE_TEXT_CHARS:
            page_text = page_text[:MAX_PAGE_TEXT_CHARS]

        raw_page_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_TEXT.txt"
        raw_page_path.write_text(page_text, encoding="utf-8")

        print(f"✅ Loaded webpage text: {len(page_text)} characters")
        return page_text

    except Exception as e:
        print(f"❌ Could not load recipe page: {e}")
        return ""


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
- Assign store_section and store_section_order.
- Do NOT rename, merge, add, or remove ingredient text.

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

# =========================================================
# OPENAI API
# =========================================================
def send_prompt_to_openai(prompt_text):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You extract recipe ingredients and return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt_text
            }
        ],
        response_format={"type": "json_object"},
        temperature=0
    )

    return response.choices[0].message.content


# =========================================================
# SAVE JSON
# =========================================================
def save_json_response(recipe_url, response_text):
    cleaned = clean_json_response(response_text)

    base_name = safe_filename(recipe_url)
    json_path = OUTPUT_FOLDER / f"{base_name}.json"
    raw_path = RAW_FOLDER / f"{base_name}_RAW.txt"

    try:
        json_data = json.loads(cleaned)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        print(f"✅ Saved JSON: {json_path}")
        return True, json_data

    except json.JSONDecodeError as e:
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)

        print(f"⚠️ Invalid JSON. Saved raw response: {raw_path}")
        print(f"JSON error: {e}")
        return False, None


# =========================================================
# MAIN
# =========================================================
def main(input_urls=None):
    all_results = []

    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Missing OPENAI_API_KEY environment variable.")
        print()
        print("Run this in Command Prompt:")
        print('setx OPENAI_API_KEY "your_api_key_here"')
        print()
        print("Then close and reopen Command Prompt.")
        return []

    recipe_urls = load_recipe_urls(input_urls)

    if not recipe_urls:
        print("No recipe URLs found.")
        return []

    total_records = len(recipe_urls)

    for index, recipe_url in enumerate(recipe_urls, start=1):
        print("\n==================================================")
        print(f"Recipe {index}/{total_records}")
        print(recipe_url)
        print("==================================================")

        try:
            page_text = fetch_recipe_page_text(recipe_url)

            if not page_text:
                print(f"⚠️ No page text found for: {recipe_url}")
                continue

            prompt_text = build_prompt(recipe_url, page_text)

            print("🤖 Sending to OpenAI API...")
            response_text = send_prompt_to_openai(prompt_text)

            raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_API_RESPONSE.txt"
            raw_api_path.write_text(response_text, encoding="utf-8")

            success, json_data = save_json_response(recipe_url, response_text)

            if success and json_data:
                all_results.append(json_data)

            time.sleep(REQUEST_DELAY_SECONDS)

        except Exception as e:
            print(f"❌ Failed recipe: {recipe_url}")
            print(e)

    print("\n🎉 All recipe URLs processed.")
    return all_results


if __name__ == "__main__":
    results = main()
    print(json.dumps(results, indent=2, ensure_ascii=False))
