import unittest

from PushShoppingList.services.recipe_extract_service import add_equipment_used_to_instructions
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields


class RecipeEquipmentNormalizationTests(unittest.TestCase):
    def test_editor_equipment_records_do_not_require_name_key(self):
        recipe_data = {
            "equipment": [
                {
                    "equipment": "baking sheet",
                    "text": "baking sheet",
                    "equipment_image_url": "/static/generated/example.png",
                }
            ],
            "instructions": [
                {
                    "instruction": "Line a baking sheet with parchment paper.",
                    "step_number": 1,
                }
            ],
        }

        normalize_extracted_equipment_fields(recipe_data)

        self.assertEqual(recipe_data["instructions"][0]["equipment_used"], ["baking sheet"])

    def test_add_equipment_used_accepts_name_equipment_text_and_string_items(self):
        instructions = [
            {
                "instruction": (
                    "Preheat the oven, line a baking sheet, mix in a large bowl, "
                    "and chop herbs."
                )
            }
        ]
        equipment = [
            {"equipment": "baking sheet"},
            {"text": "mixing bowl"},
            {"name": "oven"},
            "cutting board",
        ]

        add_equipment_used_to_instructions(instructions, equipment)

        self.assertEqual(
            instructions[0]["equipment_used"],
            ["baking sheet", "mixing bowl", "oven", "cutting board"],
        )


if __name__ == "__main__":
    unittest.main()
