import json
import os
import re
import time
from pathlib import Path

from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

SHOPPING_LIST_FILE = PROJECT_DIR / "PushShoppingList" / "shopping_list.txt"

OUTPUT_FOLDER = BASE_DIR / "data" / "output"
LOG_FOLDER = BASE_DIR / "data" / "logs"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)

SORTED_JSON_FILE = OUTPUT_FOLDER / "sorted_ingredients.json"
SORTED_TXT_FILE = OUTPUT_FOLDER / "sorted_ingredients.txt"
RAW_RESPONSE_FILE = OUTPUT_FOLDER / "sorted_ingredients_RAW.txt"

MODEL = "gpt-4o-mini"
WRITE_BACK_TO_SHOPPING_LIST = True
SAVE_SECTION_HEADERS_TO_SHOPPING_LIST = True
REQUEST_DELAY_SECONDS = 1

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def load_ingredient_list():
    if not SHOPPING_LIST_FILE.exists():
        print(f"Shopping list file not found: {SHOPPING_LIST_FILE}")
        return []

    return [
        line.strip()
        for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def is_section_header(text):
    text = str(text).strip()
    return text.startswith("===") and text.endswith("===")


def build_sort_prompt(ingredient_list):
    ingredients_text = "\n".join(ingredient_list)

    return f"""
Sort the following ingredient list into grocery store walking order.

STRICT RULES:
- Do NOT change, rename, or merge any ingredient text.
- Preserve exact spelling, capitalization, and wording.
- Do NOT remove duplicates.
- Do NOT add new ingredients.
- Only reorder the list.
- Every ingredient from the input MUST appear exactly once in the output.

STORE LAYOUT ORDER:
produce → dairy → dry goods → canned → beverages → spices → oils → bakery → misc

SECTION RULES:
- Use ONLY these exact section names:
  PRODUCE, DAIRY, DRY GOODS, CANNED, BEVERAGES, SPICES, OILS, BAKERY, MISC
- Each section header MUST be formatted exactly as:
  === SECTION NAME ===
- Do NOT create empty sections.
- Do NOT place ingredients outside of a section.
- Do NOT repeat section headers.

OUTPUT FORMAT:
Return ONLY valid JSON:

{{
  "sorted_ingredients": [
    "=== PRODUCE ===",
    "item 1",
    "item 2",
    "=== DAIRY ===",
    "item 3"
  ]
}}

INGREDIENT LIST:
{ingredients_text}
"""


def clean_json_response(text):
    text = str(text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = text.replace("\r\n", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    return text.strip()


def validate_sorted_list(original_items, sorted_items):
    if not isinstance(sorted_items, list):
        raise ValueError("sorted_ingredients is not a list.")

    cleaned_sorted_items = [
        item
        for item in sorted_items
        if not is_section_header(item)
    ]

    original_sorted = sorted(original_items)
    result_sorted = sorted(cleaned_sorted_items)

    if original_sorted != result_sorted:
        missing = sorted(set(original_items) - set(cleaned_sorted_items))
        extra = sorted(set(cleaned_sorted_items) - set(original_items))

        raise ValueError(
            "Sorted result does not contain the exact same ingredients as the original list.\n"
            f"Missing: {missing}\n"
            f"Extra: {extra}"
        )


def send_prompt_to_openai(prompt_text):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You sort grocery ingredients and return only valid JSON.",
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


def save_sorted_response(response_text, original_items):
    cleaned = clean_json_response(response_text)

    try:
        data = json.loads(cleaned)
        sorted_ingredients = data.get("sorted_ingredients", [])

        validate_sorted_list(original_items, sorted_ingredients)

        SORTED_JSON_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        SORTED_TXT_FILE.write_text(
            "\n".join(sorted_ingredients),
            encoding="utf-8",
        )

        if WRITE_BACK_TO_SHOPPING_LIST:
            if SAVE_SECTION_HEADERS_TO_SHOPPING_LIST:
                items_to_write = sorted_ingredients
            else:
                items_to_write = [
                    item
                    for item in sorted_ingredients
                    if not is_section_header(item)
                ]

            SHOPPING_LIST_FILE.write_text(
                "\n".join(items_to_write),
                encoding="utf-8",
            )

            print(f"✅ Updated shopping list: {SHOPPING_LIST_FILE}")

        print(f"✅ Saved sorted JSON: {SORTED_JSON_FILE}")
        print(f"✅ Saved sorted TXT: {SORTED_TXT_FILE}")

        return data

    except Exception as exc:
        RAW_RESPONSE_FILE.write_text(response_text, encoding="utf-8")

        print("⚠️ Could not save sorted response.")
        print(f"Raw response saved to: {RAW_RESPONSE_FILE}")
        print(f"Error: {exc}")

        return None


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Missing OPENAI_API_KEY environment variable.")
        return None

    ingredient_list = load_ingredient_list()

    if not ingredient_list:
        print("No ingredients found in shopping_list.txt.")
        return None

    ingredient_list = [
        item
        for item in ingredient_list
        if not is_section_header(item)
    ]

    if not ingredient_list:
        print("No actual ingredients found after removing section headers.")
        return None

    print(f"✅ Loaded {len(ingredient_list)} ingredients from shopping_list.txt.")

    prompt_text = build_sort_prompt(ingredient_list)

    try:
        print("🤖 Sending sort request to OpenAI API...")
        response_text = send_prompt_to_openai(prompt_text)

        RAW_RESPONSE_FILE.write_text(response_text, encoding="utf-8")

        time.sleep(REQUEST_DELAY_SECONDS)

        return save_sorted_response(response_text, ingredient_list)

    except Exception as exc:
        print("❌ API sorting failed.")
        print(exc)
        return None


if __name__ == "__main__":
    result = main()

    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))