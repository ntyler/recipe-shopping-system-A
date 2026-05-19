import unittest

from PushShoppingList.services.product_selection_service import build_product_download_plan
from PushShoppingList.services.product_selection_service import ingredient_search_terms
from PushShoppingList.services.product_selection_service import product_matches_ingredient
from PushShoppingList.services.product_selection_service import score_candidate


def candidate(name, food_status=None):
    return {
        "id": name,
        "source": "product-card",
        "product_name": name,
        "brand": "",
        "description": "",
        "ingredients_text": "",
        "detail_text_excerpt": "",
        "detail_evaluated": True,
        "food_rule_status": food_status or {"missing_required": [], "blocked_by": []},
        "price": "$4.99",
        "unit_price": "$0.50/oz",
        "unit_price_value": 0.5,
        "unit_price_unit": "oz",
        "package_size": "10 oz",
        "in_stock": True,
        "product_url": "https://example.com/product",
        "search_url": "https://example.com/search",
        "store_location_distance_miles": 1,
        "store_name": "Test Store",
        "ranking_reasons": [],
        "skip_reasons": [],
        "viable": True,
    }


class ProductSelectionServiceTest(unittest.TestCase):
    def test_or_ingredients_match_either_alternative(self):
        self.assertTrue(product_matches_ingredient("pepperoni OR turkey", candidate("Organic Pepperoni")))
        self.assertTrue(product_matches_ingredient("pepperoni OR turkey", candidate("Organic Turkey")))
        self.assertFalse(product_matches_ingredient("pepperoni OR turkey", candidate("Organic Chicken")))

    def test_required_food_rule_is_not_selectable_when_missing(self):
        item = candidate(
            "Pepperoni",
            {"missing_required": ["must be organic"], "blocked_by": []},
        )

        _, _, skip_reasons, viable = score_candidate("pepperoni", item)

        self.assertFalse(viable)
        self.assertIn("Missing required food preference: must be organic", skip_reasons)

    def test_or_ingredients_are_searched_as_separate_terms(self):
        stores = {
            "aldi": {
                "label": "Aldi",
                "url": "https://www.aldi.us/store/aldi/s?k=",
            },
        }

        plan = build_product_download_plan(["pizza sauce OR marinara"], ["aldi"], stores)

        self.assertEqual([item["search_term"] for item in plan], ["pizza sauce", "marinara"])
        self.assertEqual(
            [item["search_url"] for item in plan],
            [
                "https://www.aldi.us/store/aldi/s?k=pizza+sauce",
                "https://www.aldi.us/store/aldi/s?k=marinara",
            ],
        )

    def test_shared_suffix_alternatives_keep_the_food_noun(self):
        self.assertEqual(
            ingredient_search_terms("low fat OR fat free Greek yoghurt"),
            ["low fat greek yogurt", "fat free Greek yogurt"],
        )


if __name__ == "__main__":
    unittest.main()
