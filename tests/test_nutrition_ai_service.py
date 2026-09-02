import json
from types import SimpleNamespace

import pytest

from PushShoppingList.services import nutrition_ai_service as service
from PushShoppingList.services import nutrition_photo_service as photo_service
from PushShoppingList.services.nutrition_tracking_service import NutritionValidationError


def _analysis_json():
    return {
        "food_items": [
            {
                "name": "Oatmeal",
                "quantity": 1.5,
                "unit": "cups",
                "nutrition": {
                    "calories": 240,
                    "protein": 8,
                    "carbohydrates": 42,
                    "fat": 5,
                    "fiber": 6,
                    "sugar": 4,
                    "sodium": 180,
                },
                "confidence": 0.9,
            },
            {
                "name": "Blueberries",
                "quantity": 0.5,
                "unit": "cup",
                "nutrition": {
                    "calories": 42,
                    "protein": 0.5,
                    "carbohydrates": 10.5,
                    "fat": 0.2,
                    "fiber": 1.8,
                    "sugar": 7,
                    "sodium": 0,
                },
                "confidence": 0.8,
            },
        ],
        "confidence": 0.86,
    }


def _chat_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        model="configured-nutrition-model",
    )


def test_missing_provider_returns_empty_manual_review(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = service.analyze_meal(description="Toast and eggs")

    assert result["ok"] is True
    assert result["analysis_available"] is False
    assert result["analysis_status"] == "manual_entry"
    assert result["manual_entry_available"] is True
    assert result["requires_review"] is True
    assert result["is_estimate"] is False
    assert result["food_items"] == []
    assert result["nutrition"] == {}
    assert set(result["nutrition_status"].values()) == {"missing"}
    assert result["confidence"] is None


def test_description_analysis_uses_configured_model_throttle_and_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    calls = {}
    fake_client = object()

    monkeypatch.setattr(
        service,
        "model_value_for_env",
        lambda env_name: ("configured-nutrition-model", "test override"),
    )
    monkeypatch.setattr(service, "get_openai_client", lambda: fake_client)

    def fake_throttled(client, payload, **kwargs):
        calls["client"] = client
        calls["payload"] = payload
        calls["throttle"] = kwargs
        return _chat_response(json.dumps(_analysis_json()))

    monkeypatch.setattr(service, "throttled_chat_completion", fake_throttled)
    monkeypatch.setattr(
        service,
        "record_openai_usage",
        lambda response, feature, **kwargs: calls.setdefault(
            "usage", (response, feature, kwargs)
        ),
    )

    result = service.analyze_meal(description="Oatmeal with blueberries")

    assert calls["client"] is fake_client
    assert calls["payload"]["model"] == "configured-nutrition-model"
    assert calls["payload"]["response_format"] == {"type": "json_object"}
    assert calls["throttle"] == {
        "action_name": service.ANALYSIS_ACTION,
        "model": "configured-nutrition-model",
    }
    assert calls["usage"][1] == service.ANALYSIS_ACTION
    assert calls["usage"][2]["model"] == "configured-nutrition-model"
    assert calls["usage"][2]["metadata"] == {"source_kind": "description"}

    assert result["analysis_available"] is True
    assert result["analysis_status"] == "estimated"
    assert result["requires_review"] is True
    assert result["is_estimate"] is True
    assert result["estimate_label"] == service.ESTIMATE_LABEL
    assert result["model_used"] == "configured-nutrition-model"
    assert result["model_source"] == "test override"
    assert result["confidence"] == 0.86
    assert result["nutrition"] == {
        "calories": 282,
        "protein": 8.5,
        "carbohydrates": 52.5,
        "fat": 5.2,
        "fiber": 7.8,
        "sugar": 11,
        "sodium": 180,
    }
    assert result["nutrition_units"]["calories"] == "kcal"
    assert result["nutrition_units"]["sodium"] == "mg"
    assert set(result["nutrition_status"].values()) == {"complete"}
    assert result["food_items"][0]["portion"] == "1.5 cups"
    assert result["food_items"][0]["nutrition_per_unit"]["calories"] == 160
    assert result["food_items"][0]["id"]


def test_photo_and_description_reuse_vision_wrapper_without_exposing_path(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    staged = tmp_path / "private-staged-photo.jpg"
    staged.write_bytes(b"normalized-private-jpeg")
    calls = {}

    def fake_vision(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            ok=True,
            text=json.dumps(_analysis_json()),
            model_used="configured-vision-model",
            model_source="test vision override",
            error_code="",
        )

    monkeypatch.setattr(service, "call_openai_vision_image", fake_vision)

    result = service.analyze_meal(
        description="Oatmeal with blueberries",
        photo_path=staged,
    )

    assert calls["image_path"] == staged
    assert calls["action_name"] == service.ANALYSIS_ACTION
    assert "attached meal photo" in calls["prompt"]
    assert "Oatmeal with blueberries" in calls["prompt"]
    assert result["source_kind"] == "photo_and_description"
    assert result["model_used"] == "configured-vision-model"
    assert result["model_source"] == "test vision override"
    assert str(staged) not in json.dumps(result)


def test_vision_failure_keeps_manual_workflow_and_hides_technical_details(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    staged = tmp_path / "secret-name.jpg"
    staged.write_bytes(b"normalized-private-jpeg")

    monkeypatch.setattr(
        service,
        "call_openai_vision_image",
        lambda **kwargs: SimpleNamespace(
            ok=False,
            text="",
            model_used="configured-vision-model",
            model_source="environment",
            error_code="OPENAI_CONNECTION_ERROR",
            technical_message=f"could not open {staged}",
        ),
    )

    result = service.analyze_meal(photo_path=staged)

    assert result["analysis_available"] is False
    assert result["analysis_status"] == "manual_entry"
    assert result["error_code"] == "OPENAI_CONNECTION_ERROR"
    assert result["food_items"] == []
    assert result["nutrition"] == {}
    assert str(staged) not in json.dumps(result)


def test_route_facing_analysis_resolves_opaque_token_in_active_workspace(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    staged = tmp_path / "workspace-private.jpg"
    staged.write_bytes(b"normalized-private-jpeg")
    calls = {}

    def resolve(token):
        calls["token"] = token
        return staged

    monkeypatch.setattr(photo_service, "resolve_staged_photo", resolve)
    monkeypatch.setattr(
        service,
        "call_openai_vision_image",
        lambda **kwargs: SimpleNamespace(
            ok=True,
            text=json.dumps(_analysis_json()),
            model_used="configured-vision-model",
            model_source="environment",
            error_code="",
        ),
    )

    token = "opaque-photo-token-value-1234567890abcdef"
    result = service.analyze_staged_meal("Breakfast bowl", token)

    assert calls["token"] == token
    assert result["analysis_available"] is True
    assert token not in json.dumps(result)
    assert str(staged) not in json.dumps(result)


def test_route_facing_analysis_handles_cross_workspace_or_expired_token(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    token = "opaque-photo-token-value-1234567890abcdef"

    def unavailable(_token):
        raise photo_service.NutritionPhotoNotFoundError()

    monkeypatch.setattr(photo_service, "resolve_staged_photo", unavailable)

    result = service.analyze_staged_meal("Breakfast bowl", token)

    assert result["analysis_available"] is False
    assert result["analysis_status"] == "manual_entry"
    assert result["source_kind"] == "photo_and_description"
    assert result["error_code"] == "staged_photo_unavailable"
    assert result["nutrition"] == {}
    assert token not in json.dumps(result)


@pytest.mark.parametrize(
    "provider_payload",
    [
        "not json",
        json.dumps({"food_items": []}),
        json.dumps(
            {
                "food_items": [
                    {
                        "name": "Toast",
                        "quantity": 1,
                        "unit": "slice",
                        "nutrition": {"calories": 90},
                    }
                ]
            }
        ),
        json.dumps(
            {
                "food_items": [
                    {
                        "name": "Toast",
                        "quantity": 1,
                        "unit": "slice",
                        "nutrition": {
                            "calories": -90,
                            "protein": 3,
                            "carbohydrates": 17,
                            "fat": 1,
                            "fiber": 1,
                            "sugar": 2,
                            "sodium": 140,
                        },
                    }
                ]
            }
        ),
        json.dumps(
            {
                "food_items": [
                    {
                        "name": "Toast",
                        "unit": "slice",
                        "nutrition": {
                            "calories": 90,
                            "protein": 3,
                            "carbohydrates": 17,
                            "fat": 1,
                            "fiber": 1,
                            "sugar": 2,
                            "sodium": 140,
                        },
                    }
                ]
            }
        ),
        json.dumps(
            {
                "food_items": [
                    {
                        "name": "Toast",
                        "quantity": 1,
                        "nutrition": {
                            "calories": 90,
                            "protein": 3,
                            "carbohydrates": 17,
                            "fat": 1,
                            "fiber": 1,
                            "sugar": 2,
                            "sodium": 140,
                        },
                    }
                ]
            }
        ),
    ],
)
def test_invalid_or_incomplete_provider_data_never_fabricates_nutrition(
    monkeypatch, provider_payload
):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    monkeypatch.setattr(
        service,
        "model_value_for_env",
        lambda env_name: ("configured-nutrition-model", "environment"),
    )
    monkeypatch.setattr(service, "get_openai_client", lambda: object())
    monkeypatch.setattr(
        service,
        "throttled_chat_completion",
        lambda *args, **kwargs: _chat_response(provider_payload),
    )
    monkeypatch.setattr(service, "record_openai_usage", lambda *args, **kwargs: None)

    result = service.analyze_meal(description="Toast")

    assert result["analysis_available"] is False
    assert result["error_code"] == "analysis_response_invalid"
    assert result["food_items"] == []
    assert result["nutrition"] == {}
    assert result["confidence"] is None


def test_provider_exception_returns_manual_review_without_exception_text(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    monkeypatch.setattr(
        service,
        "model_value_for_env",
        lambda env_name: ("configured-nutrition-model", "environment"),
    )
    monkeypatch.setattr(service, "get_openai_client", lambda: object())

    def provider_failure(*args, **kwargs):
        raise RuntimeError("private upstream details")

    monkeypatch.setattr(service, "throttled_chat_completion", provider_failure)

    result = service.analyze_meal(description="Toast")

    assert result["analysis_available"] is False
    assert result["error_code"] == "analysis_unavailable"
    assert "private upstream details" not in json.dumps(result)


def test_description_limit_is_enforced_before_provider_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    monkeypatch.setattr(
        service,
        "throttled_chat_completion",
        lambda *args, **kwargs: pytest.fail("provider should not be called"),
    )

    with pytest.raises(NutritionValidationError) as exc_info:
        service.analyze_meal(description="x" * (service.MAX_DESCRIPTION_LENGTH + 1))

    assert exc_info.value.field == "description"


def test_missing_or_expired_photo_does_not_expose_path(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "tests-only-key")
    missing = tmp_path / "private" / "expired.jpg"

    result = service.analyze_meal(photo_path=missing)

    assert result["error_code"] == "staged_photo_unavailable"
    assert result["analysis_available"] is False
    assert str(missing) not in json.dumps(result)


def test_prompt_requires_units_confidence_and_human_review_language():
    prompt = service.build_meal_analysis_prompt("Rice bowl", includes_photo=True)

    assert "attached meal photo" in prompt
    assert '"food_items"' in prompt
    assert '"fiber"' in prompt
    assert '"sugar"' in prompt
    assert '"sodium"' in prompt
    assert "Use kcal" in prompt
    assert "milligrams" in prompt
    assert "human review" in prompt
