import unittest

from PushShoppingList.services.product_selection_service import build_product_download_plan
from PushShoppingList.services.product_selection_service import candidate_has_direct_product_url
from PushShoppingList.services.product_selection_service import home_address_geocode_queries
from PushShoppingList.services.product_selection_service import ingredient_search_terms
from PushShoppingList.services.product_selection_service import parse_meijer_reader_product_candidates
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

    def test_search_page_link_is_not_selectable_as_product(self):
        item = candidate("Pepperoni")
        item["product_url"] = item["search_url"]

        _, _, skip_reasons, viable = score_candidate("pepperoni", item)

        self.assertFalse(viable)
        self.assertFalse(candidate_has_direct_product_url(item))
        self.assertIn("A direct product URL was not available; search-page links are not selectable.", skip_reasons)

    def test_chatgpt_mismatch_is_not_selectable(self):
        item = candidate("Organic Lemon")
        item["chatgpt_analysis"] = {
            "status": "done",
            "is_product_page": True,
            "is_correct_product": False,
            "ingredient_match_confidence": 0.1,
            "confidence": 0.9,
        }

        _, _, skip_reasons, viable = score_candidate("lemon", item)

        self.assertFalse(viable)
        self.assertIn("ChatGPT analysis says the loaded page does not match the shopping item.", skip_reasons)

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

    def test_plural_product_name_matches_singular_ingredient(self):
        self.assertTrue(product_matches_ingredient("lemon", candidate("Lemons, 2 lb")))

    def test_meijer_reader_search_returns_direct_product_candidates(self):
        markdown = """
[![Image 20](https://www.meijer.com/content/dam/meijer/product/0605/04/9017/06/0605049017066_1_A1C1_0200.jpg) ## Lemons, 2 lb Original price $3.99/bag (19) 3.2 out of 5 stars. 19 reviews](https://www.meijer.com/shopping/product/lemons-2-lb/60504901706.html)
"""
        products = parse_meijer_reader_product_candidates(
            markdown,
            "lemon",
            "meijer",
            "Meijer",
            "https://www.meijer.com/shopping/search.html?text=lemon",
            "5905 Arlo Drive, Indianapolis, IN 46237, United States",
            None,
            {"name": "Meijer", "distance_miles": 2.1},
        )

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["product_name"], "Lemons, 2 lb")
        self.assertEqual(products[0]["price"], "Original price $3.99/bag")
        self.assertEqual(
            products[0]["product_url"],
            "https://www.meijer.com/shopping/product/lemons-2-lb/60504901706.html",
        )

    def test_address_geocode_queries_remove_apartment_and_county(self):
        queries = home_address_geocode_queries(
            "5905 Arlo Drive Apt 2213, Indianapolis, Marion County, IN 46237, United States"
        )

        self.assertIn("5905 Arlo Drive, Indianapolis, IN 46237, United States", queries)


if __name__ == "__main__":
    unittest.main()
