import json
import os
import re
from pathlib import Path

from openai import OpenAI

from PushShoppingList.services.recipe_extract_service import (
    LOG_FOLDER,
    OUTPUT_FOLDER,
    STORE_SECTION_ORDER,
    classify_store_section,
    ingredient_key_matches_existing,
    normalize_ingredient_for_shopping_list,
    normalize_ingredient_key,
)
from PushShoppingList.services.shopping_list_service import SHOPPING_LIST_FILE


BASE_DIR = Path(__file__).resolve().parent

PUSH_DIR = BASE_DIR.parent

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)

SORTED_JSON_FILE = OUTPUT_FOLDER / "sorted_ingredients.json"
SORTED_TXT_FILE = OUTPUT_FOLDER / "sorted_ingredients.txt"
RAW_RESPONSE_FILE = OUTPUT_FOLDER / "sorted_ingredients_RAW.txt"

MODEL = "gpt-4o-mini"
WRITE_BACK_TO_SHOPPING_LIST = True
SAVE_SECTION_HEADERS_TO_SHOPPING_LIST = True

SECTION_ITEM_ORDER = {
    "PRODUCE": [
        "lemon",
        "zest",
        "basil",
        "herb",
        "garlic",
        "onion",
        "tomato",
    ],
    "DAIRY & EGGS": [
        "egg",
        "yolk",
        "ricotta",
        "parmesan",
        "cheese",
        "milk",
        "cream",
        "yogurt",
        "butter",
    ],
    "PASTA, RICE & GRAINS": [
        "pasta",
        "noodle",
        "rice",
        "grain",
        "oat",
        "quinoa",
        "breadcrumb",
    ],
    "BAKING": [
        "flour",
        "baking powder",
        "baking soda",
        "yeast",
        "sugar",
        "corn syrup",
        "vanilla",
        "chocolate chip",
        "chocolate",
        "cocoa powder",
        "cocoa",
        "cocoa butter",
    ],
    "SAUCES & CONDIMENTS": [
        "tomato sauce",
        "sauce",
        "ketchup",
        "mustard",
        "mayonnaise",
        "soy sauce",
        "hot sauce",
        "salsa",
    ],
    "SPICES & SEASONINGS": [
        "salt",
        "pepper",
        "cinnamon",
        "nutmeg",
        "paprika",
        "cumin",
        "oregano",
        "thyme",
        "basil",
    ],
    "OILS & VINEGARS": [
        "oil",
        "olive oil",
        "vegetable oil",
        "vinegar",
    ],
}

client = None


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    return client


