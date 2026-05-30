import unittest
from unittest.mock import patch

from PushShoppingList.routes import main_routes
from PushShoppingList.services import ingredient_text_review_service


class IngredientTextReviewServiceTests(unittest.TestCase):
    def setUp(self):
        ingredient_text_review_service._review_cache.clear()

    def test_detects_measured_prep_phrase_candidate(self):
        item = {
            "ingredient": "large egg yolk beaten with 1 tablespoon water",
            "original_text": "1 large egg yolk beaten with 1 tablespoon water",
        }

        self.assertTrue(ingredient_text_review_service.ingredient_text_review_candidate(item))

    def test_skips_existing_or_choice_candidates(self):
        item = {
            "ingredient": "flour OR corn tortillas",
            "original_text": "12 flour or corn tortillas",
        }

        self.assertFalse(ingredient_text_review_service.ingredient_text_review_candidate(item))

    def test_chatgpt_review_is_attached_to_matching_ingredient(self):
        fake_client = FakeOpenAIClient(
            '{"reviews": [{"index": 0, "needs_review": true, '
            '"reason": "The text combines egg wash prep with the grocery item.", '
            '"prompt": "Pick grocery item", '
            '"options": [{"ingredient": "egg yolk", "purchasable_item": "eggs", '
            '"reason": "Egg yolk is the item to buy."}]}]}'
        )
        ingredients = [{
            "ingredient": "large egg yolk beaten with 1 tablespoon water",
            "original_text": "1 large egg yolk beaten with 1 tablespoon water",
            "quantity": "1",
            "unit": "",
            "preparation": "",
            "purchasable_item": "large egg yolk beaten with 1 tablespoon water",
        }]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch.object(ingredient_text_review_service, "get_openai_client", return_value=fake_client):
            result = ingredient_text_review_service.annotate_ingredients_for_food_review(ingredients)

        review = result[0]["food_review"]
        self.assertTrue(review["needs_review"])
        self.assertEqual(review["source"], "chatgpt")
        self.assertEqual(review["options"][0]["ingredient"], "egg yolk")
        self.assertEqual(review["options"][0]["purchasable_item"], "eggs")

    def test_local_fallback_returns_clean_grocery_option_without_key(self):
        ingredients = [{
            "ingredient": "large egg yolk beaten with 1 tablespoon water",
            "original_text": "1 large egg yolk beaten with 1 tablespoon water",
        }]

        with patch.dict("os.environ", {}, clear=True):
            result = ingredient_text_review_service.annotate_ingredients_for_food_review(ingredients)

        review = result[0]["food_review"]
        self.assertEqual(review["source"], "local")
        self.assertEqual(review["options"][0]["ingredient"], "egg yolk")
        self.assertEqual(review["options"][0]["purchasable_item"], "eggs")
        self.assertEqual(review["options"][1]["ingredient"], "water")
        self.assertEqual(review["options"][1]["quantity"], "1")
        self.assertEqual(review["options"][1]["unit"], "tablespoon")
        self.assertEqual(review["options"][1]["original_text"], "1 tablespoon water")

    def test_recipe_food_rule_status_includes_ingredient_text_review(self):
        recipe = {
            "ingredients": [{
                "ingredient": "large egg yolk beaten with 1 tablespoon water",
                "original_text": "1 large egg yolk beaten with 1 tablespoon water",
                "food_review": {
                    "needs_review": True,
                    "reason": "The text combines egg wash prep with the grocery item.",
                    "prompt": "Pick grocery item",
                    "options": [{
                        "ingredient": "egg yolk",
                        "purchasable_item": "eggs",
                        "reason": "Egg yolk is the item to buy.",
                    }],
                },
            }],
        }

        status = main_routes.recipe_food_rule_status(recipe)

        self.assertTrue(status["needs_review"])
        self.assertEqual(status["count"], 1)
        self.assertIn("large egg yolk beaten with 1 tablespoon water", status["marker"])
        self.assertIn("egg wash prep", status["marker"])


class FakeOpenAIClient:
    def __init__(self, response_content):
        self.chat = FakeOpenAIChat(response_content)


class FakeOpenAIChat:
    def __init__(self, response_content):
        self.completions = FakeOpenAICompletions(response_content)


class FakeOpenAICompletions:
    def __init__(self, response_content):
        self.response_content = response_content
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeOpenAIResponse(self.response_content)


class FakeOpenAIResponse:
    def __init__(self, response_content):
        self.choices = [FakeOpenAIChoice(response_content)]


class FakeOpenAIChoice:
    def __init__(self, response_content):
        self.message = FakeOpenAIMessage(response_content)


class FakeOpenAIMessage:
    def __init__(self, response_content):
        self.content = response_content
