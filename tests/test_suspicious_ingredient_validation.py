from PushShoppingList.services.recipe_extract_service import (
    normalize_extracted_ingredient_fields,
)
from PushShoppingList.services.recipe_ingredient_service import ingredient_detail_records


POTATO_MILK_WARNING = (
    "Possible extraction issue: 'potato milk' may have been incorrectly generated. "
    "Check the source recipe."
)


def test_huancaina_replaces_generated_potato_milk_when_source_lacks_exact_phrase():
    recipe = {
        "recipe_title": "Yuca (cassava) la Huancaína",
        "ingredients": [
            {
                "quantity": "1",
                "unit": "cup",
                "ingredient": "potato milk",
                "original_text": "1 cup potato milk",
            }
        ],
    }
    source_text = "Yuca la Huancaina with aji amarillo, queso fresco, and evaporated milk."

    normalize_extracted_ingredient_fields(recipe, source_text=source_text)

    ingredient = recipe["ingredients"][0]
    assert ingredient["ingredient"] == "evaporated milk"
    assert ingredient["normalized_name"] == "evaporated milk"
    assert ingredient["parsed_name"] == "potato milk"
    assert ingredient["warning"] == POTATO_MILK_WARNING
    assert ingredient["confidence"] == "low"
    assert ingredient["inferred"] is False


def test_huancaina_marks_replacement_inferred_when_no_source_milk_phrase_exists():
    recipe = {
        "recipe_title": "Yuca (cassava) la Huancaína",
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
    assert ingredient["ingredient"] == "evaporated milk"
    assert ingredient["normalized_name"] == "evaporated milk"
    assert ingredient["inferred"] is True
    assert ingredient["warning"] == POTATO_MILK_WARNING


def test_exact_source_potato_milk_is_preserved_without_warning():
    recipe = {
        "recipe_title": "Yuca (cassava) la Huancaína",
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


def test_ingredient_detail_records_preserve_extraction_audit_fields():
    recipe = {
        "raw": {
            "ingredients": [
                {
                    "original_text": "1 cup potato milk",
                    "parsed_name": "potato milk",
                    "normalized_name": "evaporated milk",
                    "quantity": "1",
                    "unit": "cup",
                    "confidence": "low",
                    "inferred": True,
                    "warning": POTATO_MILK_WARNING,
                }
            ]
        }
    }

    details = ingredient_detail_records(recipe_metadata=recipe)

    assert details == [
        {
            "original_text": "1 cup potato milk",
            "parsed_name": "potato milk",
            "normalized_name": "evaporated milk",
            "quantity": "1",
            "unit": "cup",
            "confidence": "low",
            "inferred": True,
            "warning": POTATO_MILK_WARNING,
        }
    ]