def load_ingredient_list():
    if not SHOPPING_LIST_FILE.exists():
        print(f"Shopping list file not found: {SHOPPING_LIST_FILE}")
        return []

    return [
        line.strip()
        for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def unique_shopping_ingredients(items):
    unique_items = []
    seen_keys = []

    for item in items:
        if is_section_header(item):
            continue

        cleaned = normalize_ingredient_for_shopping_list(item)
        key = normalize_ingredient_key(cleaned)

        if not cleaned:
            continue

        replacement_index = alternative_replacement_index(key, seen_keys)

        if replacement_index is not None:
            seen_keys[replacement_index] = key
            unique_items[replacement_index] = cleaned
        elif not ingredient_key_matches_existing(key, set(seen_keys)):
            unique_items.append(cleaned)
            seen_keys.append(key)

    return unique_items


def alternative_replacement_index(candidate_key, existing_keys):
    if " or " not in candidate_key:
        return None

    candidate_parts = set(candidate_key.split(" or "))

    for index, existing_key in enumerate(existing_keys):
        if " or " in existing_key:
            continue

        if existing_key in candidate_parts:
            return index

    return None


def remove_empty_sections(items):
    cleaned_items = []
    pending_header = None

    for item in items:
        if is_section_header(item):
            pending_header = item
            continue

        if pending_header:
            cleaned_items.append(pending_header)
            pending_header = None

        cleaned_items.append(item)

    return cleaned_items


def build_locally_sorted_items(ingredient_list):
    sections = {
        section: []
        for section in sorted(
            STORE_SECTION_ORDER,
            key=STORE_SECTION_ORDER.get,
        )
    }

    for ingredient in ingredient_list:
        section = classify_store_section(ingredient)
        sections.setdefault(section, []).append(ingredient)

    sorted_items = []

    for section in sorted(
        sections,
        key=lambda value: STORE_SECTION_ORDER.get(value, 999),
    ):
        items = sorted(
            sections[section],
            key=lambda item: section_item_sort_key(section, item),
        )

        if not items:
            continue

        sorted_items.append(f"=== {section} ===")
        sorted_items.extend(items)

    return sorted_items


def section_item_sort_key(section, item):
    normalized = normalize_ingredient_key(item).replace("*", "")
    order = SECTION_ITEM_ORDER.get(section, [])

    for index, keyword in enumerate(order):
        if keyword in normalized:
            return index, normalized

    return len(order), normalized


def save_locally_sorted_items(sorted_items):
    data = {
        "sorted_ingredients": sorted_items,
    }

    SORTED_JSON_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    SORTED_TXT_FILE.write_text(
        "\n".join(sorted_items),
        encoding="utf-8",
    )

    if WRITE_BACK_TO_SHOPPING_LIST:
        items_to_write = sorted_items if SAVE_SECTION_HEADERS_TO_SHOPPING_LIST else [
            item
            for item in sorted_items
            if not is_section_header(item)
        ]
        SHOPPING_LIST_FILE.write_text(
            "\n".join(items_to_write),
            encoding="utf-8",
        )

    print(f"Updated shopping list: {SHOPPING_LIST_FILE}")
    print(f"Saved sorted JSON: {SORTED_JSON_FILE}")
    print(f"Saved sorted TXT: {SORTED_TXT_FILE}")

    return data


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
produce -> meat & seafood -> dairy & eggs -> frozen -> dry goods -> pasta, rice & grains -> baking -> canned -> sauces & condiments -> snacks -> beverages -> spices & seasonings -> oils & vinegars -> bakery -> deli -> household -> personal care -> pet supplies -> misc

SECTION RULES:
- Use ONLY these exact section names:

PRODUCE
MEAT & SEAFOOD
DAIRY & EGGS
FROZEN
DRY GOODS
PASTA, RICE & GRAINS
BAKING
CANNED
SAUCES & CONDIMENTS
SNACKS
BEVERAGES
SPICES & SEASONINGS
OILS & VINEGARS
BAKERY
DELI
HOUSEHOLD
PERSONAL CARE
PET SUPPLIES
MISC

CLASSIFICATION GUIDANCE:
- Eggs go in DAIRY & EGGS.
- Butter, yogurt, milk, cream, cheese, and sour cream go in DAIRY & EGGS.
- Flour, sugar, brown sugar, baking powder, baking soda, vanilla extract, chocolate chips, cocoa powder, and yeast go in BAKING.
- Salt, kosher salt, sea salt, pepper, cinnamon, garlic powder, onion powder, paprika, chili powder, cumin, and dried herbs go in SPICES & SEASONINGS.
- Olive oil, vegetable oil, sesame oil, cooking spray, and vinegars go in OILS & VINEGARS.
- Pasta, rice, quinoa, oats, breadcrumbs, and grains go in PASTA, RICE & GRAINS.

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
    "=== DAIRY & EGGS ===",
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
    response = get_openai_client().chat.completions.create(
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
        sorted_ingredients = remove_empty_sections(sorted_ingredients)
        data["sorted_ingredients"] = sorted_ingredients

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

            print(f"Updated shopping list: {SHOPPING_LIST_FILE}")

        print(f"Saved sorted JSON: {SORTED_JSON_FILE}")
        print(f"Saved sorted TXT: {SORTED_TXT_FILE}")

        return data

    except Exception as exc:
        RAW_RESPONSE_FILE.write_text(response_text, encoding="utf-8")

        print("Could not save sorted response.")
        print(f"Raw response saved to: {RAW_RESPONSE_FILE}")
        print(f"Error: {exc}")

        return None


def main():
    ingredient_list = load_ingredient_list()

    if not ingredient_list:
        print("No ingredients found in shopping_list.txt.")
        return None

    ingredient_list = unique_shopping_ingredients(ingredient_list)

    if not ingredient_list:
        print("No actual ingredients found after removing section headers.")
        return None

    print(f"Loaded {len(ingredient_list)} ingredients from shopping_list.txt.")
    sorted_items = build_locally_sorted_items(ingredient_list)
    return save_locally_sorted_items(sorted_items)


if __name__ == "__main__":
    result = main()

    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
