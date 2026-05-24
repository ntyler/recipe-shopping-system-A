import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PushShoppingList.services import product_selection_service
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services.purchase_mapping_service import automatic_purchasable_item
from PushShoppingList.services.purchase_mapping_service import purchase_group_records_for_items


class PurchaseMappingServiceTests(unittest.TestCase):
    def test_common_recipe_terms_map_to_purchasable_items(self):
        self.assertEqual(automatic_purchasable_item("yolks"), "eggs")
        self.assertEqual(automatic_purchasable_item("egg whites"), "eggs")
        self.assertEqual(automatic_purchasable_item("garlic cloves"), "garlic")
        self.assertEqual(automatic_purchasable_item("melted butter"), "butter")
        self.assertEqual(automatic_purchasable_item("grated parmesan"), "parmesan cheese")
        self.assertEqual(automatic_purchasable_item("shredded cheddar"), "cheddar cheese")
        self.assertEqual(automatic_purchasable_item("lemon zest"), "lemons")

    def test_egg_and_yolk_group_under_eggs(self):
        groups = purchase_group_records_for_items(["egg", "yolks"])

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["purchase_group"], "eggs")
        self.assertEqual(groups[0]["purchase_group_key"], "eggs")

    def test_missing_purchasable_item_falls_back_to_ingredient(self):
        groups = purchase_group_records_for_items(["all-purpose flour"])

        self.assertEqual(groups[0]["purchasable_item"], "all-purpose flour")
        self.assertEqual(groups[0]["purchase_group"], "all-purpose flour")

    def test_quantity_context_groups_egg_and_yolk_requirements(self):
        recipe_url = "https://example.test/cake"
        recipe_data = {
            "source_url": recipe_url,
            "ingredients": [
                {"ingredient": "egg", "quantity": "5", "unit": None},
                {"ingredient": "yolks", "quantity": "2", "unit": None},
            ],
        }

        with patch.object(product_selection_service, "load_item_state", return_value={}), \
             patch.object(product_selection_service, "load_recipe_ingredients", return_value={}), \
             patch.object(product_selection_service, "recipe_url_rows", return_value=[{"url": recipe_url, "quantity": 1, "name": "Cake"}]), \
             patch.object(product_selection_service, "load_saved_recipe_output", return_value=recipe_data):
            context = product_selection_service.load_item_quantity_context(["egg", "yolks"])

        self.assertIn("eggs", context)
        self.assertEqual(context["eggs"]["display"], "7 eggs")
        self.assertEqual(
            [source["recipe_ingredient"] for source in context["eggs"]["sources"]],
            ["egg", "yolks"],
        )

    def test_product_selection_for_child_ingredient_saves_to_purchase_group(self):
        state = {
            "items": {
                "eggs": {
                    "item_key": "eggs",
                    "ingredient": "eggs",
                    "candidates": [
                        {
                            "id": "aldi-eggs",
                            "product_name": "Large Eggs",
                            "store_key": "aldi",
                            "store_name": "ALDI",
                            "product_url": "https://example.test/eggs",
                            "viable": True,
                        }
                    ],
                    "store_results": {},
                    "store_results_list": [],
                }
            }
        }

        with patch.object(product_selection_service, "load_item_state", return_value={"yolks": {"purchasable_item": "eggs"}}), \
             patch.object(product_selection_service, "load_product_choices", return_value=state), \
             patch.object(product_selection_service, "save_product_choices", return_value=state), \
             patch.object(product_selection_service, "save_item_store") as save_store:
            result = product_selection_service.select_product_choice("yolks", "aldi-eggs", "aldi")

        self.assertTrue(result["ok"])
        self.assertEqual(result["item_key"], "eggs")
        self.assertEqual(state["items"]["eggs"]["selected_product_id"], "aldi-eggs")
        save_store.assert_called_with("eggs", "aldi")

    def test_purchase_mapping_update_preserves_recipe_ingredient_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            recipe_path = output_dir / "recipe.json"
            recipe_path.write_text(
                json.dumps({
                    "source_url": "https://example.test/hohos",
                    "ingredients": [
                        {
                            "original_text": "2 yolks",
                            "ingredient": "yolks",
                            "quantity": "2",
                            "unit": "unit",
                            "preparation": "",
                        }
                    ],
                }),
                encoding="utf-8",
            )

            with patch.object(recipe_ingredient_service, "OUTPUT_FOLDER", output_dir):
                changed = recipe_ingredient_service.update_saved_recipe_purchase_mapping("yolks", "eggs")

            saved = json.loads(recipe_path.read_text(encoding="utf-8"))
            item = saved["ingredients"][0]

        self.assertEqual(changed, [str(recipe_path)])
        self.assertEqual(item["original_text"], "2 yolks")
        self.assertEqual(item["ingredient"], "yolks")
        self.assertEqual(item["quantity"], "2")
        self.assertEqual(item["recipe_qty"], "2")
        self.assertEqual(item["unit"], "unit")
        self.assertEqual(item["purchasable_item"], "eggs")
        self.assertEqual(item["purchase_group"], "eggs")


if __name__ == "__main__":
    unittest.main()
