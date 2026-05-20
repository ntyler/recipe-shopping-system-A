import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import PushShoppingList.services.product_selection_service as product_service
from PushShoppingList.services.product_selection_service import build_product_download_plan
from PushShoppingList.services.product_selection_service import build_product_choice_record_from_results
from PushShoppingList.services.product_selection_service import build_final_product_selection_prompt
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

    def test_quantity_context_prefers_single_item_over_bulk_bag_for_one(self):
        single = candidate("Lemon, large")
        single["price"] = "$0.66"
        single["package_size"] = ""
        single["unit_price"] = ""
        single["unit_price_value"] = None
        single["unit_price_unit"] = ""
        bulk = candidate("Lemons, 2 lb")
        bulk["price"] = "$3.99"
        bulk["package_size"] = "2 lb"
        bulk["unit_price"] = ""
        bulk["unit_price_value"] = None
        bulk["unit_price_unit"] = ""

        single_score, single_reasons, _, _ = score_candidate(
            "lemon",
            single,
            quantity_context={"display": "1", "sources": []},
        )
        bulk_score, _, bulk_skip_reasons, _ = score_candidate(
            "lemon",
            bulk,
            quantity_context={"display": "1", "sources": []},
        )

        self.assertGreater(single_score, bulk_score)
        self.assertIn("Single-item product fits the small total quantity needed.", single_reasons)
        self.assertIn("Bulk or weight-based package is likely more than the small count needed.", bulk_skip_reasons)

        manual_score, manual_reasons, _, _ = score_candidate(
            "lemon",
            candidate("Lemon, large"),
            quantity_context={"display": "1 lemon", "sources": []},
        )
        self.assertGreater(manual_score, bulk_score)
        self.assertIn("Single-item product fits the small total quantity needed.", manual_reasons)

    def test_final_prompt_includes_total_quantity(self):
        prompt = build_final_product_selection_prompt(
            "lemon",
            [candidate("Lemon, large")],
            "5905 Arlo Drive, Indianapolis, IN 46237",
            quantity_context={
                "display": "1",
                "sources": [{"label": "Recipe 1", "quantity": "1"}],
            },
        )

        self.assertIn("Total shopping-list quantity needed:\n1", prompt)
        self.assertIn("least practical excess/waste", prompt)

    def test_store_result_has_best_available_pick_when_no_candidate_is_viable(self):
        drink = candidate("Gatorade Lemon Lime")
        drink.update({
            "id": "drink",
            "store_key": "aldi",
            "store_name": "Aldi",
            "score": 60,
            "viable": False,
            "food_rule_status": {"missing_required": ["must be organic"], "blocked_by": []},
            "skip_reasons": ["Missing required food preference: must be organic"],
        })
        lemons = candidate("Lemons, Bag")
        lemons.update({
            "id": "lemons",
            "store_key": "aldi",
            "store_name": "Aldi",
            "score": -68,
            "viable": False,
            "package_size": "2 lb",
            "food_rule_status": {"missing_required": ["must be organic"], "blocked_by": []},
            "skip_reasons": ["Missing required food preference: must be organic"],
        })

        record = build_product_choice_record_from_results(
            "lemon",
            [
                {
                    "index": 0,
                    "store_key": "aldi",
                    "store_name": "Aldi",
                    "candidates": [drink, lemons],
                    "skip_reasons": [],
                }
            ],
            "5905 Arlo Drive, Indianapolis, IN 46237",
            quantity_context={"display": "1", "sources": []},
        )
        store_result = record["store_results"]["aldi"]

        self.assertEqual(store_result["best_product"]["product_name"], "Lemons, Bag")
        self.assertFalse(store_result["best_product_is_viable"])
        self.assertEqual(store_result["valid_candidate_count"], 0)
        self.assertEqual(record["selected_product_id"], "")

    def test_saved_choice_hydrates_store_pick_from_saved_candidates(self):
        lemons = candidate("Lemons, Bag")
        lemons.update({
            "id": "aldi-lemons",
            "store_key": "aldi",
            "store_name": "Aldi",
            "viable": False,
            "food_rule_status": {"missing_required": ["must be organic"], "blocked_by": []},
            "skip_reasons": ["Missing required food preference: must be organic"],
        })
        choice = {
            "item_key": "lemon",
            "ingredient": "lemon",
            "candidates": [lemons],
            "store_results_list": [
                {
                    "store_key": "aldi",
                    "store_name": "Aldi",
                    "candidate_count": 1,
                    "valid_candidate_count": 0,
                }
            ],
        }

        hydrated = product_service.hydrate_saved_product_choice(choice)
        store_result = hydrated["store_results"]["aldi"]

        self.assertEqual(store_result["best_product"]["product_name"], "Lemons, Bag")
        self.assertEqual(store_result["best_product_id"], "aldi-lemons")
        self.assertFalse(store_result["best_product_is_viable"])

    def test_progress_rows_include_selected_product_details(self):
        with TemporaryDirectory() as tmp_dir:
            progress_file = Path(tmp_dir) / "product_progress.json"

            with patch.object(product_service, "PRODUCT_PROGRESS_FILE", progress_file):
                product_service.start_product_progress(
                    [
                        {"index": 0, "ingredient": "lemon", "store_key": "aldi", "store_name": "Aldi"},
                        {"index": 1, "ingredient": "lemon", "store_key": "meijer", "store_name": "Meijer"},
                    ],
                    job_id="job-1",
                    max_workers=2,
                )
                product_service.update_product_progress_picks(
                    "job-1",
                    "lemon",
                    {
                        "selected_product": {
                            "id": "meijer-1",
                            "product_name": "Organic Lemons 2 lb Bag",
                            "store_key": "meijer",
                            "store_name": "Meijer",
                            "price": "$6.99",
                            "product_url": "https://www.meijer.com/shopping/product/organic-lemons-2-lb-bag/60504952155.html",
                        },
                        "store_results_list": [
                            {
                                "store_key": "aldi",
                                "best_product": {
                                    "id": "aldi-1",
                                    "product_name": "Lemons",
                                    "store_key": "aldi",
                                    "store_name": "Aldi",
                                    "price": "$3.99",
                                    "product_url": "https://www.aldi.us/product/lemons",
                                },
                            },
                            {
                                "store_key": "meijer",
                                "best_product": {
                                    "id": "meijer-1",
                                    "product_name": "Organic Lemons 2 lb Bag",
                                    "store_key": "meijer",
                                    "store_name": "Meijer",
                                    "price": "$6.99",
                                    "product_url": "https://www.meijer.com/shopping/product/organic-lemons-2-lb-bag/60504952155.html",
                                },
                            },
                        ],
                    },
                )

                progress = product_service.load_product_progress()

        self.assertEqual(progress["downloads"][0]["selected_name"], "Lemons")
        self.assertFalse(progress["downloads"][0]["selected_is_overall"])
        self.assertEqual(progress["downloads"][1]["selected_name"], "Organic Lemons 2 lb Bag")
        self.assertEqual(progress["downloads"][1]["selected_price"], "$6.99")
        self.assertTrue(progress["downloads"][1]["selected_is_overall"])
        self.assertEqual(
            progress["downloads"][1]["selected_product_url"],
            "https://www.meijer.com/shopping/product/organic-lemons-2-lb-bag/60504952155.html",
        )


if __name__ == "__main__":
    unittest.main()
