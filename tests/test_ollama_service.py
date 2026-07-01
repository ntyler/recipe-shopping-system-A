from types import SimpleNamespace

from PushShoppingList.services import ollama_service


class FakeOllamaResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return {"response": self.text}


def valid_recipe_json(name="Crab Wonton"):
    return """
    {
      "recipe_name": "%s",
      "servings": "4 servings",
      "ingredients": [
        {"quantity": "8", "unit": "oz", "ingredient": "crab", "preparation": "flaked"},
        {"quantity": "4", "unit": "oz", "ingredient": "cream cheese"}
      ],
      "equipment": ["mixing bowl", "skillet"],
      "instructions": [
        "Mix the crab and cream cheese.",
        "Fill the wonton wrappers.",
        "Heat oil in a skillet.",
        "Fry until crisp."
      ],
      "prep_time": "15 minutes",
      "cook_time": "10 minutes",
      "total_time": "25 minutes",
      "difficulty": "medium",
      "estimated_cost": "$10-$14"
    }
    """ % name


def menu_entry(item_id="item-1", name="Crab Wonton"):
    return {
        "recipe_url": "https://example.com/menu?menu_item=crab-wonton",
        "menu_item": {
            "menu_item_id": item_id,
            "item_name": name,
            "menu_section": "Appetizers",
            "description": "Crispy wontons filled with crab and cream cheese.",
        },
    }


def test_parse_ollama_json_response_strips_markdown_fence():
    payload = ollama_service.parse_ollama_json_response(
        "```json\n{\"recipe_name\":\"Crab Wonton\",\"servings\":\"4\"}\n```"
    )

    assert payload["recipe_name"] == "Crab Wonton"
    assert payload["servings"] == "4"


def test_generate_ollama_full_recipe_repairs_invalid_json_once(monkeypatch):
    calls = []
    responses = iter([
        "```json\nthis is not json\n```",
        valid_recipe_json(),
    ])

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeOllamaResponse(next(responses))

    monkeypatch.setattr(ollama_service.requests, "post", fake_post)
    monkeypatch.setenv("OLLAMA_FULL_RECIPE_MODEL", "qwen-test:14b")

    result = ollama_service.generate_ollama_full_recipe_for_entry(menu_entry())

    assert result["ok"] is True
    assert result["json_valid"] is True
    assert result["repair_attempted"] is True
    assert result["inference"]["ollama_model"] == "qwen-test:14b"
    assert len(calls) == 2
    assert calls[0]["json"]["model"] == "qwen-test:14b"
    assert calls[0]["url"].endswith("/api/generate")


def test_ollama_batch_falls_back_to_openai_for_low_confidence(monkeypatch):
    monkeypatch.setattr(
        ollama_service,
        "generate_ollama_full_recipe_for_entry",
        lambda *args, **kwargs: {
            "ok": False,
            "json_valid": True,
            "low_confidence": True,
            "low_confidence_reasons": ["equipment_empty"],
            "error": "",
        },
    )
    fallback_calls = []

    def fake_openai_fallback(entries, cancellation_check=None):
        fallback_calls.append(entries)
        return {
            "ok": True,
            "items": {
                "item-1": {
                    "predicted_ingredients": ["crab"],
                    "predicted_equipment": ["skillet"],
                    "predicted_instructions": ["Fill.", "Fry.", "Drain.", "Serve."],
                },
            },
            "model": "gpt-test",
            "model_source": "test",
        }

    result = ollama_service.infer_menu_item_recipe_batch_with_ollama_support(
        [menu_entry()],
        model_resolution=SimpleNamespace(model="gpt-test", source="test"),
        openai_infer_batch=fake_openai_fallback,
    )

    assert result["ok"] is True
    assert result["items"]["item-1"]["provider"] == "openai"
    assert result["items"]["item-1"]["fallback_used"] is True
    assert result["openai_fallback_count"] == 1
    assert result["openai_fallback_success_count"] == 1
    assert result["fallback_used"] is True
    assert len(fallback_calls) == 1
