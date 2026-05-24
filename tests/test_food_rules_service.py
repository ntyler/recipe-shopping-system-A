import unittest
from unittest.mock import patch

from PushShoppingList.services import food_rules_service


class FoodRulesServiceTests(unittest.TestCase):
    def test_targeted_prompt_guides_required_or_avoid_section(self):
        rules = {"require": [], "avoid": []}

        required_prompt = food_rules_service.build_food_rule_prompt(
            "gluten free",
            rules,
            "require",
        )
        avoid_prompt = food_rules_service.build_food_rule_prompt(
            "red dye",
            rules,
            "avoid",
        )

        self.assertIn("Target list: require", required_prompt)
        self.assertIn("Target list: avoid", avoid_prompt)
        self.assertIn("return that existing rule with any useful missing terms", required_prompt)

    def test_empty_chatgpt_additions_are_successful_noop(self):
        fake_client = FakeOpenAIClient('{"require": [], "avoid": []}')
        current_rules = {
            "require": [{"label": "must be organic", "terms": ["organic"]}],
            "avoid": [{"label": "no citric acid", "terms": ["citric acid"]}],
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch.object(food_rules_service, "get_openai_client", return_value=fake_client), \
             patch.object(food_rules_service, "save_food_rules", side_effect=food_rules_service.normalize_food_rules):
            result = food_rules_service.suggest_food_rules_from_prompt(
                "no citric acid",
                current_rules,
                "avoid",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["food_rules"], current_rules)
        self.assertEqual(result["added"], {"require": [], "avoid": []})
        self.assertEqual(result["changes"][0]["action"], "matched_existing")
        self.assertEqual(result["changes"][0]["label"], "no citric acid")
        self.assertEqual(
            result["message"],
            "ChatGPT found the existing Avoid rule 'no citric acid' already meets this requirement.",
        )

    def test_chatgpt_existing_rule_message_names_rule(self):
        fake_client = FakeOpenAIClient('{"require": [{"label": "must be organic", "terms": ["organic"]}], "avoid": []}')
        current_rules = {
            "require": [{"label": "must be organic", "terms": ["organic"]}],
            "avoid": [],
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch.object(food_rules_service, "get_openai_client", return_value=fake_client), \
             patch.object(food_rules_service, "save_food_rules", side_effect=food_rules_service.normalize_food_rules):
            result = food_rules_service.suggest_food_rules_from_prompt(
                "must be organic",
                current_rules,
                "require",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"][0]["action"], "matched_existing")
        self.assertEqual(result["changes"][0]["label"], "must be organic")
        self.assertEqual(
            result["message"],
            "ChatGPT found the existing Required rule 'must be organic' already meets this requirement.",
        )

    def test_chatgpt_added_rule_message_names_rule(self):
        fake_client = FakeOpenAIClient('{"require": [{"label": "must be gluten free", "terms": ["gluten free"]}], "avoid": []}')
        current_rules = {"require": [], "avoid": []}

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch.object(food_rules_service, "get_openai_client", return_value=fake_client), \
             patch.object(food_rules_service, "save_food_rules", side_effect=food_rules_service.normalize_food_rules):
            result = food_rules_service.suggest_food_rules_from_prompt(
                "must be gluten free",
                current_rules,
                "require",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"][0]["action"], "added")
        self.assertEqual(
            result["message"],
            "ChatGPT added a new Required rule: must be gluten free.",
        )

    def test_chatgpt_updated_rule_message_names_rule_and_terms(self):
        fake_client = FakeOpenAIClient('{"require": [], "avoid": [{"label": "no citric acid", "terms": ["citric acid", "citric acid monohydrate"]}]}')
        current_rules = {
            "require": [],
            "avoid": [{"label": "no citric acid", "terms": ["citric acid"]}],
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch.object(food_rules_service, "get_openai_client", return_value=fake_client), \
             patch.object(food_rules_service, "save_food_rules", side_effect=food_rules_service.normalize_food_rules):
            result = food_rules_service.suggest_food_rules_from_prompt(
                "avoid citric acid variants",
                current_rules,
                "avoid",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"][0]["action"], "updated_existing")
        self.assertEqual(result["changes"][0]["added_terms"], ["citric acid monohydrate"])
        self.assertEqual(
            result["message"],
            "ChatGPT found the existing Avoid rule 'no citric acid' and updated it. Added terms: citric acid monohydrate.",
        )

    def test_merge_food_rules_updates_matching_rule_terms(self):
        merged = food_rules_service.merge_food_rules(
            {"require": [], "avoid": [{"label": "no red dye", "terms": ["red dye"]}]},
            {"avoid": [{"label": "no red dye", "terms": ["red 40", "red dye"]}]},
        )

        self.assertEqual(merged["avoid"], [{
            "label": "no red dye",
            "terms": ["red 40", "red dye"],
        }])


class FakeOpenAIClient:
    def __init__(self, response_content):
        self.chat = FakeOpenAIChat(response_content)


class FakeOpenAIChat:
    def __init__(self, response_content):
        self.completions = FakeOpenAICompletions(response_content)


class FakeOpenAICompletions:
    def __init__(self, response_content):
        self.response_content = response_content

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
