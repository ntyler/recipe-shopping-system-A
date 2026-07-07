from PushShoppingList.services.recipe_extract_service import (
    normalize_extracted_ingredient_fields,
)
from PushShoppingList.services.food_review_alternative_service import (
    build_alternative_prompt,
    build_food_review_context,
)
from PushShoppingList.services.recipe_ingredient_service import ingredient_detail_records


POTATO_MILK_WARNING = (
    "Possible extraction issue: 'potato milk' may have been incorrectly generated. "
    "Check the source recipe."
)


def test_huancaina_flags_generated_potato_milk_without_replacing_it():
    recipe = {
        "recipe_title": "Yuca (cassava) la Huancaina",
        "ingredients": [
            {
                "quantity": "2",
                "unit": "cups",
                "ingredient": "potato milk",
                "original_text": "2 cups potato milk",
            }
        ],
    }
    source_text = "Yuca la Huancaina with aji amarillo, queso fresco, and evaporated milk."

    normalize_extracted_ingredient_fields(recipe, source_text=source_text)

    ingredient = recipe["ingredients"][0]
    assert ingredient["ingredient"] == "potato milk"
    assert ingredient["normalized_name"] == "potato milk"
    assert ingredient["parsed_name"] == "potato milk"
    assert ingredient["warning"] == POTATO_MILK_WARNING
    assert ingredient["confidence"] == "low"
    assert ingredient["inferred"] is True
    assert ingredient["food_review"]["needs_review"] is True
    assert ingredient["food_review"]["kind"] == "suspicious_ingredient"
    assert ingredient["food_review"]["status"] == "open"
    assert ingredient["food_review"]["original_ingredient"] == "2 cups potato milk"
    assert "Huancaina-style" in ingredient["food_review"]["reason"]
    assert ingredient["food_review"]["options"][0]["ingredient"] == "evaporated milk"
    assert ingredient["food_review"]["options"][0]["quantity"] == "2"
    assert ingredient["food_review"]["options"][0]["unit"] == "cups"


def test_huancaina_proposes_evaporated_milk_when_no_source_milk_phrase_exists():
    recipe = {
        "recipe_title": "Yuca (cassava) la Huancaina",
        "ingredients": [
            {
                "quantity": "1",
                "unit": "cup",
                "ingredient": "potato milk",
                "original_text": "1 cup potato milk",
            }
        ],
    }
    source_text = "Yuca la Huancaina with yuca, aji amarillo, queso fresco, and crackers."

    normalize_extracted_ingredient_fields(recipe, source_text=source_text)

    ingredient = recipe["ingredients"][0]
    assert ingredient["ingredient"] == "potato milk"
    assert ingredient["normalized_name"] == "potato milk"
    assert ingredient["inferred"] is True
    assert ingredient["warning"] == POTATO_MILK_WARNING
    assert ingredient["food_review"]["options"][0]["ingredient"] == "evaporated milk"


def test_exact_source_potato_milk_is_preserved_without_warning():
    recipe = {
        "recipe_title": "Yuca (cassava) la Huancaina",
        "ingredients": [
            {
                "quantity": "1",
                "unit": "cup",
                "ingredient": "potato milk",
                "original_text": "1 cup potato milk",
            }
        ],
    }
    source_text = "Ingredients: yuca, potato milk, queso fresco, and aji amarillo."

    normalize_extracted_ingredient_fields(recipe, source_text=source_text)

    ingredient = recipe["ingredients"][0]
    assert ingredient["ingredient"] == "potato milk"
    assert ingredient["normalized_name"] == "potato milk"
    assert ingredient["warning"] == ""
    assert ingredient["inferred"] is False
    assert "food_review" not in ingredient


def test_ingredient_detail_records_preserve_extraction_audit_fields_and_food_review():
    food_review = {
        "needs_review": True,
        "kind": "suspicious_ingredient",
        "status": "open",
        "reason": "Potato milk is unusual for a Huancaina-style sauce.",
        "options": [{"ingredient": "evaporated milk"}],
    }
    recipe = {
        "raw": {
            "ingredients": [
                {
                    "original_text": "1 cup potato milk",
                    "parsed_name": "potato milk",
                    "normalized_name": "potato milk",
                    "quantity": "1",
                    "unit": "cup",
                    "confidence": "low",
                    "inferred": True,
                    "warning": POTATO_MILK_WARNING,
                    "food_review": food_review,
                }
            ]
        }
    }

    details = ingredient_detail_records(recipe_metadata=recipe)

    assert details == [
        {
            "original_text": "1 cup potato milk",
            "parsed_name": "potato milk",
            "normalized_name": "potato milk",
            "quantity": "1",
            "unit": "cup",
            "confidence": "low",
            "inferred": True,
            "warning": POTATO_MILK_WARNING,
            "food_review": food_review,
        }
    ]


def test_food_review_alternative_prompt_uses_suspicious_ingredient_context():
    review = build_food_review_context({
        "recipe_title": "Yuca (cassava) la Huancaina",
        "ingredient": "potato milk",
        "original_text": "2 cups potato milk",
        "quantity": "2",
        "unit": "cups",
        "food_review": {
            "needs_review": True,
            "kind": "suspicious_ingredient",
            "reason": "Potato milk is unusual for a Huancaina-style sauce.",
            "warning": POTATO_MILK_WARNING,
            "original_ingredient": "2 cups potato milk",
            "suspicious_phrase": "potato milk",
            "options": [{
                "ingredient": "evaporated milk",
                "quantity": "2",
                "unit": "cups",
            }],
        },
    })

    prompt = build_alternative_prompt(review)

    assert review["kind"] == "suspicious_ingredient"
    assert review["review_options"][0]["ingredient"] == "evaporated milk"
    assert "Huancaina-style recipes" in prompt
    assert "Do not suggest the same suspicious phrase" in prompt
