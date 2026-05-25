import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import PushShoppingList.services.product_selection_service as product_service
import PushShoppingList.scripts.test_grab_aldi_eggs as test_grab_script
from PushShoppingList.scripts.stores import aldi_store
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

    def test_strong_rendered_card_can_rank_without_detail_page(self):
        item = candidate("Simply Nature Organic Bread")
        item.update({
            "source": "browser-visible-card",
            "detail_evaluated": False,
            "product_url": "https://www.aldi.us/store/aldi/products/25350346-simply-nature-seedtastic-organic-bread-27-oz",
            "search_url": "https://www.aldi.us/store/aldi/s?k=bread",
            "card_text_excerpt": "Simply Nature Organic Bread 27 oz Many in stock Current price: $3.99",
            "raw_product_html_snippet": "<li>Simply Nature Organic Bread 27 oz Many in stock $3.99</li>",
            "skip_reasons": ["Full product page was not evaluated because the per-store detail limit is 4."],
        })

        _, reasons, skip_reasons, viable = score_candidate("bread", item)

        self.assertTrue(viable)
        self.assertIn("Visible product card has enough direct product evidence for ranking.", reasons)
        self.assertNotIn("Full product page was not successfully evaluated.", skip_reasons)

    def test_generic_card_name_still_requires_detail_page_confirmation(self):
        item = candidate("Bread")
        item.update({
            "source": "browser-visible-card",
            "detail_evaluated": False,
            "product_url": "https://www.aldi.us/store/aldi/products/19876330-bake-shop-large-croissants-12-oz",
            "search_url": "https://www.aldi.us/store/aldi/s?k=bread",
            "card_text_excerpt": "Bread Current price: $2.79 Large Croissants 12 oz Many in stock",
        })

        _, _, skip_reasons, viable = score_candidate("bread", item)

        self.assertFalse(viable)
        self.assertIn("Full product page was not successfully evaluated.", skip_reasons)

    def test_rankable_rendered_cards_skip_detail_page_opens(self):
        item = candidate("Simply Nature Organic Bread")
        item.update({
            "source": "browser-visible-card",
            "detail_evaluated": False,
            "product_url": "https://www.aldi.us/store/aldi/products/25350346-simply-nature-seedtastic-organic-bread-27-oz",
            "search_url": "https://www.aldi.us/store/aldi/s?k=bread",
            "card_text_excerpt": "Simply Nature Organic Bread 27 oz Many in stock Current price: $3.99",
            "raw_product_html_snippet": "<li>Simply Nature Organic Bread 27 oz Many in stock $3.99</li>",
        })

        with patch.object(product_service, "enrich_product_candidate_from_page") as detail_mock:
            enriched = product_service.enrich_product_candidates_from_pages(
                [item],
                "bread",
                "Aldi",
            )

        detail_mock.assert_not_called()
        self.assertFalse(enriched[0]["detail_evaluated"])
        self.assertFalse(enriched[0]["shortlisted_for_detail"])
        self.assertIn("rendered product cards had enough direct evidence", enriched[0]["detail_fetch"]["reason"])

    def test_product_image_embedding_is_limited_by_default(self):
        items = []
        for index in range(14):
            item = candidate(f"Organic Bread {index}")
            item.update({
                "id": f"bread-{index}",
                "image_url": f"https://example.com/bread-{index}.jpg",
                "embedded_image_base64": "",
            })
            items.append(item)

        with patch.object(product_service, "product_image_data_uri", return_value="data:image/png;base64,AAAA") as image_mock:
            enriched = product_service.embed_product_candidate_images(items)

        self.assertEqual(image_mock.call_count, 12)
        self.assertEqual(sum(1 for item in enriched if item.get("embedded_image_base64")), 12)

    def test_rendered_html_chatgpt_skips_when_visible_cards_are_rankable(self):
        items = []
        for index in range(3):
            item = candidate(f"Simply Nature Organic Bread {index}")
            item.update({
                "source": "browser-visible-card",
                "detail_evaluated": False,
                "product_url": f"https://www.aldi.us/store/aldi/products/2535034{index}-simply-nature-organic-bread-27-oz",
                "search_url": "https://www.aldi.us/store/aldi/s?k=bread",
                "card_text_excerpt": f"Simply Nature Organic Bread {index} 27 oz Many in stock Current price: $3.99",
            })
            items.append(item)

        self.assertTrue(product_service.should_skip_rendered_html_chatgpt("bread", items))

    def test_candidate_limit_keeps_relevant_rendered_anchor_after_visible_cap(self):
        visible_candidates = []
        for index in range(4):
            item = candidate(f"Snack Mix {index}")
            item.update({
                "source": "browser-visible-card",
                "id": f"visible-{index}",
                "product_url": f"https://www.aldi.us/store/aldi/products/snack-{index}",
                "search_url": "https://www.aldi.us/store/aldi/s?k=bread",
            })
            visible_candidates.append(item)

        rendered_anchor = candidate("Simply Nature Seedtastic Organic Thin-Sliced Bread")
        rendered_anchor.update({
            "source": "html-anchor",
            "id": "rendered-bread",
            "product_url": "https://www.aldi.us/store/aldi/products/24735124-simply-nature-seedtastic-thin-sliced-organic-bread-20-4-oz",
            "search_url": "https://www.aldi.us/store/aldi/s?k=bread",
            "card_text_excerpt": "Simply Nature Seedtastic Organic Thin-Sliced Bread 20.4 oz Many in stock Current price: $3.85",
        })

        limited = product_service.limit_product_candidates_for_search(
            "bread",
            visible_candidates + [rendered_anchor],
            limit=4,
        )

        self.assertEqual(len(limited), 4)
        self.assertIn(
            "Simply Nature Seedtastic Organic Thin-Sliced Bread",
            [item["product_name"] for item in limited],
        )

    def test_rendered_scroll_loop_uses_configured_default_cap(self):
        class FakeDriver:
            def __init__(self):
                self.scroll_calls = 0

            def execute_script(self, *_args):
                self.scroll_calls += 1
                return False

        driver = FakeDriver()

        with patch.object(product_service, "extract_visible_product_cards_from_browser", return_value=[{"name": "chips"}]), patch.object(
            product_service,
            "wait_for_browser_text_to_settle",
        ) as settle_mock:
            product_service.scroll_rendered_product_results_until_stable(driver)

        self.assertEqual(settle_mock.call_count, product_service.product_rendered_scroll_max_passes())
        self.assertLessEqual(settle_mock.call_count, 18)

    def test_rendered_scroll_loop_does_not_stop_at_target_before_bottom(self):
        class FakeDriver:
            def execute_script(self, *_args):
                return False

        enough_cards = [{"name": f"chips {index}"} for index in range(product_service.product_rendered_scroll_target_cards())]

        with patch.object(
            product_service,
            "extract_visible_product_cards_from_browser",
            return_value=enough_cards,
        ) as extract_mock, patch.object(product_service, "wait_for_browser_text_to_settle"):
            count = product_service.scroll_rendered_product_results_until_stable(FakeDriver())

        self.assertEqual(count, len(enough_cards))
        self.assertEqual(extract_mock.call_count, product_service.product_rendered_scroll_max_passes())

    def test_rendered_scroll_loop_stops_after_bottom_is_stable(self):
        class FakeDriver:
            def execute_script(self, *_args):
                return True

        cards = [{"name": "bread"}]

        with patch.object(
            product_service,
            "extract_visible_product_cards_from_browser",
            return_value=cards,
        ) as extract_mock, patch.object(product_service, "wait_for_browser_text_to_settle"), patch.object(
            product_service,
            "click_rendered_load_more_button",
            return_value=False,
        ):
            count = product_service.scroll_rendered_product_results_until_stable(FakeDriver())

        self.assertEqual(count, len(cards))
        self.assertEqual(extract_mock.call_count, 3)

    def test_rendered_scroll_loop_clicks_load_more_before_settling(self):
        class FakeDriver:
            def execute_script(self, *_args):
                return True

        card_batches = [
            [{"name": "bread 1"}],
            [{"name": "bread 1"}, {"name": "bread 2"}],
            [{"name": "bread 1"}, {"name": "bread 2"}],
        ]

        with patch.object(
            product_service,
            "extract_visible_product_cards_from_browser",
            side_effect=card_batches,
        ) as extract_mock, patch.object(product_service, "wait_for_browser_text_to_settle"), patch.object(
            product_service,
            "click_rendered_load_more_button",
            side_effect=[True, False, False],
        ) as click_mock:
            count = product_service.scroll_rendered_product_results_until_stable(
                FakeDriver(),
                max_passes=3,
                stable_passes=1,
            )

        self.assertEqual(count, 2)
        self.assertEqual(click_mock.call_count, 3)
        self.assertEqual(extract_mock.call_count, 3)

    def test_run_find_nearest_stores_button_route_runs_resolver(self):
        from PushShoppingList.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        saved_address = {"full_address": "5905 Arlo Drive, Indianapolis, IN 46237"}
        nearest_result = {
            "ok": True,
            "home_address": saved_address["full_address"],
            "store_locations": {
                "aldi": {
                    "name": "Aldi",
                    "address": "Aldi, Indianapolis, IN 46237",
                    "distance_miles": 1.95,
                }
            },
        }

        with patch("PushShoppingList.routes.main_routes.save_home_address", return_value=saved_address), patch(
            "PushShoppingList.routes.main_routes.resolve_nearest_stores_for_home_address",
            return_value=nearest_result,
        ) as resolver:
            response = app.test_client().post(
                "/save_home_address",
                data={"action": "run_find_nearest"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/#storeOptionsSection"))
        resolver.assert_called_once_with(saved_address, search_radius_miles=None)

    def test_run_find_nearest_stores_ajax_returns_warning_without_jump_failure(self):
        from PushShoppingList.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        saved_address = {"full_address": "5905 Arlo Drive, Indianapolis, IN 46237"}
        nearest_result = {
            "ok": False,
            "saved": False,
            "home_address": saved_address["full_address"],
            "store_locations": {},
            "error": "Full Address could not be geocoded.",
        }

        with patch("PushShoppingList.routes.main_routes.save_home_address", return_value=saved_address), patch(
            "PushShoppingList.routes.main_routes.resolve_nearest_stores_for_home_address",
            return_value=nearest_result,
        ):
            response = app.test_client().post(
                "/save_home_address",
                data={"action": "run_find_nearest", "ajax": "1"},
                headers={"X-Requested-With": "fetch"},
            )

        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["warning"], "Full Address could not be geocoded.")
        self.assertFalse(data["nearest_store_results"]["saved"])

    def test_run_find_nearest_stores_passes_radius_to_resolver(self):
        from PushShoppingList.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        saved_address = {"full_address": "5905 Arlo Drive, Indianapolis, IN 46237"}
        nearest_result = {
            "ok": True,
            "home_address": saved_address["full_address"],
            "search_radius_miles": 15,
            "store_locations": {},
        }

        with patch("PushShoppingList.routes.main_routes.save_home_address", return_value=saved_address), patch(
            "PushShoppingList.routes.main_routes.resolve_nearest_stores_for_home_address",
            return_value=nearest_result,
        ) as resolver:
            response = app.test_client().post(
                "/save_home_address",
                data={
                    "action": "run_find_nearest",
                    "ajax": "1",
                    "store_search_radius_miles": "15",
                },
                headers={"X-Requested-With": "fetch"},
            )

        self.assertEqual(response.status_code, 200)
        resolver.assert_called_once_with(saved_address, search_radius_miles="15")

    def test_app_js_uses_form_action_attribute_for_fetches(self):
        js_path = Path("PushShoppingList/static/js/app.js")
        script = js_path.read_text(encoding="utf-8")

        self.assertIn("function formActionUrl(form)", script)
        self.assertNotIn("fetch(form.action", script)

    def test_store_options_stays_below_home_address_in_main_page_flow(self):
        index_template = Path("PushShoppingList/templates/index.html").read_text(encoding="utf-8")

        store_options_index = index_template.index('{% include "sections/store_options.html" %}')
        enter_recipe_index = index_template.index('{% include "sections/enter_recipe_links.html" %}')
        home_address_index = index_template.index('{% include "sections/home_address.html" %}')

        self.assertGreater(store_options_index, enter_recipe_index)
        self.assertGreater(store_options_index, home_address_index)

    def test_cookbooks_section_sits_between_recipe_log_and_rules(self):
        index_template = Path("PushShoppingList/templates/index.html").read_text(encoding="utf-8")
        cookbook_template = Path("PushShoppingList/templates/sections/cookbooks.html").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        recipe_log_index = index_template.index('{% include "sections/current_recipe_url_log.html" %}')
        cookbooks_index = index_template.index('{% include "sections/cookbooks.html" %}')
        rules_index = index_template.index('{% include "sections/rules.html" %}')

        self.assertGreater(cookbooks_index, recipe_log_index)
        self.assertLess(cookbooks_index, rules_index)
        self.assertIn('id="cookbooksCard"', cookbook_template)
        self.assertIn("Move Selected", cookbook_template)
        self.assertIn("data-cookbook-recipe-checkbox", cookbook_template)
        self.assertIn("Equipment", cookbook_template)
        self.assertIn("Instructions", cookbook_template)
        self.assertIn("data-cookbook-recipe-toggle", cookbook_template)
        self.assertIn("data-cookbook-restore-checkbox", cookbook_template)
        self.assertIn("restoreCookbookRecipes(event)", cookbook_template)
        self.assertIn("openCookbookNameEditor(this)", cookbook_template)
        self.assertIn("cookbookNameEditorModal", cookbook_template)
        self.assertIn("cookbookOverwriteModal", cookbook_template)
        self.assertIn("cookbookRecipeSearchInput", cookbook_template)
        self.assertIn("data-cookbook-toggle", cookbook_template)
        self.assertIn("data-cookbook-card", cookbook_template)
        self.assertIn("resolveCookbookOverwritePrompt(false)", cookbook_template)
        self.assertIn("openRecipeEditor(this)", cookbook_template)
        self.assertIn("recipe-archive-pdf-btn cookbook-recipe-pdf-btn", cookbook_template)
        self.assertIn("/api/cookbooks/restore_recipes", cookbook_template)
        self.assertIn("/rename", script)
        self.assertIn("cookbook_recipe_exists", script)
        self.assertIn("function createCookbook", script)
        self.assertIn("function moveRecipesToCookbook", script)
        self.assertIn("function toggleCookbookRecipeDetails", script)
        self.assertIn("function restoreCookbookRecipes", script)
        self.assertIn("function promptCookbookOverwrite", script)
        self.assertIn("function toggleCookbookCard", script)
        self.assertIn("function applyCookbookRecipeSearch", script)
        self.assertIn("cookbook-card-collapse:", script)
        self.assertIn("cookbook-recipe-search", script)
        self.assertIn('savedState !== "expanded"', script)
        self.assertIn("function saveCookbookName", script)
        self.assertIn("restoreCookbookRecipeCollapseState", script)
        self.assertIn('replaceSectionFromPage(nextPage, "#editItemsSection")', script)
        self.assertIn("/api/cookbooks/move_recipes", cookbook_template)
        self.assertIn('replaceSectionFromPage(nextPage, "#cookbooksCard")', script)
        self.assertIn(".cookbooks-layout", css)
        self.assertIn(".cookbook-edit-btn", css)
        self.assertIn(".cookbook-name-modal-backdrop", css)
        self.assertIn(".cookbook-overwrite-list", css)
        self.assertIn(".cookbook-card-toggle-btn", css)
        self.assertIn(".cookbook-card-collapsed .cookbook-card-body", css)
        self.assertIn(".cookbook-recipe-search", css)
        self.assertIn(".cookbook-restore-btn", css)
        self.assertIn(".cookbook-recipe-details.collapsed", css)

    def test_cookbook_move_reassigns_recipes_with_details_between_cookbooks(self):
        from PushShoppingList.services import cookbook_service

        with TemporaryDirectory() as temp_dir, patch.object(
            cookbook_service,
            "COOKBOOKS_FILE",
            Path(temp_dir) / "cookbooks.json",
        ):
            recipe_rows = [{
                "number": 1,
                "name": "Skillet Chili",
                "url": "https://example.com/chili",
                "source_href": "https://example.com/chili",
                "source_display_url": "https://example.com/chili",
                "quantity": 1,
                "archive_pdf_available": True,
                "cover_image": {
                    "url": "https://example.com/chili.jpg",
                    "alt": "Skillet Chili",
                    "source": "structured_data",
                },
                "base_servings": "4 servings",
                "scaled_servings": "4 servings",
                "equipment_items": ["Dutch oven"],
                "instruction_items": ["Simmer until thick."],
                "sections": {
                    "MISC": [{
                        "name": "canned white beans",
                        "display_name": "canned white beans",
                        "quantity": "2",
                        "unit": "cans",
                        "base_display": "2 cans",
                        "quantity_display": "2 cans",
                    }],
                },
            }]

            cookbook_service.create_cookbook("Dinner")
            cookbook_service.create_cookbook("Baking")

            cookbook_service.move_recipes_to_cookbook(
                "dinner",
                ["https://example.com/chili"],
                recipe_rows,
            )
            cookbook_service.move_recipes_to_cookbook(
                "baking",
                ["https://example.com/chili"],
                recipe_rows,
            )

            data = cookbook_service.load_cookbooks()
            dinner = next(cookbook for cookbook in data["cookbooks"] if cookbook["id"] == "dinner")
            baking = next(cookbook for cookbook in data["cookbooks"] if cookbook["id"] == "baking")
            baking_recipe = baking["recipes"][0]

            self.assertEqual(dinner["recipes"], [])
            self.assertEqual(baking_recipe["name"], "Skillet Chili")
            self.assertTrue(baking_recipe["archive_pdf_available"])
            self.assertEqual(baking_recipe["cover_image"]["url"], "https://example.com/chili.jpg")
            self.assertEqual(baking_recipe["equipment_items"], ["Dutch oven"])
            self.assertEqual(baking_recipe["instruction_items"], ["Simmer until thick."])
            self.assertEqual(baking_recipe["sections"]["MISC"][0]["display_name"], "canned white beans")

            view = cookbook_service.cookbook_view([])
            baking_view = next(cookbook for cookbook in view["cookbooks"] if cookbook["id"] == "baking")
            self.assertEqual(baking_view["recipes"][0]["sections"]["MISC"][0]["quantity_display"], "2 cans")

    def test_cookbook_view_for_render_adds_cover_image_src_for_saved_recipes(self):
        from PushShoppingList.app import create_app
        from PushShoppingList.routes import main_routes
        from PushShoppingList.services import cookbook_service

        with TemporaryDirectory() as temp_dir, patch.object(
            cookbook_service,
            "COOKBOOKS_FILE",
            Path(temp_dir) / "cookbooks.json",
        ):
            recipe_rows = [{
                "name": "Skillet Chili",
                "url": "https://example.com/chili",
                "source_href": "https://example.com/chili",
                "source_display_url": "https://example.com/chili",
                "cover_image": {
                    "url": "https://example.com/chili.jpg",
                    "alt": "Skillet Chili",
                },
            }]

            cookbook_service.create_cookbook("Dinner")
            cookbook_service.move_recipes_to_cookbook(
                "dinner",
                ["https://example.com/chili"],
                recipe_rows,
            )

            app = create_app()
            app.config["TESTING"] = True
            with app.test_request_context("/"):
                view = main_routes.cookbook_view_for_render([])

            dinner = view["cookbooks"][0]
            recipe = dinner["recipes"][0]
            self.assertEqual(recipe["cover_image"]["src"], "https://example.com/chili.jpg")
            self.assertEqual(recipe["cover_image"]["alt"], "Skillet Chili")

    def test_cookbook_move_requires_overwrite_for_existing_target_recipe(self):
        from PushShoppingList.services import cookbook_service

        with TemporaryDirectory() as temp_dir, patch.object(
            cookbook_service,
            "COOKBOOKS_FILE",
            Path(temp_dir) / "cookbooks.json",
        ):
            cookbook_service.create_cookbook("Dinner")
            cookbook_service.move_recipes_to_cookbook(
                "dinner",
                ["https://example.com/chili"],
                [{"name": "Skillet Chili", "url": "https://example.com/chili"}],
            )

            with self.assertRaises(cookbook_service.CookbookRecipeConflict) as err:
                cookbook_service.move_recipes_to_cookbook(
                    "dinner",
                    ["https://example.com/chili"],
                    [{"name": "Updated Chili", "url": "https://example.com/chili"}],
                )

            self.assertEqual(err.exception.conflicts[0]["name"], "Updated Chili")
            data = cookbook_service.load_cookbooks()
            self.assertEqual(data["cookbooks"][0]["recipes"][0]["name"], "Skillet Chili")

            cookbook_service.move_recipes_to_cookbook(
                "dinner",
                ["https://example.com/chili"],
                [{"name": "Updated Chili", "url": "https://example.com/chili"}],
                overwrite_existing=True,
            )

            data = cookbook_service.load_cookbooks()
            self.assertEqual(data["cookbooks"][0]["recipes"][0]["name"], "Updated Chili")

    def test_cookbook_rename_updates_name_without_losing_recipes(self):
        from PushShoppingList.services import cookbook_service

        with TemporaryDirectory() as temp_dir, patch.object(
            cookbook_service,
            "COOKBOOKS_FILE",
            Path(temp_dir) / "cookbooks.json",
        ):
            cookbook_service.create_cookbook("Dinner")
            cookbook_service.move_recipes_to_cookbook(
                "dinner",
                ["https://example.com/chili"],
                [{"name": "Skillet Chili", "url": "https://example.com/chili"}],
            )

            cookbook_service.rename_cookbook("dinner", "Weeknight Dinners")

            data = cookbook_service.load_cookbooks()
            cookbook = data["cookbooks"][0]
            self.assertEqual(cookbook["id"], "dinner")
            self.assertEqual(cookbook["name"], "Weeknight Dinners")
            self.assertEqual(cookbook["recipes"][0]["name"], "Skillet Chili")

            with self.assertRaises(ValueError):
                cookbook_service.create_cookbook("Weeknight Dinners")

    def test_cookbook_restore_adds_recipe_log_and_shopping_items(self):
        from PushShoppingList.routes import main_routes
        from PushShoppingList.services import cookbook_service
        from PushShoppingList.services import recipe_ingredient_service
        from PushShoppingList.services import recipe_url_service
        from PushShoppingList.services import shopping_list_service

        with TemporaryDirectory() as temp_dir, patch.object(
            cookbook_service,
            "COOKBOOKS_FILE",
            Path(temp_dir) / "cookbooks.json",
        ), patch.object(
            shopping_list_service,
            "SHOPPING_LIST_FILE",
            Path(temp_dir) / "shopping_list.txt",
        ), patch.object(
            recipe_url_service,
            "URLS_FILE",
            Path(temp_dir) / "urls.txt",
        ), patch.object(
            recipe_url_service,
            "RECIPE_INGREDIENTS_FILE",
            Path(temp_dir) / "recipe_ingredients.json",
        ), patch.object(
            recipe_ingredient_service,
            "RECIPE_INGREDIENTS_FILE",
            Path(temp_dir) / "recipe_ingredients.json",
        ), patch.object(main_routes, "sort_ingredients"):
            recipe_rows = [{
                "name": "Skillet Chili",
                "url": "https://example.com/chili",
                "source_href": "https://example.com/chili",
                "source_display_url": "https://example.com/chili",
                "quantity": 2,
                "archive_pdf_available": True,
                "cover_image": {
                    "url": "https://example.com/chili.jpg",
                    "alt": "Skillet Chili",
                    "source": "structured_data",
                },
                "equipment_items": ["Dutch oven"],
                "instruction_items": ["Simmer until thick."],
                "sections": {
                    "MISC": [{
                        "name": "canned white beans",
                        "display_name": "canned white beans",
                        "base_display": "2 cans",
                    }],
                },
            }]

            cookbook_service.create_cookbook("Dinner")
            cookbook_service.move_recipes_to_cookbook(
                "dinner",
                ["https://example.com/chili"],
                recipe_rows,
            )

            result = main_routes.restore_cookbook_recipes_to_log(["https://example.com/chili"])

            self.assertEqual(result["restored_count"], 1)
            self.assertEqual(recipe_url_service.read_recipe_urls(), ["https://example.com/chili"])
            self.assertEqual(shopping_list_service.load_items(), ["canned white beans"])

            recipe_meta = recipe_ingredient_service.load_recipe_ingredients()
            chili_meta = recipe_meta[recipe_url_service.normalize_recipe_url_key("https://example.com/chili")]
            self.assertEqual(chili_meta["name"], "Skillet Chili")
            self.assertEqual(chili_meta["quantity"], 2)
            self.assertEqual(chili_meta["cover_image"]["url"], "https://example.com/chili.jpg")
            self.assertEqual(chili_meta["ingredients"], ["canned white beans"])

    def test_recipe_cover_image_is_extracted_from_recipe_structured_data(self):
        from PushShoppingList.services.recipe_extract_service import extract_recipe_from_structured_data

        html = """
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Recipe",
          "name": "Crispy Falafel",
          "image": [
            {
              "@type": "ImageObject",
              "url": "/images/falafel.jpg",
              "width": 1200,
              "height": 800
            }
          ],
          "recipeYield": "4 servings",
          "recipeIngredient": ["1 cup chickpeas"],
          "recipeInstructions": [
            {"@type": "HowToStep", "text": "Bake until crisp."}
          ]
        }
        </script>
        </head><body></body></html>
        """

        data = extract_recipe_from_structured_data("https://example.com/recipes/falafel", html)

        self.assertEqual(data["cover_image"]["url"], "https://example.com/images/falafel.jpg")
        self.assertEqual(data["cover_image"]["alt"], "Crispy Falafel")

    def test_recipe_cover_image_falls_back_to_open_graph_image(self):
        from PushShoppingList.services.recipe_extract_service import extract_recipe_cover_image_from_html

        html = '<meta property="og:image" content="/covers/finished-dish.jpg">'
        cover_image = extract_recipe_cover_image_from_html(
            html,
            "https://example.com/recipes/dinner",
            fallback_alt="Dinner",
        )

        self.assertEqual(cover_image["url"], "https://example.com/covers/finished-dish.jpg")
        self.assertEqual(cover_image["source"], "html_metadata")

    def test_screen_settings_section_is_available_at_top_of_page(self):
        index_template = Path("PushShoppingList/templates/index.html").read_text(encoding="utf-8")
        screen_template = Path("PushShoppingList/templates/sections/screen_settings.html").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

        self.assertLess(
            index_template.index('{% include "sections/screen_settings.html" %}'),
            index_template.index('<main id="appContent"'),
        )
        self.assertIn("Screen Settings", screen_template)
        self.assertIn('data-screen-mode-button="phone"', screen_template)
        self.assertIn('id="screenPreviewFrame"', screen_template)
        self.assertIn("body.screen-preview-active #appContent", css)
        self.assertIn("screen_preview_frame", script)
        self.assertIn("setScreenPreviewMode", script)

    def test_recipe_cover_images_can_open_lightbox(self):
        current_recipe_template = Path(
            "PushShoppingList/templates/sections/current_recipe_url_log.html"
        ).read_text(encoding="utf-8")
        cookbook_template = Path("PushShoppingList/templates/sections/cookbooks.html").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn("recipe-cover-image recipe-url-summary-cover", current_recipe_template)
        self.assertIn("recipe-cover-image cookbook-recipe-cover", cookbook_template)
        self.assertLess(
            cookbook_template.index("cookbook-recipe-servings"),
            cookbook_template.index("recipe-cover-image cookbook-recipe-cover"),
        )
        self.assertIn("recipe-image-lightbox", css)
        self.assertIn("openRecipeImageLightbox", script)
        self.assertIn("handleRecipeCoverImageClick", script)
        self.assertIn("decorateRecipeCoverImages", script)

    def test_store_radius_toolbar_lives_in_store_options(self):
        home_template = Path("PushShoppingList/templates/sections/home_address.html").read_text(encoding="utf-8")
        store_template = Path("PushShoppingList/templates/sections/store_options.html").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertNotIn("store-radius-control", home_template)
        self.assertIn("home-address-actions-copy", home_template)
        self.assertIn("store-options-sticky-stack", store_template)
        self.assertIn("store-options-sticky-toolbar", store_template)
        self.assertIn("store-options-title-toggle", store_template)
        self.assertIn('form="homeAddressForm"', store_template)
        self.assertIn("storeSearchRadiusMiles", store_template)
        self.assertIn("adjustStoreSearchRadius(-1)", store_template)
        self.assertIn("adjustStoreSearchRadius(1)", store_template)
        self.assertIn("position: sticky", css)
        self.assertIn(".store-options-sticky-stack", css)
        self.assertIn(".store-options-title-toggle", css)
        self.assertIn(".store-options-sticky-toolbar", css)
        self.assertIn(".store-radius-stepper", css)
        self.assertNotIn("#storeOptionsSection.card-collapsed .store-options-sticky-toolbar", css)

    def test_store_options_sticky_bar_matches_display_view_alignment(self):
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn(".store-options-sticky-stack", css)
        self.assertIn("top: 0", css)
        self.assertIn("background: #111414", css)
        self.assertIn("border: 1px solid #3a3a3a", css)
        self.assertIn(".store-add-sticky-action.is-visible", css)
        self.assertIn("opacity 160ms ease", css)
        self.assertIn(".store-options-title-toggle:hover", css)
        self.assertIn('key === "store-options" && isCollapsed', script)
        self.assertIn("inlineCanTakeOver", script)
        self.assertIn('document.querySelector(".store-add-inline-action")', script)
        self.assertIn("function scrollStoreOptionsIntoView", script)
        self.assertIn('document.getElementById("storeOptionsSection")', script)
        self.assertIn("scrollIntoView", script)
        self.assertIn("function adjustStoreSearchRadius", script)
        self.assertIn('document.getElementById("storeSearchRadiusMiles")', script)

    def test_rules_hide_scrolls_back_to_rules_card(self):
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn('key === "rules" && isCollapsed', script)
        self.assertIn("function scrollRulesIntoView", script)
        self.assertIn('scrollCardIntoView("rulesCard")', script)
        self.assertIn("function scrollCardIntoView", script)
        self.assertIn("scrollIntoView", script)

    def test_store_options_toolbar_only_runs_nearest_stores(self):
        home_template = Path("PushShoppingList/templates/sections/home_address.html").read_text(encoding="utf-8")
        store_template = Path("PushShoppingList/templates/sections/store_options.html").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn("Save Address", home_template)
        self.assertIn("Use My Location", home_template)
        self.assertNotIn('value="run_find_nearest"', home_template)
        self.assertNotIn("Save Address", store_template)
        self.assertNotIn("Use My Location", store_template)
        self.assertIn("Run Find Nearest Stores", store_template)
        self.assertIn('value="run_find_nearest"', store_template)
        self.assertIn(".store-options-sticky-toolbar .address-actions-grid", css)
        self.assertIn("Show all Addresses", store_template)
        self.assertIn("Show Maps", store_template)
        self.assertIn("data-store-display-toggle=\"addresses\"", store_template)
        self.assertIn("data-store-display-toggle=\"maps\"", store_template)
        self.assertIn(".store-options-display-controls", css)
        self.assertIn("body.store-addresses-hidden", css)
        self.assertIn("body.store-maps-hidden", css)
        self.assertIn("function toggleStoreOptionsDisplay", script)
        self.assertIn("function restoreStoreOptionsDisplaySettings", script)

    def test_home_address_summary_opens_google_or_apple_maps(self):
        home_template = Path("PushShoppingList/templates/sections/home_address.html").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("home-address-map-link", home_template)
        self.assertIn("https://www.google.com/maps/search/?api=1&query=", home_template)
        self.assertIn("https://maps.apple.com/?q=", home_template)
        self.assertIn("data-google-maps-url", home_template)
        self.assertIn("data-apple-maps-url", home_template)
        self.assertIn("onclick=\"return openStoreAddressMap(this, event);\"", home_template)
        self.assertIn("function homeAddressGoogleMapsUrl", script)
        self.assertIn("function homeAddressAppleMapsUrl", script)
        self.assertIn("function updateHomeAddressMapLink", script)
        self.assertIn("updateHomeAddressMapLink(summary, text)", script)
        self.assertIn(".home-address-map-link", css)

    def test_store_manager_actions_match_recipe_log_buttons(self):
        store_template = Path("PushShoppingList/templates/sections/store_options.html").read_text(encoding="utf-8")
        recipe_log_template = Path("PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
            encoding="utf-8"
        )
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("edit-recipe-btn recipe-url-summary-edit", recipe_log_template)
        self.assertIn("remove-recipe-btn recipe-url-summary-remove", recipe_log_template)
        self.assertIn("store-edit-btn edit-recipe-btn recipe-url-summary-edit", store_template)
        self.assertIn("store-delete-btn remove-recipe-btn recipe-url-summary-remove", store_template)
        self.assertIn("aria-label=\"Delete {{ store.label }}\"", store_template)
        self.assertIn(">X</button>", store_template)
        self.assertNotIn(">Delete</button>", store_template)
        self.assertIn(".store-action-row .store-edit-btn", css)
        self.assertIn(".store-action-row .store-delete-btn", css)
        self.assertIn("width: 34px", css)
        self.assertIn("height: 32px", css)

    def test_store_manager_actions_stay_in_mobile_card_header(self):
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("@media (max-width: 650px)", css)
        self.assertIn("grid-template-columns: 28px minmax(0, 1fr) auto", css)
        self.assertIn(".store-action-row", css)
        self.assertIn("grid-column: 3 / 4", css)
        self.assertIn("grid-row: 1 / 2", css)
        self.assertIn("justify-self: end", css)
        self.assertIn("grid-column: 1 / 4", css)

    def test_behavior_toggles_left_align_on_mobile(self):
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn(".behavior-toggle", css)
        self.assertIn("justify-content: flex-start", css)
        self.assertIn("text-align: left", css)

    def test_mobile_controls_do_not_trigger_focus_zoom_outside_maps(self):
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("@media (max-width: 650px)", css)
        self.assertIn("body :where(input, select, textarea)", css)
        self.assertIn("font-size: 16px !important", css)
        self.assertIn('body :where(button, a, [role="button"], input, select, textarea, label)', css)
        self.assertIn("touch-action: manipulation", css)
        self.assertIn(".leaflet-container", css)
        self.assertIn("touch-action: auto", css)

    def test_nearby_store_list_prevents_horizontal_scroll(self):
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("overflow-x: hidden", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn("box-sizing: border-box", css)
        self.assertIn("overflow-wrap: anywhere", css)

    def test_active_store_summary_uses_linked_logo_tiles(self):
        store_template = Path("PushShoppingList/templates/sections/store_options.html").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("active-store-summary-header", store_template)
        self.assertIn("active-store-mode-controls", store_template)
        self.assertIn("data-active-store-mode-toggle=\"store\"", store_template)
        self.assertIn("data-active-store-mode-toggle=\"map\"", store_template)
        self.assertIn("data-active-store-mode-toggle=\"activation\"", store_template)
        self.assertIn("data-active-store-mode-toggle=\"edit\"", store_template)
        self.assertIn("active-store-card", store_template)
        self.assertIn("active-store-unavailable", store_template)
        self.assertIn("selected_store.skip_reason", store_template)
        self.assertIn("title=\"{{ store_tile_title }}\"", store_template)
        self.assertIn("store.urlStoreSelector or store.url", store_template)
        self.assertIn("data-store-url", store_template)
        self.assertIn("data-google-maps-url", store_template)
        self.assertIn("data-apple-maps-url", store_template)
        self.assertIn("data-edit-title", store_template)
        self.assertIn("onclick=\"return openActiveStoreIcon(this, event);\"", store_template)
        self.assertIn("store-logo-", store_template)
        self.assertIn("active-store-name", store_template)
        self.assertIn("rel=\"noopener noreferrer\"", store_template)
        self.assertIn("function setActiveStoreIconMode", script)
        self.assertIn("function restoreActiveStoreIconMode", script)
        self.assertIn("function openActiveStoreIcon", script)
        self.assertIn('new Set(["store", "map", "activation", "edit"])', script)
        self.assertIn("active-store-edit-mode", script)
        self.assertIn("openStoreEditModal(`store-edit-${link ? link.dataset.storeKey || \"\" : \"\"}`", script)
        self.assertIn("active-store-icon-mode", script)
        self.assertIn("restoreActiveStoreIconMode()", script)
        self.assertIn(".active-store-summary-header", css)
        self.assertIn(".active-store-mode-controls", css)
        self.assertIn(".active-store-mode-toggle", css)
        self.assertIn("body.active-store-map-mode", css)
        self.assertIn("body.active-store-edit-mode", css)
        self.assertIn("#storeOptionsSection .store-options-content.collapsed", css)
        self.assertIn(".store-edit-form:not(.open)", css)
        self.assertIn(".active-store-card", css)
        self.assertIn(".active-store-card.active-store-unavailable", css)
        self.assertIn(".active-store-name", css)

    def test_store_location_addresses_are_linked_and_mapped(self):
        store_template = Path("PushShoppingList/templates/sections/store_options.html").read_text(encoding="utf-8")
        index_template = Path("PushShoppingList/templates/index.html").read_text(encoding="utf-8")
        script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn("store-address-link", store_template)
        self.assertIn("https://www.google.com/maps/search/?api=1&query=", store_template)
        self.assertIn("https://maps.apple.com/", store_template)
        self.assertIn("data-google-maps-url", store_template)
        self.assertIn("data-apple-maps-url", store_template)
        self.assertIn("onclick=\"return openStoreAddressMap(this, event);\"", store_template)
        self.assertIn("https://www.google.com/maps/dir/?api=1", store_template)
        self.assertIn("travelmode=driving", store_template)
        self.assertIn("store-directions-link", store_template)
        self.assertIn("data-store-map", store_template)
        self.assertIn("data-home-lat", store_template)
        self.assertIn("data-selected-address", store_template)
        self.assertIn("data-selected-lat", store_template)
        self.assertIn("store-location-map-legend", store_template)
        self.assertIn("selected-stores-map", store_template)
        self.assertIn("data-selected-stores-map", store_template)
        self.assertIn("active_store_map_locations", store_template)
        self.assertIn("data-locations", store_template)
        self.assertIn("leaflet@1.9.4", index_template)
        self.assertIn("function initStoreLocationMaps()", script)
        self.assertIn("function coordinatesMatch", script)
        self.assertIn("function storeHomePinMarkup", script)
        self.assertIn("function shouldOpenAppleMaps", script)
        self.assertIn("function openStoreAddressMap", script)
        self.assertIn("function openStoreDirections", script)
        self.assertIn('"storeDirections"', script)
        self.assertIn("store-logo-pin", script)
        self.assertIn("store selected", script)
        self.assertIn("function selectNearbyStoreLocationFromKey", script)
        self.assertIn(".store-location-map", css)
        self.assertIn(".store-directions-link", css)
        self.assertIn(".store-map-pin.home", css)
        self.assertIn(".store-map-pin.home.house svg", css)
        self.assertIn(".store-map-pin.store", css)
        self.assertIn(".store-map-pin.store.selected", css)
        self.assertIn(".store-map-pin.store.nearby", css)
        self.assertIn(".store-map-pin.store-logo-pin", css)
        self.assertIn(".selected-stores-map", css)
        self.assertIn(".store-location-map-legend", css)

    def test_sticky_headers_render_above_store_maps(self):
        css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

        self.assertIn(".store-options-sticky-stack", css)
        self.assertIn(".view-switcher-sticky", css)
        self.assertIn(".store-location-map-wrap", css)
        self.assertIn("z-index: 1200", css)
        self.assertIn("isolation: isolate", css)

    def test_find_nearby_store_locations_filters_by_radius_and_sorts(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "display_name": "Far Aldi, Indianapolis, Indiana",
                        "lat": "39.8200",
                        "lon": "-86.0600",
                    },
                    {
                        "display_name": "Second Aldi, Indianapolis, Indiana",
                        "lat": "39.6900",
                        "lon": "-86.0600",
                    },
                    {
                        "display_name": "Aldi Fuel Center, Indianapolis, Indiana",
                        "lat": "39.6450",
                        "lon": "-86.0600",
                    },
                    {
                        "display_name": "Nearest Aldi, Indianapolis, Indiana",
                        "lat": "39.6500",
                        "lon": "-86.0600",
                    },
                ]

        with patch.object(product_service.requests, "get", return_value=FakeResponse()):
            locations = product_service.find_nearby_store_locations(
                "aldi",
                {"label": "Aldi", "urlStoreSelector": "https://info.aldi.us/stores"},
                "5905 Arlo Drive, Indianapolis, IN 46237",
                {"latitude": 39.64, "longitude": -86.06},
                radius_miles=5,
            )

        self.assertEqual(
            [location["address"] for location in locations],
            [
                "Nearest Aldi, Indianapolis, Indiana",
                "Second Aldi, Indianapolis, Indiana",
            ],
        )
        self.assertEqual(locations[0]["search_radius_miles"], 5.0)

    def test_find_nearby_store_locations_excludes_secondary_brand_pois(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "display_name": "Kroger Fuel Center, 8745, South Emerson Avenue, Indianapolis, Indiana",
                        "lat": "39.6420",
                        "lon": "-86.0600",
                    },
                    {
                        "display_name": "Kroger, 8745, South Emerson Avenue, Indianapolis, Indiana",
                        "lat": "39.6410",
                        "lon": "-86.0600",
                    },
                    {
                        "display_name": "Kroger Pharmacy, 8745, South Emerson Avenue, Indianapolis, Indiana",
                        "lat": "39.6405",
                        "lon": "-86.0600",
                    },
                ]

        with patch.object(product_service.requests, "get", return_value=FakeResponse()):
            locations = product_service.find_nearby_store_locations(
                "kroger",
                {"label": "Kroger", "urlStoreSelector": "https://www.kroger.com/stores/search"},
                "5905 Arlo Drive, Indianapolis, IN 46237",
                {"latitude": 39.64, "longitude": -86.06},
                radius_miles=1,
            )

        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0]["address"], "Kroger, 8745, South Emerson Avenue, Indianapolis, Indiana")
        self.assertFalse(product_service.is_primary_store_location_result("Meijer Express, 5303, East Southport Road"))
        self.assertTrue(product_service.is_primary_store_location_result("Meijer, 5325, East Southport Road"))
        self.assertFalse(product_service.is_primary_store_location_result("Costco Drive, Indianapolis, Indiana"))
        self.assertTrue(product_service.is_primary_store_location_result("Costco, 4628, Costco Drive"))

    def test_dedupe_nearby_store_locations_keeps_numbered_store_address(self):
        locations = [
            {
                "address": "Costco Drive, Indianapolis, Indiana",
                "latitude": 39.6367099,
                "longitude": -86.0901902,
                "distance_miles": 1.45,
            },
            {
                "address": "Costco, 4628, Costco Drive, Indianapolis, Indiana",
                "latitude": 39.6387011,
                "longitude": -86.0896104,
                "distance_miles": 1.39,
            },
        ]

        deduped = product_service.dedupe_nearby_store_locations(locations, "Costco")

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["address"], "Costco, 4628, Costco Drive, Indianapolis, Indiana")

    def test_find_nearby_store_locations_dedupes_same_physical_store(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "display_name": "Walmart, Wilson Drive, Greenwood, Indiana",
                        "lat": "39.6345362",
                        "lon": "-86.0790417",
                    },
                    {
                        "display_name": "Walmart Supercenter, 1133, Wilson Drive, Greenwood, Indiana",
                        "lat": "39.6337446",
                        "lon": "-86.0800703",
                    },
                    {
                        "display_name": "Walmart Supercenter, 4650, South Emerson Avenue, Beech Grove, Indiana",
                        "lat": "39.6900",
                        "lon": "-86.0800",
                    },
                ]

        with patch.object(product_service.requests, "get", return_value=FakeResponse()):
            locations = product_service.find_nearby_store_locations(
                "walmart",
                {"label": "Walmart", "urlStoreSelector": "https://www.walmart.com/"},
                "5905 Arlo Drive, Indianapolis, IN 46237",
                {"latitude": 39.6425974, "longitude": -86.0639388},
                radius_miles=5,
            )

        self.assertEqual(
            [location["address"] for location in locations],
            [
                "Walmart Supercenter, 1133, Wilson Drive, Greenwood, Indiana",
                "Walmart Supercenter, 4650, South Emerson Avenue, Beech Grove, Indiana",
            ],
        )

    def test_home_store_resolver_saves_nearest_with_nearby_locations(self):
        from PushShoppingList.services import home_store_location_service

        nearby_locations = [
            {
                "name": "Aldi",
                "address": "Nearest Aldi",
                "distance_miles": 1.2,
            },
            {
                "name": "Aldi",
                "address": "Second Aldi",
                "distance_miles": 3.4,
            },
        ]

        with patch(
            "PushShoppingList.services.product_selection_service.geocode_home_address",
            return_value={"latitude": 39.64, "longitude": -86.06},
        ), patch(
            "PushShoppingList.services.product_selection_service.find_nearby_store_locations",
            return_value=nearby_locations,
        ), patch.object(
            home_store_location_service,
            "save_nearest_store_results",
            side_effect=lambda result: result,
        ):
            result = home_store_location_service.resolve_nearest_stores_for_home_address(
                {"full_address": "5905 Arlo Drive, Indianapolis, IN 46237"},
                {
                    "stores": {
                        "aldi": {
                            "label": "Aldi",
                            "urlStoreSelector": "https://info.aldi.us/stores",
                        }
                    },
                    "enabled_stores": ["aldi"],
                },
                search_radius_miles="7",
            )

        aldi = result["store_locations"]["aldi"]
        self.assertEqual(result["search_radius_miles"], 7.0)
        self.assertEqual(aldi["address"], "Nearest Aldi")
        self.assertEqual(aldi["nearby_count"], 2)
        self.assertEqual(aldi["nearby_locations"][1]["address"], "Second Aldi")

    def test_select_nearby_store_location_promotes_clicked_address(self):
        from PushShoppingList.services import home_store_location_service

        saved_payloads = []
        saved_results = {
            "ok": True,
            "home_address": "5905 Arlo Drive, Indianapolis, IN 46237",
            "search_radius_miles": 5,
            "store_locations": {
                "aldi": {
                    "name": "Aldi",
                    "address": "Nearest Aldi",
                    "distance_miles": 1.2,
                    "search_radius_miles": 5,
                    "nearby_locations": [
                        {
                            "name": "Aldi",
                            "address": "Nearest Aldi",
                            "distance_miles": 1.2,
                            "search_radius_miles": 5,
                        },
                        {
                            "name": "Aldi",
                            "address": "Second Aldi",
                            "distance_miles": 3.4,
                            "search_radius_miles": 5,
                        },
                    ],
                }
            },
        }

        with patch.object(
            home_store_location_service,
            "load_nearest_store_results",
            return_value=saved_results,
        ), patch.object(
            home_store_location_service,
            "save_nearest_store_results",
            side_effect=lambda payload: saved_payloads.append(payload) or payload,
        ):
            result = home_store_location_service.select_nearby_store_location("aldi", "1")

        selected = result["selected_location"]
        self.assertTrue(result["ok"])
        self.assertEqual(selected["address"], "Second Aldi")
        self.assertEqual(selected["nearby_count"], 2)
        self.assertEqual(saved_payloads[0]["store_locations"]["aldi"]["address"], "Second Aldi")

    def test_select_nearby_store_location_route_returns_json(self):
        from PushShoppingList.app import create_app

        app = create_app()
        app.config["TESTING"] = True

        with patch(
            "PushShoppingList.routes.store_routes.select_nearby_store_location",
            return_value={"ok": True, "store_key": "aldi"},
        ) as selector:
            response = app.test_client().post(
                "/select_nearby_store_location/aldi",
                data={"ajax": "1", "nearby_index": "1"},
                headers={"X-Requested-With": "fetch"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        selector.assert_called_once_with("aldi", "1")

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

    def test_boule_product_matches_bread_ingredient(self):
        self.assertTrue(product_matches_ingredient("bread", candidate("Simply Nature Organic Rustic Italian Boule")))

    def test_aldi_boule_anchor_is_extracted_as_bread_candidate(self):
        image_url = "https://www.instacart.com/image-server/197x197/filters:fill(FFFFFF,true):format(jpg)/d2lnr5mha7bycj.cloudfront.net/product-image/file/large_boule.jpg"
        html = f"""
        <li>
          <div data-item-card="true">
            <div role="group">
              <a href="/store/aldi/products/62751457-organic-rustic-italian-boule">
                <img alt="" srcset="{image_url}, {image_url} 1.5x">
                <span>Current price: $4.39</span><span>$</span><span>4</span><span>39</span>
                <div role="heading"><div>Simply Nature Organic Rustic Italian Boule</div></div>
                <div title="24 oz">24 oz</div>
                <div>Many in stock</div>
              </a>
            </div>
          </div>
        </li>
        """

        products = product_service.parse_product_candidates_from_html(
            html,
            "https://www.aldi.us/store/aldi/s?k=bread",
            "bread",
            "aldi",
            "Aldi",
            "https://www.aldi.us/store/aldi/s?k=bread",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            None,
            {"name": "Aldi"},
        )

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["product_name"], "Simply Nature Organic Rustic Italian Boule")
        self.assertEqual(products[0]["price"], "$4.39")
        self.assertEqual(products[0]["package_size"], "24 oz")
        self.assertIn("filters:fill(FFFFFF,true):format(jpg)", products[0]["image_url"])

    def test_aldi_semantic_bread_anchor_is_kept_for_chatgpt_review(self):
        html = """
        <li data-item-card="true">
          <a href="/store/aldi/products/12345-specially-selected-artisan-ciabatta-rolls-12-oz">
            <img alt="Specially Selected Artisan Ciabatta Rolls" src="https://example.com/ciabatta.jpg">
            <span>Current price: $3.29</span>
            <div role="heading">Specially Selected Artisan Ciabatta Rolls</div>
            <span>12 oz</span>
            <span>Many in stock</span>
          </a>
        </li>
        """

        products = product_service.parse_product_candidates_from_html(
            html,
            "https://www.aldi.us/store/aldi/s?k=bread",
            "bread",
            "aldi",
            "Aldi",
            "https://www.aldi.us/store/aldi/s?k=bread",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            None,
            {"name": "Aldi"},
        )

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["product_name"], "Specially Selected Artisan Ciabatta Rolls")
        self.assertTrue(products[0]["semantic_review_needed"])
        self.assertIn("ChatGPT semantic review", products[0]["ranking_reasons"][0])

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
        self.assertIn("semantic approval layer", prompt)
        self.assertIn("Italian boule", prompt)

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
        prompt = test_grab_script.build_test_grab_eggs_aldi_prompt(
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

    def test_test_grab_uses_shared_grab_best_products_rendered_html_agent(self):
        raw_result = {
            "index": 0,
            "store_key": "aldi",
            "store_name": "Aldi",
            "candidates": [],
            "skip_reasons": [],
        }

        with patch.object(
            test_grab_script,
            "load_store_settings",
            return_value={
                "stores": {
                    "aldi": {
                        "label": "Aldi",
                        "url": "https://www.aldi.us/store/aldi/s?k=",
                    }
                }
            },
        ), patch.object(
            test_grab_script,
            "normalize_test_grab_home_address",
            return_value={"full_address": "5905 Arlo Drive, Indianapolis, IN 46237"},
        ), patch.object(
            test_grab_script,
            "geocode_home_address",
            return_value={"latitude": 39.64, "longitude": -86.06},
        ), patch.object(
            test_grab_script,
            "find_nearest_store_location",
            return_value={"name": "Aldi", "address": "Indianapolis, IN 46237", "distance_miles": 2.2},
        ), patch.object(
            test_grab_script,
            "search_store_products_for_download",
            return_value=raw_result,
        ) as search_mock, patch.object(
            test_grab_script,
            "save_test_grab_result",
            side_effect=lambda payload: payload,
        ):
            test_grab_script.test_grab_products(ingredient="eggs")

        self.assertNotIn("product_agent_prompt_builder", search_mock.call_args.kwargs)

    def test_test_grab_visible_defaults_do_not_hold_browser_open(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(test_grab_script.test_grab_visual_pause_seconds(), 0.25)
            self.assertEqual(test_grab_script.test_grab_visual_hold_seconds(), 0)

    def test_test_grab_alternatives_fall_back_to_instacart_payload_shape(self):
        payload = {
            "test_grab": True,
            "search_item": "eggs",
            "best_product": {
                "id": "best-eggs",
                "store_name": "Aldi",
                "source_page_url": "https://www.aldi.us/store/aldi/s?k=eggs",
                "product_name": "Simply Nature Organic Cage Free Brown Eggs",
                "size_count": "12 ct",
                "price": "$4.69",
                "price_per_egg": "$0.39/egg",
                "product_url": "https://www.aldi.us/store/aldi/products/17498616-eggs",
                "image_url": "https://www.instacart.com/image-server/eggs.jpg",
                "raw_product_html_snippet": "<li><a>Simply Nature Organic Cage Free Brown Eggs</a></li>",
                "product_card_text": "Simply Nature Organic Cage Free Brown Eggs 12 ct Many in stock",
                "in_stock": True,
            },
            "alternatives": [
                {
                    "id": "value-eggs",
                    "store_name": "Aldi",
                    "source_page_url": "https://www.aldi.us/store/aldi/s?k=eggs",
                    "product_name": "Goldhen Grade A Large Eggs",
                    "size_count": "12 ct",
                    "price": "$1.46",
                    "price_per_egg": "$0.12/egg",
                    "product_url": "https://www.aldi.us/store/aldi/products/115095-eggs",
                    "image_url": "https://www.instacart.com/image-server/value-eggs.jpg",
                    "raw_product_html_snippet": "<li><a>Goldhen Grade A Large Eggs</a></li>",
                    "product_card_text": "Goldhen Grade A Large Eggs 12 ct Many in stock",
                    "in_stock": True,
                }
            ],
            "results": [
                {
                    "item_key": "eggs",
                    "ingredient": "eggs",
                    "selected_product_id": "best-eggs",
                    "candidates": [],
                    "valid_products": [
                        {
                            "id": "value-eggs",
                            "product_name": "Goldhen Grade A Large Eggs",
                            "price": "$1.46",
                            "product_url": "https://www.aldi.us/store/aldi/products/115095-eggs",
                        }
                    ],
                    "store_results_list": [
                        {
                            "store_key": "aldi",
                            "store_name": "Aldi",
                            "valid_alternatives": [],
                        }
                    ],
                }
            ],
        }

        choice = test_grab_script.test_grab_choice_from_result(payload)

        self.assertEqual(len(choice["valid_alternatives"]), 2)
        self.assertEqual(choice["selected_product"]["id"], "best-eggs")
        self.assertEqual(choice["valid_alternatives"][1]["store_key"], "aldi")
        self.assertEqual(choice["valid_alternatives"][1]["search_url"], "https://www.aldi.us/store/aldi/s?k=eggs")
        self.assertEqual(choice["valid_alternatives"][1]["size"], "12 ct")
        self.assertEqual(choice["valid_alternatives"][1]["unit_price"], "")
        self.assertIn("Goldhen Grade A Large Eggs", choice["valid_alternatives"][1]["raw_product_html_snippet"])

    def test_test_grab_choice_preserves_raw_candidates_for_alternatives_modal(self):
        payload = {
            "test_grab": True,
            "search_item": "bread",
            "best_product": {
                "id": "best-bread",
                "product_name": "L'oven Fresh White Bread",
                "product_url": "https://www.aldi.us/store/aldi/products/white-bread",
                "source_page_url": "https://www.aldi.us/store/aldi/s?k=bread",
                "in_stock": True,
            },
            "results": [
                {
                    "item_key": "bread",
                    "ingredient": "bread",
                    "selected_product_id": "best-bread",
                    "candidates": [
                        {
                            "id": "raw-bread",
                            "product_name": "Raw Bread Candidate",
                            "product_url": "https://www.aldi.us/store/aldi/products/raw-bread",
                            "source_page_url": "https://www.aldi.us/store/aldi/s?k=bread",
                            "viable": False,
                        }
                    ],
                    "store_results_list": [
                        {
                            "store_key": "aldi",
                            "store_name": "Aldi",
                            "valid_alternatives": [],
                        }
                    ],
                }
            ],
        }

        choice = test_grab_script.test_grab_choice_from_result(payload)

        self.assertTrue(choice["test_grab"])
        self.assertEqual(len(choice["valid_alternatives"]), 1)
        self.assertEqual(len(choice["candidates"]), 2)
        self.assertTrue(any(candidate["id"] == "raw-bread" for candidate in choice["candidates"]))

    def test_test_grab_hydrates_missing_candidate_images_from_saved_html(self):
        with TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "aldi_bread.html"
            html_path.write_text(
                """
                <html><body>
                    <li data-item-card="true">
                        <a href="/store/aldi/products/24735034-simply-nature-organic-thin-sliced-graintastic-bread-20-4-oz">
                            <img alt="Simply Nature Graintastic Organic Thin-Sliced Bread"
                                 srcset="https://www.instacart.com/image-server/197x197/product-image/file/large_thin.jpg 1x">
                            <span>Current price: $3.49</span>
                            <span>20.4 oz</span>
                            <span>Many in stock</span>
                        </a>
                    </li>
                </body></html>
                """,
                encoding="utf-8",
            )
            payload = {
                "test_grab": True,
                "search_item": "bread",
                "results": [
                    {
                        "item_key": "bread",
                        "ingredient": "bread",
                        "selected_product_id": "thin-bread",
                        "candidates": [
                            {
                                "id": "thin-bread",
                                "product_name": "Current price: $3.49 $ 3 49 Simply Nature Graintastic Organic Thin-Sliced Bread 20.4 oz Many in stock Bread",
                                "price": "$3.49",
                                "product_url": "https://www.aldi.us/store/aldi/products/24735034-simply-nature-organic-thin-sliced-graintastic-bread-20-4-oz",
                                "rendered_page_html_path": str(html_path),
                                "image_url": "",
                                "viable": True,
                            }
                        ],
                    }
                ],
            }

            choice = test_grab_script.test_grab_choice_from_result(payload)

        item = choice["valid_alternatives"][0]
        self.assertEqual(item["product_name"], "Simply Nature Graintastic Organic Thin-Sliced Bread")
        self.assertIn("large_thin.jpg", item["image_url"])
        self.assertEqual(item["size"], "20.4 oz")
        self.assertIn("Simply Nature Graintastic Organic Thin-Sliced Bread", item["raw_product_html_snippet"])

    def test_test_grab_shell_egg_detection_accepts_final_payload_card_text(self):
        candidate = {
            "id": "payload-eggs",
            "source_page_url": "https://www.aldi.us/store/aldi/s?k=eggs",
            "product_name": "Goldhen Grade A Large Eggs",
            "size_count": "12 ct",
            "product_url": "https://www.aldi.us/store/aldi/products/115095-eggs",
            "product_card_text": "Goldhen Grade A Large Eggs 12 ct Many in stock",
            "in_stock": True,
        }

        self.assertTrue(test_grab_script.test_grab_candidate_is_valid_alternative(candidate, "eggs"))

    def test_html_anchor_candidates_capture_aldi_card_images(self):
        html = """
            <html><body>
                <li data-item-card="true">
                    <a href="/store/aldi/products/24735124-simply-nature-seedtastic-thin-sliced-organic-bread-20-4-oz">
                        <img alt="Simply Nature Seedtastic Organic Thin-Sliced Bread"
                             srcset="https://www.instacart.com/image-server/197x197/product-image/file/large_seed.jpg 1x,
                                     https://www.instacart.com/image-server/394x394/product-image/file/large_seed.jpg 2x">
                        <span>Current price: $3.49</span>
                        <span>20.4 oz</span>
                        <span>Many in stock</span>
                    </a>
                </li>
            </body></html>
        """

        candidates = product_service.parse_product_candidates_from_html(
            html,
            "https://www.aldi.us/store/aldi/s?k=bread",
            "bread",
            "aldi",
            "Aldi",
            "https://www.aldi.us/store/aldi/s?k=bread",
            "",
            None,
            {},
        )

        self.assertEqual(candidates[0]["product_name"], "Simply Nature Seedtastic Organic Thin-Sliced Bread")
        self.assertEqual(candidates[0]["price"], "$3.49")
        self.assertEqual(candidates[0]["package_size"], "20.4 oz")
        self.assertIn("large_seed.jpg", candidates[0]["image_url"])

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

    def test_store_ranking_response_rejects_unclassified_candidates(self):
        normalized = product_service.normalize_store_product_ranking_response(
            {
                "best_product_id": "bread-a",
                "results": [
                    {
                        "id": "bread-a",
                        "ranking_status": "best",
                        "confidence_score": 0.92,
                    }
                ],
            },
            {"bread-a", "bread-b"},
        )
        results = {item["id"]: item for item in normalized["results"]}

        self.assertEqual(results["bread-a"]["ranking_status"], "best")
        self.assertEqual(results["bread-b"]["ranking_status"], "rejected")
        self.assertIn("did not return a classification", results["bread-b"]["rejection_reason"])

    def test_chatgpt_store_ranking_can_rescue_semantic_card_candidate(self):
        item = candidate("Specially Selected Artisan Ciabatta Rolls")
        item.update({
            "id": "ciabatta-rolls",
            "score": -20,
            "viable": False,
            "semantic_review_needed": True,
            "skip_reasons": [
                "Product name does not clearly match the ingredient.",
                "Full product details do not confirm enough ingredient terms.",
            ],
            "rejection_reason": "Product name does not clearly match the ingredient.",
        })

        product_service.apply_store_product_ranking_selection(
            [item],
            {
                "status": "done",
                "best_product_id": "",
                "results": [
                    {
                        "id": "ciabatta-rolls",
                        "ranking_status": "alternative",
                        "confidence_score": 0.88,
                        "reason": "Ciabatta rolls are a valid bread alternative.",
                    }
                ],
            },
        )

        self.assertTrue(item["viable"])
        self.assertFalse(item["rejected"])
        self.assertEqual(item["rejection_reason"], "")
        self.assertEqual(item["ranking_status"], "alternative")
        self.assertIn("ChatGPT store ranking kept this product as a valid alternative.", item["ranking_reasons"])

    def test_chatgpt_store_ranking_does_not_override_strict_food_rules(self):
        item = candidate("Lemons, Bag")
        item.update({
            "id": "lemons-bag",
            "viable": False,
            "skip_reasons": ["Missing required food preference: must be organic"],
            "rejection_reason": "Missing required food preference: must be organic",
        })

        product_service.apply_store_product_ranking_selection(
            [item],
            {
                "status": "done",
                "best_product_id": "",
                "results": [
                    {
                        "id": "lemons-bag",
                        "ranking_status": "alternative",
                        "confidence_score": 0.88,
                        "reason": "Lemons match the ingredient.",
                    }
                ],
            },
        )

        self.assertFalse(item["viable"])
        self.assertEqual(item["rejection_reason"], "Missing required food preference: must be organic")

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

    def test_aldi_uses_zip_scoped_persistent_browser_profile(self):
        profile_dir = product_service.store_browser_profile_dir(
            "aldi",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            {"address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237"},
        )

        self.assertEqual(profile_dir.name, "aldi_46237")
        self.assertIn("browser_profiles", str(profile_dir))

    def test_aldi_reuses_verified_profile_session_before_store_selector(self):
        class FakeDriver:
            current_url = ""

            def __init__(self):
                self.get_calls = []

            def get(self, url):
                self.get_calls.append(url)
                self.current_url = url

            def execute_script(self, script, *args):
                if "document.body" in script:
                    return "Shopping at ALDI - GRE 73 - Indianapolis Pickup"
                return ""

        driver = FakeDriver()

        with patch(
            "PushShoppingList.services.recipe_extract_service.wait_for_browser_document",
        ) as wait_mock, patch(
            "PushShoppingList.scripts.stores.home_store_router.route_update_home_store",
        ) as route_mock:
            status = product_service.prepare_store_session_before_product_search(
                driver,
                "aldi",
                {"label": "Aldi", "url": "https://www.aldi.us/store/aldi/s?k="},
                "https://www.aldi.us/store/aldi/s?k=bread",
                "5905 Arlo Drive, Indianapolis, IN 46237",
                {"latitude": 39.64, "longitude": -86.06},
                {"name": "Aldi", "address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237"},
                "Aldi",
            )

        self.assertTrue(status["ok"])
        self.assertTrue(status["home_store_update"]["reused_profile_session"])
        self.assertEqual(driver.get_calls, ["https://www.aldi.us/store/aldi/s?k=bread"])
        self.assertEqual(status["pre_search_store_url"], "https://www.aldi.us/store/aldi?zipcode=46237")
        wait_mock.assert_called_once()
        route_mock.assert_not_called()

    def test_aldi_already_confirmed_store_skips_post_update_document_wait(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/products/16902710-friendly-farms-vitamin-d-milk-1-gal"

        update_result = {
            "attempted": False,
            "ok": True,
            "already_selected": True,
            "storefront_url": FakeDriver.current_url,
        }

        with patch.object(
            product_service,
            "try_reuse_aldi_profile_store_session",
            return_value={"ok": False},
        ), patch(
            "PushShoppingList.services.recipe_extract_service.wait_for_browser_document",
        ) as wait_mock, patch(
            "PushShoppingList.scripts.stores.home_store_router.route_update_home_store",
            return_value=update_result,
        ) as route_mock, patch.object(
            product_service,
            "rendered_store_context_status",
            return_value={"ok": False, "verified": False, "proof_of_store_selection": [], "errors": ["slow check skipped"]},
        ):
            status = product_service.prepare_store_session_before_product_search(
                FakeDriver(),
                "aldi",
                {"label": "Aldi", "url": "https://www.aldi.us/store/aldi/s?k="},
                "https://www.aldi.us/store/aldi/s?k=bread",
                "5905 Arlo Drive, Indianapolis, IN 46237",
                {"latitude": 39.64, "longitude": -86.06},
                {"name": "Aldi", "address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237"},
                "Aldi",
            )

        self.assertTrue(status["ok"])
        self.assertTrue(status["verified"])
        self.assertTrue(status["home_store_update"]["already_selected"])
        self.assertIn("already confirmed", " ".join(status["proof_of_store_selection"]))
        wait_mock.assert_not_called()
        route_mock.assert_called_once()

    def test_aldi_reused_profile_product_restore_jumps_back_to_search(self):
        class FakeDriver:
            current_url = ""

            def __init__(self):
                self.get_calls = []
                self.script_assign_calls = []

            def get(self, url):
                self.get_calls.append(url)
                if len(self.get_calls) == 1:
                    self.current_url = "https://www.aldi.us/store/aldi/products/26274163-mandarins-bag-3-lb"
                else:
                    self.current_url = url

            def execute_script(self, script, *args):
                if "window.location.assign" in script:
                    self.script_assign_calls.append(args[0])
                    self.current_url = args[0]
                    return None
                if "document.body" in script:
                    return 'Shopping at ALDI - GRE 73 - Indianapolis Pickup Results for "chips"'
                return ""

        driver = FakeDriver()

        status = product_service.try_reuse_aldi_profile_store_session(
            driver,
            "https://www.aldi.us/store/aldi/s?k=chips",
            "https://www.aldi.us/store/aldi?zipcode=46237",
            "aldi",
            "Aldi",
            "5905 Arlo Drive, Indianapolis, IN 46237",
            {"name": "Aldi", "address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237"},
            lambda *_args, **_kwargs: None,
        )

        self.assertTrue(status["ok"])
        self.assertEqual(driver.get_calls, ["https://www.aldi.us/store/aldi/s?k=chips"])
        self.assertEqual(driver.script_assign_calls, ["https://www.aldi.us/store/aldi/s?k=chips"])

    def test_aldi_product_search_does_not_noop_on_product_detail_overlay(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/products/26274163-mandarins-bag-3-lb"
            page_source = "<html><body>Results for chips</body></html>"

            def __init__(self):
                self.get_calls = []
                self.script_assign_calls = []

            def get(self, url):
                self.get_calls.append(url)
                self.current_url = url

            def execute_script(self, script, *args):
                if "return document.body" in script:
                    return 'Results for "chips"'
                if "window.location.assign" in script:
                    self.script_assign_calls.append(args[0])
                    self.current_url = args[0]
                    return None
                if "HTMLInputElement" in script:
                    return False
                return ""

        driver = FakeDriver()

        self.assertTrue(product_service.open_aldi_product_search(
            driver,
            "https://www.aldi.us/store/aldi/s?k=chips",
            search_term="chips",
        ))
        self.assertEqual(driver.script_assign_calls, ["https://www.aldi.us/store/aldi/s?k=chips"])
        self.assertEqual(driver.get_calls, [])

    def test_aldi_reused_profile_search_does_not_wait_for_storefront(self):
        class FakeDriver:
            pass

        with patch.object(product_service, "wait_for_current_url_contains") as wait_mock, patch.object(
            product_service,
            "open_aldi_product_search",
            return_value=True,
        ) as search_mock:
            product_service.open_product_search_after_storefront(
                FakeDriver(),
                "https://www.aldi.us/store/aldi/s?k=bread",
                "aldi",
                {"home_store_update": {"ok": True, "reused_profile_session": True}},
                search_term="bread",
            )

        wait_mock.assert_not_called()
        search_mock.assert_called_once()

    def test_aldi_verified_store_context_search_does_not_wait_for_storefront(self):
        class FakeDriver:
            pass

        status = {
            "ok": True,
            "verified": True,
            "proof_of_store_selection": ["Visible store/session identifier: GRE 73."],
            "home_store_update": {"ok": True, "clicked_final": True},
        }

        with patch.object(product_service, "wait_for_current_url_contains") as wait_mock, patch.object(
            product_service,
            "open_aldi_product_search",
            return_value=True,
        ) as search_mock:
            product_service.open_product_search_after_storefront(
                FakeDriver(),
                "https://www.aldi.us/store/aldi/s?k=bread",
                "aldi",
                status,
                search_term="bread",
            )

        wait_mock.assert_not_called()
        search_mock.assert_called_once()

    def test_aldi_address_selection_can_continue_to_actual_search_without_proof_bypass(self):
        status = {
            "ok": False,
            "home_store_update": {
                "typed_location": True,
                "clicked_address_suggestion": True,
                "clicked_save_address": True,
                "clicked_shop_this_store": False,
            },
        }

        self.assertTrue(product_service.store_session_update_allows_product_search(status))
        self.assertFalse(product_service.store_session_update_has_store_confirmation(status))

        context_status = {
            "ok": False,
            "verified": False,
            "message": "Localized store session could not be proven from visible page text.",
            "proof_of_store_selection": [],
            "errors": ["Localized store session could not be proven from visible page text."],
        }

        merged = product_service.merge_store_session_selection_proof(context_status, status)

        self.assertFalse(merged["ok"])
        self.assertEqual(merged["proof_of_store_selection"], [])

    def test_aldi_typed_location_alone_does_not_allow_product_search(self):
        status = {
            "ok": False,
            "home_store_update": {
                "typed_location": True,
                "clicked_address_suggestion": False,
                "clicked_save_address": False,
                "clicked_store_card": False,
                "clicked_shop_this_store": False,
            },
        }

        self.assertFalse(product_service.store_session_update_allows_product_search(status))

    def test_aldi_zip_mismatch_blocks_product_search_even_after_store_clicks(self):
        status = {
            "ok": False,
            "message": "Expected store ZIP 46237 from the saved Full Address/store resolution, found visible ZIP(s): 60602.",
            "home_store_update": {
                "clicked_store_card": True,
                "clicked_shop_this_store": True,
                "reached_storefront": True,
            },
        }

        self.assertTrue(product_service.store_session_has_zip_mismatch(status))
        self.assertFalse(product_service.store_session_update_allows_product_search(status))

    def test_aldi_search_after_storefront_submits_ingredient_search(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/storefront"
            page_source = "<html><body>Shopping at ALDI - GRE 73 - Indianapolis</body></html>"

            def __init__(self):
                self.get_calls = []
                self.script_calls = []

            def get(self, url):
                self.get_calls.append(url)
                self.current_url = url

            def execute_script(self, script, *args):
                self.script_calls.append((script, args))
                if "HTMLInputElement" in script:
                    self.current_url = f"https://www.aldi.us/store/aldi/s?k={args[0]}"
                    return True
                if "return document.body" in script:
                    return 'Results for "eggs"'
                return ""

        driver = FakeDriver()

        product_service.open_product_search_after_storefront(
            driver,
            "https://www.aldi.us/store/aldi/s?k=eggs",
            "aldi",
            {"home_store_update": {"clicked_shop_this_store": True}},
            search_term="eggs",
        )

        self.assertEqual(driver.current_url, "https://www.aldi.us/store/aldi/s?k=eggs")
        self.assertEqual(driver.get_calls, [])

    def test_aldi_store_update_skips_selector_when_store_already_confirmed(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/products/16902710-friendly-farms-vitamin-d-milk-1-gal"

            def execute_script(self, script, *args):
                if "document.body" in script:
                    return "In-Store open 9am - 8pm ALDI - GRE 73 - Indianapolis 46237"
                return ""

        unexpected_calls = []

        def unexpected_helper(*_args, **_kwargs):
            unexpected_calls.append(True)
            return False

        helpers = {
            "accept_cookies_if_present": lambda *_args, **_kwargs: False,
            "type_visible_location_input": unexpected_helper,
            "click_first_address_suggestion": unexpected_helper,
            "click_save_address_button": unexpected_helper,
            "click_first_store_location_card": unexpected_helper,
            "click_store_card_that_matches_context": unexpected_helper,
            "click_continue_shopping": unexpected_helper,
            "click_visible_xpath": unexpected_helper,
            "final_home_store_xpaths": lambda _context: ["//button"],
            "correct_home_store_selected": lambda *_args, **_kwargs: True,
        }

        with patch.object(aldi_store, "open_aldi_store_selector_page") as selector_mock:
            result = aldi_store.update_home_store(
                FakeDriver(),
                {
                    "search_values": ["5905 Arlo Drive, Indianapolis, IN 46237"],
                    "home_zip": "46237",
                    "pickup_zip": "46237",
                    "exact_address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237",
                    "address_hints": ["46237", "6835 South Emerson Avenue"],
                    "store_key": "aldi",
                    "store_name": "Aldi",
                },
                helpers,
                wait_seconds=0,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["already_selected"])
        self.assertFalse(result["attempted"])
        selector_mock.assert_not_called()
        self.assertEqual(unexpected_calls, [])

    def test_aldi_visible_confirmation_rejects_hidden_expected_zip_when_header_is_wrong(self):
        class FakeDriver:
            page_source = "<html><script>46237 Indianapolis</script><body>60602 Chicago</body></html>"

            def execute_script(self, script, *args):
                if "document.body" in script:
                    return "Delivery 60602 Shopping at ALDI - BAT 104 - Chicago"
                return ""

        self.assertFalse(aldi_store.aldi_visible_home_store_selected(
            FakeDriver(),
            {
                "home_zip": "46237",
                "pickup_zip": "46237",
                "exact_address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237",
                "address_hints": ["46237", "6835 South Emerson Avenue"],
            },
        ))

    def test_aldi_visible_confirmation_accepts_visible_expected_store_header(self):
        class FakeDriver:
            def execute_script(self, script, *args):
                if "document.body" in script:
                    return "In-Store open 9am - 8pm ALDI - GRE 73 - Indianapolis"
                return ""

        self.assertTrue(aldi_store.aldi_visible_home_store_selected(
            FakeDriver(),
            {
                "home_zip": "46237",
                "pickup_zip": "46237",
                "exact_address": "Aldi, 6835 South Emerson Avenue, Indianapolis, IN 46237",
                "address_hints": ["46237", "6835 South Emerson Avenue"],
            },
        ))

    def test_aldi_store_update_uses_scoped_location_input_and_saves_after_typing(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/s?k=bread"

        generic_type_calls = []
        save_calls = []

        def generic_type(*_args, **_kwargs):
            generic_type_calls.append(True)
            return True

        def save_address(*_args, **_kwargs):
            save_calls.append(True)
            return True

        helpers = {
            "accept_cookies_if_present": lambda *_args, **_kwargs: False,
            "type_visible_location_input": generic_type,
            "click_first_address_suggestion": lambda *_args, **_kwargs: False,
            "click_save_address_button": save_address,
            "click_first_store_location_card": lambda *_args, **_kwargs: False,
            "click_store_card_that_matches_context": lambda *_args, **_kwargs: True,
            "click_continue_shopping": lambda *_args, **_kwargs: False,
            "click_visible_xpath": lambda *_args, **_kwargs: False,
            "final_home_store_xpaths": lambda _context: ["//button"],
            "correct_home_store_selected": lambda *_args, **_kwargs: False,
        }

        with patch.object(aldi_store, "aldi_visible_home_store_selected", side_effect=[False, True]), patch.object(
            aldi_store,
            "open_aldi_store_selector_page",
            return_value=True,
        ), patch.object(
            aldi_store,
            "click_aldi_near_button",
            return_value=False,
        ), patch.object(
            aldi_store,
            "type_aldi_location_input",
            return_value=True,
        ) as scoped_type_mock, patch.object(
            aldi_store,
            "click_aldi_shop_this_store",
            return_value=True,
        ), patch.object(
            aldi_store,
            "wait_for_aldi_storefront",
            return_value=True,
        ), patch.object(
            aldi_store.time,
            "sleep",
            return_value=None,
        ):
            result = aldi_store.update_home_store(
                FakeDriver(),
                {
                    "search_values": ["5905 Arlo Drive, Indianapolis, IN 46237"],
                    "home_zip": "46237",
                    "pickup_zip": "46237",
                    "store_key": "aldi",
                    "store_name": "Aldi",
                },
                helpers,
                wait_seconds=0,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["typed_location"])
        self.assertTrue(result["clicked_save_address"])
        scoped_type_mock.assert_called_once()
        self.assertEqual(save_calls, [True])
        self.assertEqual(generic_type_calls, [])

    def test_aldi_store_update_does_not_fallback_to_first_card_without_address_update(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/s?k=bread"

        first_card_calls = []

        helpers = {
            "accept_cookies_if_present": lambda *_args, **_kwargs: False,
            "type_visible_location_input": lambda *_args, **_kwargs: False,
            "click_first_address_suggestion": lambda *_args, **_kwargs: False,
            "click_save_address_button": lambda *_args, **_kwargs: False,
            "click_first_store_location_card": lambda *_args, **_kwargs: first_card_calls.append(True) or True,
            "click_store_card_that_matches_context": lambda *_args, **_kwargs: False,
            "click_continue_shopping": lambda *_args, **_kwargs: False,
            "click_visible_xpath": lambda *_args, **_kwargs: False,
            "final_home_store_xpaths": lambda _context: ["//button"],
            "correct_home_store_selected": lambda *_args, **_kwargs: False,
        }

        with patch.object(aldi_store, "open_aldi_store_selector_page", return_value=True), patch.object(
            aldi_store,
            "click_aldi_near_button",
            return_value=False,
        ), patch.object(
            aldi_store,
            "type_aldi_location_input",
            return_value=False,
        ), patch.object(
            aldi_store,
            "click_aldi_shop_this_store",
            return_value=False,
        ) as shop_mock, patch.object(
            aldi_store.time,
            "sleep",
            return_value=None,
        ):
            result = aldi_store.update_home_store(
                FakeDriver(),
                {
                    "search_values": ["5905 Arlo Drive, Indianapolis, IN 46237"],
                    "home_zip": "46237",
                    "pickup_zip": "46237",
                    "selected_name": "Aldi",
                    "store_key": "aldi",
                    "store_name": "Aldi",
                },
                helpers,
                wait_seconds=0,
            )

        self.assertFalse(result["ok"])
        self.assertFalse(result["clicked_first_store_card"])
        self.assertEqual(first_card_calls, [])
        shop_mock.assert_not_called()

    def test_aldi_store_card_context_removes_generic_chain_name(self):
        card_context = aldi_store.aldi_store_card_context({
            "store_name": "Aldi",
            "selected_name": "Aldi",
            "pickup_zip": "46237",
        })

        self.assertEqual(card_context["selected_name"], "")
        self.assertEqual(card_context["pickup_zip"], "46237")

    def test_aldi_store_update_does_not_click_final_after_reaching_storefront(self):
        class FakeDriver:
            current_url = "https://www.aldi.us/store/aldi/storefront"

        final_clicks = []

        def final_click(*_args, **_kwargs):
            final_clicks.append(True)
            return True

        confirmation_checks = []

        def correct_store_after_selector(*_args, **_kwargs):
            confirmation_checks.append(True)
            return len(confirmation_checks) > 1

        helpers = {
            "accept_cookies_if_present": lambda *_args, **_kwargs: False,
            "type_visible_location_input": lambda *_args, **_kwargs: True,
            "click_first_address_suggestion": lambda *_args, **_kwargs: True,
            "click_save_address_button": lambda *_args, **_kwargs: True,
            "click_first_store_location_card": lambda *_args, **_kwargs: True,
            "click_store_card_that_matches_context": lambda *_args, **_kwargs: False,
            "click_continue_shopping": lambda *_args, **_kwargs: False,
            "click_visible_xpath": final_click,
            "final_home_store_xpaths": lambda _context: ["//button"],
            "correct_home_store_selected": correct_store_after_selector,
        }

        with patch.object(aldi_store, "aldi_visible_home_store_selected", side_effect=[False, True]), patch.object(
            aldi_store,
            "open_aldi_store_selector_page",
            return_value=True,
        ), patch.object(
            aldi_store,
            "click_aldi_near_button",
            return_value=True,
        ), patch.object(
            aldi_store,
            "click_aldi_shop_this_store",
            return_value=True,
        ), patch.object(
            aldi_store,
            "wait_for_aldi_storefront",
            return_value=True,
        ), patch.object(
            aldi_store.time,
            "sleep",
            return_value=None,
        ):
            result = aldi_store.update_home_store(
                FakeDriver(),
                {
                    "search_values": ["5905 Arlo Drive, Indianapolis, IN 46237"],
                    "store_key": "aldi",
                    "store_name": "Aldi",
                },
                helpers,
                wait_seconds=0,
            )

        self.assertTrue(result["reached_storefront"])
        self.assertFalse(result["clicked_final"])
        self.assertEqual(final_clicks, [])

    def test_browser_closes_after_rendered_snapshot_before_offline_reasoning(self):
        class FakeDriver:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        driver = FakeDriver()

        with patch.object(product_service, "visual_browser_pause") as pause_mock:
            product_service.close_browser_after_rendered_snapshot(
                driver,
                browser_visible=True,
                browser_visual_hold_seconds=0.5,
            )

        pause_mock.assert_called_once_with(True, 0.5)
        self.assertTrue(driver.quit_called)

    def test_post_scroll_snapshot_captures_current_dom_html_and_product_html(self):
        class FakeDriver:
            page_source = "<html><body>Fallback</body></html>"

            def execute_script(self, script, *args):
                if "document.documentElement" in script:
                    return "<html><body><article>Large Eggs $1.99</article></body></html>"
                if "const limit = arguments[0]" in script:
                    return [
                        {
                            "name": "Large Eggs",
                            "price": "$1.99",
                            "product_url": "https://www.aldi.us/store/aldi/products/eggs",
                            "image_url": "https://example.com/eggs.jpg",
                            "text": "Large Eggs 12 ct $1.99",
                            "raw_product_html_snippet": "<article><a href='/eggs'>Large Eggs</a><span>$1.99</span></article>",
                        }
                    ]
                if "return document.body" in script:
                    return "Shopping at ALDI Results for eggs Large Eggs $1.99"
                return ""

        snapshot = product_service.capture_rendered_product_page_snapshot(FakeDriver())

        self.assertIn("Large Eggs $1.99", snapshot["html"])
        self.assertIn("Results for eggs", snapshot["visible_text"])
        self.assertEqual(snapshot["visible_cards"][0]["name"], "Large Eggs")
        self.assertIn('data-name="Large Eggs"', snapshot["product_related_html"])

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
