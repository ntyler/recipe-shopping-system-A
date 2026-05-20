import json
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
        self.assertIn("You are a grocery product collection agent.", prompt)
        self.assertIn("Never return partial product lists.", prompt)
        self.assertIn('"best_result"', prompt)
        self.assertIn('"results"', prompt)

    def test_final_payload_includes_collection_agent_fields(self):
        item = candidate("Large White Eggs, 12 Count")
        item.update({
            "store_key": "aldi",
            "store_name": "Aldi",
            "brand": "Goldhen",
            "source_page_url": "https://www.aldi.us/store/aldi/s?k=eggs",
            "image_url": "https://example.com/eggs.png",
            "embedded_image_base64": "data:image/png;base64,AAAA",
            "package_size": "12 ct",
            "price": "$2.40",
            "raw_product_html_snippet": '<article><a href="/eggs">Large White Eggs</a><span>$2.40</span></article>',
        })
        product_service.apply_egg_product_metadata("eggs", item)

        payload = product_service.final_product_candidate_payload(item)

        self.assertEqual(payload["store_name"], "Aldi")
        self.assertEqual(payload["store_location"]["distance_miles"], 1)
        self.assertEqual(payload["source_page_url"], "https://www.aldi.us/store/aldi/s?k=eggs")
        self.assertEqual(payload["brand"], "Goldhen")
        self.assertEqual(payload["price_per_egg"], "$0.20/egg")
        self.assertIn("Large White Eggs", payload["raw_product_html_snippet"])
        self.assertTrue(payload["embedded_image_base64_captured"])
        self.assertIn("omitted from ChatGPT prompt", payload["embedded_image_base64"])

    def test_store_ranking_prompt_uses_extracted_cards_and_forbids_browsing(self):
        item = candidate("Organic Lemons 2 lb Bag")
        item.update({
            "id": "meijer-lemon",
            "store_key": "meijer",
            "store_name": "Meijer",
            "store_location_address": "5325 E Southport Rd, Indianapolis, IN 46237",
            "raw_product_html_snippet": '<li><a href="/shopping/product/organic-lemons">Organic Lemons 2 lb Bag</a><span>$6.99</span></li>',
            "rendered_page_html_excerpt": '<html><body><div>Organic Lemons 2 lb Bag $6.99 pickup</div></body></html>',
            "rendered_page_html_length": 72,
            "rendered_page_html_path": "D:/tmp/meijer-lemon.html",
            "card_text_excerpt": "Organic Lemons 2 lb Bag $6.99 2 lb",
        })

        prompt = product_service.build_store_product_ranking_prompt(
            "lemon",
            [item],
            "5905 Arlo Drive, Indianapolis, IN 46237",
            quantity_context={"display": "1 lemon", "sources": []},
        )

        self.assertIn("Selenium/undetected Chrome already opened the actual grocery website", prompt)
        self.assertIn("Do not browse, fetch, or infer from outside websites.", prompt)
        self.assertIn("Cleaned rendered page HTML from the fully loaded Selenium page", prompt)
        self.assertIn("D:/tmp/meijer-lemon.html", prompt)
        self.assertIn("raw_product_html_snippet", prompt)
        self.assertIn("Organic Lemons 2 lb Bag", prompt)
        self.assertIn("ranking_status", prompt)

    def test_rendered_html_prompt_uses_generic_browser_content(self):
        prompt = product_service.build_rendered_html_product_agent_prompt(
            "eggs",
            "Aldi",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            {"address": "Indianapolis, IN 46237", "distance_miles": 2.2},
            {
                "url": "https://example.com/search?q=eggs",
                "path": "D:/tmp/rendered.html",
                "prompt_html": "<article><a href='/eggs'>Large Eggs</a><span>$2.40</span></article>",
                "prompt_html_length": 75,
            },
            [
                {
                    "name": "Large Eggs",
                    "price": "$2.40",
                    "product_url": "https://example.com/eggs",
                    "text": "Large Eggs 12 ct $2.40",
                    "raw_product_html_snippet": "<article>Large Eggs 12 ct $2.40</article>",
                }
            ],
        )

        self.assertIn("generic browser agent already opened", prompt)
        self.assertIn("Do not browse, fetch, or infer from outside websites.", prompt)
        self.assertIn("Visible product blocks extracted generically", prompt)
        self.assertIn("Large Eggs", prompt)
        self.assertIn("best|alternative|rejected", prompt)

    def test_test_grab_prompt_is_isolated_to_aldi_eggs(self):
        prompt = product_service.build_test_grab_eggs_aldi_prompt(
            "eggs",
            "Aldi",
            "5905 Arlo Drive Apt 2213\nIndianapolis, IN 46237\nUSA",
            {"address": "Indianapolis, IN 46237", "distance_miles": 2.2},
            {
                "url": "https://www.aldi.us/store/aldi/s?k=eggs&zipcode=46237",
                "prompt_html": "<article>Simply Nature Organic Cage Free Brown Eggs 12 ct $4.69</article>",
                "localization": {
                    "verified": True,
                    "store_name": "Aldi",
                    "store_address": "Indianapolis, IN 46237",
                    "proof_of_store_selection": ["Visible store ZIP/postal code: 46237."],
                },
            },
            [
                {
                    "name": "Simply Nature Organic Cage Free Brown Eggs",
                    "price": "$4.69",
                    "product_url": "https://www.aldi.us/store/aldi/products/eggs",
                    "text": "Simply Nature Organic Cage Free Brown Eggs 12 ct $4.69",
                }
            ],
        )

        self.assertIn("TARGET PRODUCT:\nEdible grocery eggs", prompt)
        self.assertIn("5905 Arlo Drive Apt 2213", prompt)
        self.assertIn("STRICTLY EXCLUDE Easter eggs", prompt)
        self.assertIn("liquid eggs", prompt)
        self.assertIn("Simply Nature Organic Cage Free Brown Eggs", prompt)

    def test_rendered_html_agent_response_normalizes_candidates(self):
        data = {
            "best_product": {"product_name": "Large Eggs", "product_url": "/eggs"},
            "results": [
                {
                    "product_index": "1",
                    "product_name": "Large Eggs",
                    "product_url": "/eggs",
                    "price": "$2.40",
                    "confidence_score": 0.95,
                    "in_stock": "yes",
                },
                {
                    "product_name": "Liquid Egg Whites",
                    "ranking_status": "rejected",
                    "rejection_reason": "Not standard shell eggs.",
                    "in_stock": "true",
                },
            ],
        }

        normalized = product_service.normalize_rendered_html_product_agent_response(data)

        self.assertEqual(normalized["results"][0]["ranking_status"], "best")
        self.assertEqual(normalized["results"][0]["product_index"], 1)
        self.assertTrue(normalized["results"][0]["in_stock"])
        self.assertEqual(normalized["results"][1]["ranking_status"], "rejected")
        self.assertEqual(normalized["results"][1]["rejection_reason"], "Not standard shell eggs.")

    def test_rendered_store_context_requires_localization_proof(self):
        class FakeDriver:
            def execute_script(self, _):
                return "Results for egg National catalog"

        status = product_service.rendered_store_context_status(
            FakeDriver(),
            "aldi",
            "Aldi",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            {
                "name": "Aldi",
                "address": "Southport Rd, Indianapolis, IN 46237",
                "distance_miles": 2.2,
            },
        )

        self.assertFalse(status["ok"])
        self.assertIn("Localized store session could not be proven", status["message"])

    def test_rendered_store_context_accepts_store_banner_proof(self):
        class FakeDriver:
            def execute_script(self, _):
                return "Shopping at ALDI - GRE 73 - Indianapolis Pickup available 46237 Results for egg"

        status = product_service.rendered_store_context_status(
            FakeDriver(),
            "aldi",
            "Aldi",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            {
                "name": "Aldi",
                "address": "Southport Rd, Indianapolis, IN 46237",
                "distance_miles": 2.2,
                "pickup_enabled": True,
            },
        )

        self.assertTrue(status["ok"])
        self.assertTrue(status["proof_of_store_selection"])
        self.assertIn("46237", " ".join(status["proof_of_store_selection"]))

    def test_localized_inventory_failure_blocks_generic_fallback(self):
        self.assertTrue(product_service.localized_inventory_blocking_failure([
            "Aldi: Localized store session could not be proven from visible page text. Refusing to treat this as localized inventory."
        ]))
        self.assertFalse(product_service.localized_inventory_blocking_failure([
            "Aldi: no visible product cards were found on the rendered search page."
        ]))

    def test_egg_scoring_prefers_standard_shell_eggs(self):
        shell = candidate("Large White Eggs, 12 Count")
        shell["price"] = "$2.40"
        shell["package_size"] = "12 ct"
        shell["unit_price"] = ""
        shell["unit_price_value"] = None
        liquid = candidate("Liquid Egg Whites")
        liquid["price"] = "$3.99"
        liquid["package_size"] = "16 oz"

        shell_score, shell_reasons, _, shell_viable = score_candidate("eggs", shell)
        liquid_score, _, liquid_skip_reasons, liquid_viable = score_candidate("eggs", liquid)

        self.assertTrue(shell_viable)
        self.assertGreater(shell_score, liquid_score)
        self.assertIn("Standard shell egg carton match.", shell_reasons)
        self.assertFalse(liquid_viable)
        self.assertTrue(any("Excluded egg-product form detected" in reason for reason in liquid_skip_reasons))

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

    def test_store_result_separates_valid_and_rejected_products(self):
        valid = candidate("Large White Eggs, 12 Count")
        valid.update({
            "id": "valid-eggs",
            "store_key": "aldi",
            "store_name": "Aldi",
            "package_size": "12 ct",
            "price": "$2.40",
        })
        rejected = candidate("Liquid Egg Whites")
        rejected.update({
            "id": "liquid-eggs",
            "store_key": "aldi",
            "store_name": "Aldi",
            "package_size": "16 oz",
            "price": "$3.99",
        })

        record = build_product_choice_record_from_results(
            "eggs",
            [
                {
                    "index": 0,
                    "store_key": "aldi",
                    "store_name": "Aldi",
                    "candidates": [valid, rejected],
                    "skip_reasons": [],
                }
            ],
            "5905 Arlo Drive, Indianapolis, IN 46237",
        )
        store_result = record["store_results"]["aldi"]

        self.assertEqual(store_result["valid_candidate_count"], 1)
        self.assertEqual(store_result["rejected_candidate_count"], 1)
        self.assertEqual(store_result["rejected_products"][0]["product_name"], "Liquid Egg Whites")
        self.assertTrue(store_result["rejected_products"][0]["rejection_reasons"])
        self.assertEqual(record["validation_summary"]["rejected"], 1)
        self.assertTrue(any(stage["name"] == "Validation Layer" for stage in record["agent_stages"]))

    def test_product_results_file_is_written_with_hybrid_schema(self):
        with TemporaryDirectory() as tmp_dir:
            choices_file = Path(tmp_dir) / "product_choices.json"
            results_file = Path(tmp_dir) / "product_results.json"

            with patch.object(product_service, "PRODUCT_CHOICES_FILE", choices_file), patch.object(
                product_service,
                "PRODUCT_RESULTS_FILE",
                results_file,
            ):
                product_service.save_product_choices({"items": {"eggs": {"ingredient": "eggs"}}})
                payload = json.loads(results_file.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "hybrid-agentic-shopping-results/v1")
        self.assertIn("Planner Agent", payload["architecture"])
        self.assertIn("eggs", payload["items"])

    def test_manual_alternative_selection_persists_user_metadata(self):
        with TemporaryDirectory() as tmp_dir:
            choices_file = Path(tmp_dir) / "product_choices.json"
            results_file = Path(tmp_dir) / "product_results.json"
            item = candidate("Organic Lemons 2 lb Bag")
            item.update({
                "id": "meijer-lemons",
                "store_key": "meijer",
                "store_name": "Meijer",
                "product_url": "https://www.meijer.com/shopping/product/organic-lemons/1.html",
            })
            state = {
                "items": {
                    "lemon": {
                        "item_key": "lemon",
                        "ingredient": "lemon",
                        "candidates": [item],
                        "store_results": {},
                        "store_results_list": [],
                    }
                }
            }

            with patch.object(product_service, "PRODUCT_CHOICES_FILE", choices_file), patch.object(
                product_service,
                "PRODUCT_RESULTS_FILE",
                results_file,
            ), patch.object(product_service, "save_item_store"):
                product_service.save_product_choices(state)
                result = product_service.select_product_choice("lemon", "meijer-lemons", store_key="meijer")
                saved = product_service.load_product_choices()["items"]["lemon"]

        self.assertTrue(result["ok"])
        self.assertTrue(saved["selected_by_user"])
        self.assertTrue(saved["selected_product"]["selected_by_user"])
        self.assertTrue(saved["store_results"]["meijer"]["selected_by_user"])
        self.assertTrue(saved["selected_at"])

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
